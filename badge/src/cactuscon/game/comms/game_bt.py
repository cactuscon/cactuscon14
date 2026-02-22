"""GameBTComms class - Bluetooth communication protocol for badge battles.

This is the main protocol implementation class that handles:
- Challenge/accept/decline flow
- Handshake and session establishment
- Player data exchange
- Turn-based battle protocol
- Consensus verification
- Connection state management
"""

import bluetooth
import struct
import time
import ubinascii
import uhashlib

from cactuscon.hw.bluetooth import (
    BluetoothManager,
    AVAILABILITY_IDLE,
    AVAILABILITY_OPEN,
    AVAILABILITY_IN_BATTLE,
)
from cactuscon.utils import Logger

from cactuscon.game.comms.protocol import (
    GAME_SERVICE_UUID_TEMPLATE,
    GAME_CHAR_UUID,
    PROTOCOL_VERSION,
    MSG_CHALLENGE_REQUEST,
    MSG_CHALLENGE_ACCEPT,
    MSG_CHALLENGE_DECLINE,
    MSG_HANDSHAKE,
    MSG_HANDSHAKE_ACK,
    MSG_PLAYER_DATA,
    MSG_PLAYER_DATA_ACK,
    MSG_BATTLE_MOVE,
    MSG_BATTLE_STATUS,
    MSG_BATTLE_RESULT,
    MSG_BATTLE_FORFEIT,
    MSG_TURN_READY,
    MSG_TURN_RESOLVE,
    MSG_TURN_CONSENSUS,
    MSG_CONSENSUS_ACK,
    MSG_CONSENSUS_FAIL,
    MSG_TURN_ACK,
    MSG_BATTLE_READY,
    MSG_KEEPALIVE,
    MSG_ERROR,
    PLAYER_DATA_CHARACTER_ID,
    PLAYER_DATA_LEVEL,
    PLAYER_DATA_NAME,
    PLAYER_DATA_BADGE_ID,
    PLAYER_DATA_WINS,
    PLAYER_DATA_LOSSES,
    PLAYER_DATA_CARE_ACTIVITY,
    PLAYER_DATA_CARE_FOOD,
    PLAYER_DATA_POWERS,
    PLAYER_DATA_IS_STATION,
    CHARACTER_TO_ID,
    ID_TO_CHARACTER,
    SESSION_IDLE,
    SESSION_CHALLENGING,
    SESSION_CHALLENGED,
    SESSION_HANDSHAKING,
    SESSION_EXCHANGING_DATA,
    SESSION_BATTLING,
    SESSION_COMPLETE,
    SESSION_ERROR,
    TURN_SELECTING,
    TURN_WAITING,
    TURN_RESOLVING,
    CHALLENGE_TIMEOUT_MS,
    HANDSHAKE_TIMEOUT_MS,
    BATTLE_INACTIVITY_TIMEOUT_MS,
    MOVE_TIMEOUT_MS,
    READY_GRACE_TIMEOUT_MS,
    KEEPALIVE_INTERVAL_MS,
    CONSENSUS_RESEND_INTERVAL_MS,
    CONSENSUS_MAX_SENDS,
    CONSENSUS_TIMEOUT_MS,
    MAX_MESSAGE_SIZE,
)

from cactuscon.game.comms.session import BattleSession

# Module-level service UUID (set at runtime)
GAME_SERVICE_UUID = None



class GameBTComms:
    """
    High-level Bluetooth communication manager for badge battle games.

    Wraps BluetoothManager with game-specific protocol implementation.
    Handles battle session lifecycle, message encoding/decoding, and
    ensures secure isolated communication between two badges.

    Usage:
        bt_mgr = BluetoothManager()
        game_bt = GameBTComms(bt_mgr)

        # Start scanning for opponents
        game_bt.start_opponent_scan()

        # Challenge nearby badge
        opponents = game_bt.get_nearby_opponents()
        if opponents:
            game_bt.challenge_opponent(opponents[0].addr)

        # In main loop, process protocol
        game_bt.update()
    """

    __slots__ = (
        "logger",
        "bt",
        "device_name",
        "service_uuid",
        "session",
        "pending_challenges",
        "last_keepalive",
        "availability",
        "_is_advertising",
        "_resume_server_after_scan",
        "player_data_provider",
        "challenge_callback",
        "battle_start_callback",
        "result_callback",
        "error_callback",
        "cancel_callback",
        "turn_order_callback",
        "turn_resolve_callback",
        "consensus_callback",
        "battle_ready_callback",
        "pending_turn_resolve",
        "server_mode",
        "server_conn_handle",
    )

    def __init__(self, bluetooth_manager, device_name="Badge", logger_level=20):
        """
        Initialize game Bluetooth communications.

        Creates a device-specific service UUID by embedding this badge's
        MAC address into the middle of the UUID. This allows each badge
        to have a unique identifier while still being recognizable as
        a CactusCon badge via the common prefix/suffix.

        Args:
            bluetooth_manager: BluetoothManager instance for BLE operations
            device_name: This badge's display name
            logger_level: Logging level (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR)
        """
        self.logger = Logger(logger_level)
        self.bt: BluetoothManager = bluetooth_manager
        self.device_name = device_name

        # Create device-specific service UUID with embedded MAC address
        global GAME_SERVICE_UUID
        GAME_SERVICE_UUID = BluetoothManager.create_device_uuid(
            GAME_SERVICE_UUID_TEMPLATE
        )
        self.service_uuid = GAME_SERVICE_UUID

        self.logger.info(f"Device service UUID: {GAME_SERVICE_UUID}")

        # Configure BLE service/characteristic for game protocol
        self.bt.service_uuid = self.service_uuid
        self.bt.char_uuid = GAME_CHAR_UUID

        # Session management
        self.session = None  # Current active battle session
        self.pending_challenges = {}  # addr -> (timestamp, opponent_name)
        self.last_keepalive = 0

        # Availability state for matchmaking
        self.availability = AVAILABILITY_IDLE
        self._is_advertising = False
        self._resume_server_after_scan = False

        # Player data provider callback - returns dict with current player data
        # Set by BattleManager to pull from authoritative state
        # Signature: () -> dict with keys: character_id, level, name, wins, losses
        self.player_data_provider = None

        # Message handlers
        self.challenge_callback = None
        self.battle_start_callback = None
        self.result_callback = None
        self.error_callback = None
        self.cancel_callback = None

        # Turn-based battle callbacks
        # turn_order_callback: (our_move, opponent_move) -> bool (True=we go first)
        self.turn_order_callback = None
        # turn_resolve_callback: (turn_number, our_move, opponent_move, we_go_first) -> None
        self.turn_resolve_callback = None
        # consensus_callback: (turn_number, agreed, their_hash) -> None
        self.consensus_callback = None
        # battle_ready_callback: invoked when peer signals UI/asset ready
        self.battle_ready_callback = None

        # Pending turn resolution - deferred to main loop to avoid stack overflow
        # MicroPython has low recursion limit (~50) and BLE IRQ callback chain is deep
        self.pending_turn_resolve = (
            None  # (turn_num, our_move, opponent_move, we_go_first)
        )

        # Server mode state (for receiving connections/challenges)
        self.server_mode = False
        self.server_conn_handle = None  # Connection handle when acting as server

        # Set BLE callbacks
        self.bt.set_data_callback(self._handle_data)
        self.bt.set_disconnect_callback(self._handle_disconnect)

        # Start advertising by default so other badges can discover us
        self.start_advertising()

        self.logger.info(f"GameBTComms initialized for '{device_name}'")

    def _validate_character_id(self, cid):
        """
        Validate and normalize incoming character ID from peer payloads.

        Returns canonical character id string when valid, else None.
        """
        if not isinstance(cid, int):
            return None
        if cid < 0:
            return None
        return ID_TO_CHARACTER.get(cid)

    def _sanitize_name(self, name_bytes, max_len=32):
        """
        Sanitize opponent name from BLE payload.

        Removes control characters, normalizes bad UTF-8, and enforces length.
        """
        if not name_bytes:
            return "Unknown"
        try:
            if not isinstance(name_bytes, (bytes, bytearray, memoryview)):
                name_bytes = str(name_bytes).encode("utf-8")
            decoded = bytes(name_bytes[: max_len * 2]).decode("utf-8", errors="replace")
            cleaned = "".join(ch for ch in decoded if ch.isprintable() or ch == " ")
            cleaned = cleaned.strip()
            if len(cleaned) > max_len:
                cleaned = cleaned[:max_len]
            return cleaned or "Unknown"
        except Exception as exc:
            self.logger.warning(f"Name sanitize failed: {exc}")
            return "Unknown"

    def _validate_message_length(self, msg_type, data, signed=False):
        """
        Validate message length against per-type minimums.

        Args:
            msg_type: protocol message type byte
            data: received bytes payload
            signed: True when an HMAC signature is expected
        """
        min_lengths = {
            MSG_CHALLENGE_REQUEST: 4,
            MSG_CHALLENGE_ACCEPT: 4,
            MSG_HANDSHAKE: 27,
            MSG_HANDSHAKE_ACK: 9,
            MSG_PLAYER_DATA: 2,
            MSG_BATTLE_STATUS: 4,
            MSG_BATTLE_RESULT: 2,
            MSG_TURN_READY: 5,
            MSG_TURN_ACK: 3,
            MSG_TURN_CONSENSUS: 19,
            MSG_BATTLE_READY: 1,
            MSG_KEEPALIVE: 1,
            MSG_ERROR: 3,
        }
        min_len = min_lengths.get(msg_type, 1)
        expected = min_len + (16 if signed else 0)
        if len(data) < expected:
            self.logger.warning(
                f"Message type 0x{msg_type:02x} too short: {len(data)} < {expected}"
            )
            return False
        return True

    def start_advertising(self, availability=None):
        """
        Start advertising this badge with availability status.

        Uses multiple BLE advertisement data types:
        1. Service Data: Device-specific UUID + availability state
        2. Complete Local Name: Badge display name

        The device UUID contains the MAC address embedded in the middle,
        allowing other badges to identify this specific device without
        needing a separate device ID field.

        Args:
            availability: AVAILABILITY_* constant (None = use current state)

        Returns:
            True if advertising started successfully

        Notes:
            - AVAILABILITY_IDLE: Badge visible but not accepting challenges
            - AVAILABILITY_OPEN: Badge actively looking for battles
            - AVAILABILITY_IN_BATTLE: Badge in battle (shouldn't challenge)

        Advertisement Structure (within 31-byte limit):
            - Flags: 3 bytes (mandatory)
            - Service Data (128-bit UUID): 19 bytes (1 len + 1 type + 16 UUID + 1 availability)
            - Shortened Name: ~7 bytes (for passive scanners)
            Total: ~29 bytes
        
        Scan Response (for active scanners, another 31 bytes):
            - Complete Local Name: Up to 29 bytes (full badge name)

        Example:
            >>> game_bt = GameBTComms(bt_manager, device_name="MyBadge")
            >>> # Device UUID is CC140001-AABB-CCDD-EEFF-CAC71B072026
            >>> # where AABBCCDDEEFF is this badge's MAC address
            >>> game_bt.start_advertising(AVAILABILITY_OPEN)
            True

            Other badges scanning will see:
            - Service UUID: CC140001-AABB-CCDD-EEFF-CAC71B072026
            - Availability: OPEN (looking for battles)
            - Name: "MyBadge"

            They can extract your MAC: extract_mac_from_uuid() → AA:BB:CC:DD:EE:FF
        """
        if availability is not None:
            self.availability = availability

        # Advertise using service data (includes UUID + availability state)
        # This is the most space-efficient way to advertise both service and data
        service_data = {self.service_uuid: bytes([self.availability])}

        self._is_advertising = self.bt.start_advertising(
            name=self.device_name,
            service_data=service_data,
        )

        availability_str = ["IDLE", "OPEN", "IN_BATTLE"][self.availability]
        if self._is_advertising:
            self.logger.info(f"Advertising as {availability_str}")

        return self._is_advertising

    def stop_advertising(self):
        """
        Stop advertising this badge.

        Call this during battles to prevent new challenge attempts.

        Returns:
            True if advertising stopped successfully
        """
        self._is_advertising = False
        return self.bt.stop_advertising()

    def set_availability(self, availability):
        """
        Update matchmaking availability status.

        Use this to signal whether your badge is open to battle challenges:
        - AVAILABILITY_IDLE: Not looking for battles (default)
        - AVAILABILITY_OPEN: Actively seeking opponents
        - AVAILABILITY_IN_BATTLE: Currently in battle

        Args:
            availability: AVAILABILITY_* constant
        """
        old_state = self.availability
        self.availability = availability

        # Restart advertising with new state; if not currently advertising, start it
        if self._is_advertising:
            self.stop_advertising()
            # Small delay to let NimBLE complete the stop operation
            # This prevents os_memblock_get failures from rapid start/stop cycles
            time.sleep_ms(100)
        self.start_advertising()

        availability_str = ["IDLE", "OPEN", "IN_BATTLE"][availability]
        self.logger.info(f"Availability changed to {availability_str}")

    def is_available_for_battle(self):
        """
        Check if this badge is currently available for battle challenges.

        Returns:
            True if availability is OPEN and not in an active session
        """
        return self.availability == AVAILABILITY_OPEN and (
            not self.session
            or self.session.state in (SESSION_IDLE, SESSION_COMPLETE, SESSION_ERROR)
        )

    def set_player_data(
        self,
        character_id,
        level=1,
        name=None,
        badge_id=None,
        wins=0,
        losses=0,
        care_activity=None,
        care_food=None,
        is_station=False,
        powers=None,
    ):
        """
        Set our player data for the battle session.

        This should be called before accepting/sending a challenge. The data
        will be exchanged after the handshake completes.

        Args:
            character_id: String character ID (e.g., 'hacktarmon') or numeric ID
            level: Character level (1-255)
            name: Player display name (optional)
            badge_id: Badge unique ID bytes (optional)
            wins: Total win count (optional)
            losses: Total loss count (optional)
            care_activity: Active activity effect ID (optional)
            care_food: Active food effect ID (optional)
            powers: Iterable of active achievement power IDs (optional)
        """
        # Convert string ID to numeric if needed
        if isinstance(character_id, str):
            numeric_id = CHARACTER_TO_ID.get(character_id)
        else:
            numeric_id = character_id

        # Validate character ID (must map to a known character)
        if numeric_id is None or numeric_id not in ID_TO_CHARACTER:
            raise ValueError(f"Unknown character_id: {character_id}")

        # Build player data dict
        player_data = {
            PLAYER_DATA_CHARACTER_ID: numeric_id,
            PLAYER_DATA_LEVEL: min(255, max(1, level)),
            PLAYER_DATA_IS_STATION: 1 if is_station else 0,
        }
        if name:
            player_data[PLAYER_DATA_NAME] = name
        if badge_id:
            player_data[PLAYER_DATA_BADGE_ID] = badge_id
        if wins > 0:
            player_data[PLAYER_DATA_WINS] = wins
        if losses > 0:
            player_data[PLAYER_DATA_LOSSES] = losses
        if care_activity:
            player_data[PLAYER_DATA_CARE_ACTIVITY] = care_activity
        if care_food:
            player_data[PLAYER_DATA_CARE_FOOD] = care_food
        if powers:
            if isinstance(powers, (list, tuple)):
                powers_val = ",".join(powers)
            else:
                powers_val = str(powers)
            if powers_val:
                player_data[PLAYER_DATA_POWERS] = powers_val

        if self.session:
            self.session.our_player_data = player_data
            self.logger.debug(f"Set player data on session: {player_data}")
        else:
            self.logger.warning(
                "set_player_data called with no active session - data will be lost"
            )

    def get_opponent_character_id(self):
        """Get opponent's character ID (numeric) from exchanged player data."""
        if not self.session or not self.session.opponent_player_data:
            raise ValueError("Opponent character data missing")
        if PLAYER_DATA_CHARACTER_ID not in self.session.opponent_player_data:
            raise ValueError("Opponent character ID not provided")
        char_id = self.session.opponent_player_data[PLAYER_DATA_CHARACTER_ID]
        if char_id not in ID_TO_CHARACTER:
            raise ValueError(f"Unknown opponent character ID: {char_id}")
        return char_id

    def get_opponent_level(self):
        """Get opponent's level from exchanged player data."""
        if self.session and self.session.opponent_player_data:
            return self.session.opponent_player_data.get(PLAYER_DATA_LEVEL, 1)
        return 1

    def get_opponent_care_effects(self):
        """Get opponent's active care effect IDs (activity/food) from exchanged data."""
        if not self.session or not self.session.opponent_player_data:
            return {"activity": None, "food": None}
        activity = self.session.opponent_player_data.get(
            PLAYER_DATA_CARE_ACTIVITY, None
        )
        food = self.session.opponent_player_data.get(PLAYER_DATA_CARE_FOOD, None)
        return {
            "activity": activity or None,
            "food": food or None,
        }

    def get_opponent_power_effects(self):
        """Get opponent's active achievement power IDs from exchanged data."""
        if not self.session or not self.session.opponent_player_data:
            return []
        powers = self.session.opponent_player_data.get(PLAYER_DATA_POWERS, "")
        if not powers:
            return []
        if isinstance(powers, (list, tuple)):
            return list(powers)
        if isinstance(powers, str):
            return [p for p in powers.split(",") if p]
        return []

    def start_server_mode(self):
        """
        Start GATT server to accept incoming connections from challengers.

        In server mode, this badge can receive challenge requests and battle
        data from other badges connecting as clients. This is required for
        AUTO_BATTLE_MODE where the badge (or station) accepts challengers.

        Server mode allows bidirectional communication:
        - Client writes to server's characteristic → server receives data
        - Server sends notifications → client receives data

        Returns:
            bool: True if server started successfully.
        """
        self.logger.debug("[COMMS] start_server_mode: entering...")
        if self.server_mode:
            self.logger.debug("Server mode already active")
            self.logger.debug("[COMMS] start_server_mode: already active")
            return True

        # Setup GATT server with game service/characteristic
        self.logger.debug("[COMMS] start_server_mode: calling setup_gatt_server...")
        
        success = self.bt.setup_gatt_server(self.service_uuid, GAME_CHAR_UUID)
        self.logger.info(
            "[COMMS] start_server_mode: setup_gatt_server returned {}".format(success)
        )

        if success:
            self.server_mode = True
            # Set server-specific data callback
            self.bt.set_server_data_callback(self._handle_server_data)
            self.logger.info(
                "[COMMS] start_server_mode: server_char_handle={}".format(
                    self.bt.server_char_handle
                )
            )

        return success

    def stop_server_mode(self):
        """
        Stop GATT server and disconnect any connected challengers.

        Returns:
            bool: True if server stopped successfully.
        """
        if not self.server_mode:
            return True

        self.bt.stop_gatt_server()
        self.server_mode = False
        self.server_conn_handle = None
        self.logger.info("Server mode stopped")
        return True

    def is_server_mode(self):
        """
        Check if currently accepting incoming connections.

        Returns:
            bool: True if in server mode.
        """
        return self.server_mode

    def _handle_server_data(self, conn_handle, data):
        """
        Handle data received via GATT server write.

        Called when a connected client writes to our characteristic.
        Routes to the same message handler as client-received data.

        Args:
            conn_handle (int): Connection handle of the writer.
            data (bytes): Data received.
        """
        self.server_conn_handle = conn_handle
        self._handle_data(data)

    def _send_message_server(self, payload):
        """
        Send message via server notification (when in server mode).

        Uses GATT notifications to respond to the connected client.

        Args:
            payload (bytes): Message payload.

        Returns:
            bool: True if sent successfully.
        """
        if not self.server_mode:
            return False

        return self.bt.server_notify(payload, self.server_conn_handle)

    def start_opponent_scan(self, duration_ms=0):
        """
        Start scanning for potential battle opponents.

        Scans for badges broadcasting the CactusCon game service.
        Continuous scan (duration_ms=0) recommended for battle mode.

        **Important Side Effects:**
        - Stops advertising while scanning (BLE limitation: can't scan and advertise simultaneously)
        - Advertising automatically resumes when scan completes via stop_opponent_scan()
        - Call stop_opponent_scan() to manually stop and resume advertising

        Args:
            duration_ms: Scan duration (0 = continuous until stopped)

        Returns:
            True if scan started successfully, False if already in battle

        Example:
            >>> game_bt.start_opponent_scan(duration_ms=5000)  # 5 second scan
            >>> time.sleep(5.5)
            >>> opponents = game_bt.get_nearby_opponents()
        """
        if self.session and self.session.state in (
            SESSION_HANDSHAKING,
            SESSION_BATTLING,
        ):
            self.logger.warning("Cannot scan during active battle session")
            return False

        # Check if already scanning - don't restart
        if self.bt.is_scanning():
            self.logger.debug("Already scanning, ignoring duplicate request")
            return True

        self.logger.info("Starting opponent scan...")

        # Proactively reset connection state to ensure clean slate
        # This prevents freezes from stale state after failed challenges
        self.bt.reset_connection_state()

        # Stop advertising while scanning (can't do both simultaneously)
        if self.server_mode:
            # Suspend server mode during scan; restore after scan completes
            self._resume_server_after_scan = True
            self.stop_server_mode()
        if self._is_advertising:
            self.stop_advertising()
            # Give NimBLE time to complete the advertising stop
            # This prevents os_memblock_get failures from rapid BLE operation changes
            time.sleep_ms(100)

        # Active scanning is required to receive scan responses (resp_data) that contain
        # the full handle; adv_data only carries the shortened hash. Enabling active=True
        # triggers SCAN_RSP events so we can stitch full handles to the hashed entries.
        return self.bt.start_scan(duration_ms=duration_ms, active=True)

    def stop_opponent_scan(self):
        """
        Stop scanning for opponents.

        Resumes advertising after scan completes so this badge
        remains discoverable.

        Returns:
            True if scan stopped successfully
        """
        success = self.bt.stop_scan()

        # Resume advertising after scan with delay for NimBLE stability
        if success and not self.is_in_battle():
            # Give NimBLE time to complete the scan stop
            time.sleep_ms(50)
            if (
                self._resume_server_after_scan
                and not self.server_mode
                and self.availability == AVAILABILITY_OPEN
            ):
                self.start_server_mode()
            self._resume_server_after_scan = False
            self.start_advertising()

        return success

    def _enrich_device_names(self, min_rssi, limit):
        """
        Run a short active scan to collect scan responses (resp_data) so we get
        complete device names instead of shortened ADV names.
        """
        if self.is_in_battle() or self.bt.is_scanning():
            return

        was_advertising = self._is_advertising
        if was_advertising:
            self.stop_advertising()
            time.sleep_ms(50)

        # Short, aggressive active scan to pull scan responses
        self.bt.reset_connection_state()
        duration = 800  # ms
        self.bt.start_scan(duration_ms=duration, active=True)
        time.sleep_ms(duration + 50)
        self.bt.stop_scan()

        if was_advertising and not self.is_in_battle():
            self.start_advertising()

    def get_nearby_opponents(self, min_rssi=-70, limit=10, only_available=True):
        """
        Get list of nearby badges available for battle.

        Filters to show strongest signals for best connection quality.
        Automatically filters to only CactusCon badges by looking for the
        standard UUID prefix/suffix pattern (CC140001-****-****-****-CAC71B072026).

        Uses BluetoothManager.get_available_badges() which leverages the
        already-parsed BluetoothDevice fields (is_cactuscon_badge, availability).

        Args:
            min_rssi: Minimum signal strength (-70 dBm recommended for stable connection)
            limit: Maximum number of opponents to return
            only_available: If True, only return badges in AVAILABILITY_OPEN state (default: True)

        Returns:
            List of BluetoothDevice objects sorted by proximity (RSSI)
            Each device's service UUID contains the opponent's MAC address embedded

        Example:
            >>> game_bt.start_opponent_scan()  # Start scanning
            >>> time.sleep(2)  # Scan for 2 seconds
            >>> opponents = game_bt.get_nearby_opponents(min_rssi=-70, limit=5)
            >>> for opponent in opponents:
            ...     print(f"Found: {opponent.name} (RSSI: {opponent.rssi})")
            ...     # Get their MAC from the parsed BluetoothDevice
            ...     mac = opponent.get_embedded_mac()
            ...     print(f"  MAC: {BluetoothManager.format_address(mac)}")
            Found: Badge42 (RSSI: -45)
              MAC: aa:bb:cc:dd:ee:ff
            Found: BadgeX (RSSI: -52)
              MAC: 11:22:33:44:55:66
        """
        station_names = self._get_station_names()
        station_min_rssi = -95

        if only_available:
            # Use the optimized BluetoothManager method that filters by availability
            devices = self.bt.get_available_badges(min_rssi=min_rssi)
        else:
            # Get all CactusCon badges regardless of availability
            devices = self.bt.get_nearby_devices(min_rssi=min_rssi)
            devices = [d for d in devices if d.is_cactuscon_badge]

        # If we have short/unknown names in the top set, run a quick active scan
        # to pull scan responses (which carry the full name) before returning.
        if devices and any((not d.name) or len(d.name) < 12 for d in devices[:limit]):
            self.logger.debug("Enriching device names via short active scan...")
            self._enrich_device_names(min_rssi=min_rssi, limit=limit)
            # Re-fetch after enrichment
            if only_available:
                devices = self.bt.get_available_badges(min_rssi=min_rssi)
            else:
                devices = self.bt.get_nearby_devices(min_rssi=min_rssi)
                devices = [d for d in devices if d.is_cactuscon_badge]

        station_candidates = self._get_station_candidates(
            station_names, station_min_rssi, only_available
        )
        if station_candidates and any(
            (not d.name) or len(d.name) < 12 for d in station_candidates[:limit]
        ):
            self.logger.debug("Enriching station names via short active scan...")
            self._enrich_device_names(min_rssi=station_min_rssi, limit=limit)
            station_candidates = self._get_station_candidates(
                station_names, station_min_rssi, only_available
            )
        if station_candidates:
            devices = devices + station_candidates

        # De-duplicate by address and re-sort by RSSI
        if devices:
            by_addr = {}
            for dev in devices:
                try:
                    by_addr[dev.addr] = dev
                except Exception as exc:
                    self.logger.debug(f"Skipping device without stable addr: {exc}")
            devices = list(by_addr.values())
            try:
                devices.sort(key=lambda d: d.rssi, reverse=True)
            except Exception as exc:
                self.logger.debug(f"Device sort by RSSI failed: {exc}")

        # Apply limit
        if limit and len(devices) > limit:
            devices = devices[:limit]

        return devices

    def _get_station_names(self):
        try:
            from cactuscon.game.engine.stations import get_station_registry
            return {
                (s.name or "").strip().lower()
                for s in get_station_registry().all()
                if s and s.name
            }
        except Exception as exc:
            self.logger.debug(f"Station registry unavailable: {exc}")
            return set()

    def _is_station_device(self, device, station_names):
        try:
            name = (device.name or "").strip().lower()
        except Exception:
            name = ""
        return bool(name and name in station_names)

    def _get_station_candidates(self, station_names, station_min_rssi, only_available):
        if not station_names:
            return []
        if only_available:
            candidates = self.bt.get_available_badges(min_rssi=station_min_rssi)
        else:
            candidates = self.bt.get_nearby_devices(min_rssi=station_min_rssi)
            candidates = [d for d in candidates if d.is_cactuscon_badge]
        return [d for d in candidates if self._is_station_device(d, station_names)]

    def challenge_opponent(self, opponent_addr, timeout_ms=CHALLENGE_TIMEOUT_MS):
        """
        Initiate a battle challenge to a specific opponent.

        Connects to opponent badge and sends challenge request.
        Response delivered via challenge_callback.

        Args:
            opponent_addr: Opponent's BLE MAC address (bytes or string)
            timeout_ms: Challenge timeout in milliseconds

        Returns:
            True if challenge initiated, False on error
        """
        if self.session and self.session.state in (
            SESSION_CHALLENGING,
            SESSION_CHALLENGED,
            SESSION_HANDSHAKING,
            SESSION_EXCHANGING_DATA,
            SESSION_BATTLING,
        ):
            self.logger.warning("Challenge already in progress")
            return False

        # Convert address if needed
        if isinstance(opponent_addr, str):
            opponent_addr = BluetoothManager.parse_address(opponent_addr)

        # Stop advertising and scanning before battle - MUST complete before connect
        self.stop_advertising()

        # Stop scanning and wait for it to complete
        if self.bt.is_scanning():
            self.bt.stop_scan()
            # Give NimBLE time to fully stop scanning before attempting connect
            # This prevents BLE stack conflicts that cause freezes
            time.sleep_ms(150)

        # Reset connection state to ensure clean slate
        self.bt.reset_connection_state()

        # Create new session as challenger
        session_id = uhashlib.sha1(
            opponent_addr + str(time.ticks_ms()).encode()
        ).digest()[:8]
        self.session = BattleSession(session_id, opponent_addr, is_challenger=True)
        self.session.state = SESSION_CHALLENGING

        addr_str = BluetoothManager.format_address(opponent_addr)
        self.logger.info("Challenging opponent: {}".format(addr_str))

        # Connect to opponent
        def on_connect(conn_handle, addr_type, addr):
            self.logger.debug("[COMMS] on_connect callback entered")
            self.logger.info("Connected, requesting MTU exchange...")

            # Request larger MTU for battle messages (default is 23 bytes = 20 byte payload)
            # Battle messages can be up to ~100 bytes, so request 128 to be safe
            try:
                self.logger.debug("[COMMS] on_connect: calling gattc_exchange_mtu...")
                self.bt.ble.gattc_exchange_mtu(conn_handle)
                self.logger.debug("[COMMS] on_connect: gattc_exchange_mtu returned")
                # Give MTU exchange time to complete
                time.sleep_ms(100)
            except Exception as e:
                self.logger.debug("[COMMS] on_connect: MTU exchange failed: {}".format(e))
                # Continue anyway - some devices don't support MTU exchange

            self.logger.debug("[COMMS] on_connect: calling _discover_services...")
            # Discover GATT services and characteristics
            self._discover_services()
            self.logger.debug("[COMMS] on_connect: _discover_services returned")

        self.logger.debug("[COMMS] challenge_opponent: calling bt.connect...")
        # Ensure we are acting as client (disable server_mode to avoid server_notify path)
        self.stop_server_mode()
        self._resume_server_after_scan = False
        try:
            result = self.bt.connect(opponent_addr, callback=on_connect)
        except Exception as exc:
            self.logger.error(f"[COMMS] challenge_opponent: bt.connect failed: {exc}")
            self._handle_error("Failed to connect")
            self.end_session()
            return False
        self.logger.debug(
            "[COMMS] challenge_opponent: bt.connect returned {}".format(result)
        )
        if not result:
            self._handle_error("Failed to connect")
            self.end_session()
            return False
        return True

    def accept_challenge(self, opponent_addr):
        """
        Accept an incoming battle challenge.

        Args:
            opponent_addr: Challenger's BLE MAC address (bytes or string)

        Returns:
            True if acceptance sent, False on error
        """
        if isinstance(opponent_addr, str):
            opponent_addr = BluetoothManager.parse_address(opponent_addr)

        if opponent_addr not in self.pending_challenges:
            self.logger.warning("No pending challenge from that opponent")
            return False

        # Get challenge info (timestamp, name)
        challenge_info = self.pending_challenges[opponent_addr]
        if isinstance(challenge_info, tuple):
            _, opponent_name = challenge_info
        else:
            # Legacy: just timestamp (backwards compat)
            opponent_name = "Unknown"

        # Create session as challengee
        session_id = uhashlib.sha1(
            opponent_addr + str(time.ticks_ms()).encode()
        ).digest()[:8]
        self.session = BattleSession(session_id, opponent_addr, is_challenger=False)
        self.session.opponent_name = opponent_name  # Store opponent name
        self.session.state = SESSION_CHALLENGED

        self.logger.info(f"Accepting challenge from {opponent_name}...")

        # Send acceptance
        self._send_challenge_accept()

        # Remove from pending
        del self.pending_challenges[opponent_addr]

        return True

    def decline_challenge(self, opponent_addr):
        """
        Decline an incoming battle challenge.

        Args:
            opponent_addr: Challenger's BLE MAC address (bytes or string)

        Returns:
            True if decline sent successfully, False if no pending challenge
        """
        if isinstance(opponent_addr, str):
            opponent_addr = BluetoothManager.parse_address(opponent_addr)

        if opponent_addr not in self.pending_challenges:
            self.logger.warning("No pending challenge from that opponent")
            return False

        # Remove from pending before sending decline
        del self.pending_challenges[opponent_addr]

        # Send decline message
        self._send_challenge_decline(opponent_addr)

        return True

    def send_status(self, hp, status_flags=0, status_data=None):
        """
        Send battle status update to opponent.

        Args:
            hp: Current HP value (0-65535)
            status_flags: Status effect bitmask
            status_data: Optional additional status info (bytes)

        Returns:
            True if sent successfully, False if not in battle state
        """
        if not self.session:
            self.logger.error("Cannot send status: no active session")
            return False

        if self.session.state != SESSION_BATTLING:
            self.logger.error("Cannot send status: not in battling state")
            return False

        payload = struct.pack("<BHB", MSG_BATTLE_STATUS, hp, status_flags)
        if status_data:
            payload += status_data

        return self._send_message(payload)

    def send_battle_result(self, winner, result_data=None):
        """
        Send battle result to opponent.

        Args:
            winner: 0=draw, 1=us, 2=opponent
            result_data: Optional result details (bytes)

        Returns:
            True if sent successfully
        """
        if not self.session:
            self.logger.warning("No active session")
            return False

        payload = struct.pack("<BB", MSG_BATTLE_RESULT, winner)
        if result_data:
            payload += result_data

        success = self._send_message(payload)

        if success:
            self.session.state = SESSION_COMPLETE
            self.logger.info(f"Battle complete (winner={winner})")

        return success

    def forfeit_battle(self):
        """
        Forfeit current battle and notify opponent.

        Returns:
            True if forfeit sent, False if not in battle state
        """
        if not self.session:
            self.logger.error("Cannot forfeit: no active session")
            return False

        if self.session.state != SESSION_BATTLING:
            self.logger.error(
                "Cannot forfeit: not in battling state (current state: {})".format(
                    self.session.state
                )
            )
            return False

        payload = struct.pack("<B", MSG_BATTLE_FORFEIT)
        success = self._send_message(payload)

        if success:
            self.session.state = SESSION_COMPLETE
            self.logger.info("Battle forfeited")

        return success

    def end_session(self):
        """
        End current battle session and disconnect.

        Call this after battle completion to cleanup and release connection.
        Returns to IDLE state (discoverable but not actively looking for battles).

        Performs full BLE state cleanup to prevent freezes on next scan.
        Also clears any pending protocol state (e.g., deferred turn resolution).
        """
        if self.session:
            self.logger.info("Ending battle session...")
            self.session = None
        # Clear any pending turn resolution (deferred from previous battle)
        if self.pending_turn_resolve is not None:
            self.logger.info("Clearing pending_turn_resolve from previous session.")
            self.pending_turn_resolve = None
        # Clear server connection handle
        self.server_conn_handle = None
        # Force disconnect if connected (handles both client and server connections)
        if self.bt.is_connected():
            self.bt.disconnect()
            # Give disconnect time to complete
            time.sleep_ms(100)
        # Reset all connection state (clears pending callbacks, char handles, etc.)
        self.bt.reset_connection_state()
        # Stop any active scanning (in case we were mid-scan when challenge started)
        if self.bt.is_scanning():
            self.bt.stop_scan()
        # Return to IDLE state - discoverable but not actively looking for battles
        # User must explicitly enter matchmaking mode again
        self.set_availability(AVAILABILITY_IDLE)
        self.start_advertising()

    def update(self):
        """
        Update game protocol state machine.

        Call this regularly (e.g., in main loop) to:
        - Process pending BLE callbacks (deferred from IRQ context)
        - Process pending turn resolution (deferred from BLE IRQ)
        - Check for session timeouts
        - Send keepalive messages
        - Clean up expired challenges
        - Process pending protocol state changes

        Recommended: Call every 100-500ms
        """
        # --- DEBUG: Log main loop and session state ---
        # No debug log here; log only on state transitions or key protocol events
        # Process pending BLE callbacks (connection, etc.) - MUST be outside IRQ
        self.bt.process_pending()

        # Process pending turn resolution (deferred from BLE IRQ to avoid stack overflow)
        self._process_pending_turn_resolve()

        now = time.ticks_ms()

        # If we think we have an active session but the BLE link is down, fail fast.
        # This covers edge cases where we suppressed a disconnect during an asset-load
        # grace period or the lower layer didn't surface a callback promptly.
        if (
            self.session
            and self.session.state in (SESSION_HANDSHAKING, SESSION_EXCHANGING_DATA, SESSION_BATTLING)
            and not self.bt.is_connected()
        ):
            self.logger.warning("Session active but BLE is disconnected; ending session")
            self._handle_error("Connection lost")
            self.end_session()
            return

        # Send keepalive if connected and battling
        if (
            self.session
            and self.session.state == SESSION_BATTLING
            and time.ticks_diff(now, self.last_keepalive) > KEEPALIVE_INTERVAL_MS
        ):
            self._send_keepalive()
            self.last_keepalive = now

        # Retry TURN_READY if sent but not acked within 3s to avoid desync.
        # If we already have the opponent's move, treat it as implicit ack to avoid stalls.
        if (
            self.session
            and self.session.state == SESSION_BATTLING
            and self.session.turn_move_sent
            and not self.session.turn_move_acked
            and self.session.our_move is not None
        ):
            if self.session.opponent_move is not None:
                # Opponent sent their move, so they almost certainly received ours
                self.session.turn_move_acked = True
                self._maybe_resolve_turn("Implicit ACK via opponent move; resolving.")
            else:
                last_ts = self.session.last_turn_ready_ts or 0
                if time.ticks_diff(now, last_ts) >= 3000:
                    self.logger.warning(
                        f"Resending TURN_READY for turn {self.session.turn_number} (no ACK yet)"
                    )
                    self._send_turn_ready_message(force=True)

        # Retry consensus hash if we're waiting on opponent hash/ACK
        if (
            self.session
            and self.session.state in (SESSION_BATTLING, SESSION_COMPLETE)
            and self.session.our_consensus_hash is not None
            and self.session.their_consensus_hash is None
            and self.session.consensus_turn is not None
        ):
            last_ts = self.session.last_consensus_send_ts or 0
            if time.ticks_diff(now, last_ts) >= CONSENSUS_RESEND_INTERVAL_MS:
                if self.session.consensus_send_attempts < CONSENSUS_MAX_SENDS:
                    payload = struct.pack(
                        "<BH", MSG_TURN_CONSENSUS, self.session.consensus_turn
                    )
                    payload += self.session.our_consensus_hash[:16]
                    if self._send_message(payload):
                        self.session.consensus_send_attempts += 1
                        try:
                            self.session.last_consensus_send_ts = time.ticks_ms()
                        except Exception:
                            self.session.last_consensus_send_ts = 0
                        self.logger.warning(
                            f"Resent CONSENSUS hash for turn {self.session.consensus_turn} "
                            f"(attempt {self.session.consensus_send_attempts})"
                        )
                else:
                    if time.ticks_diff(now, last_ts) >= CONSENSUS_TIMEOUT_MS:
                        self.logger.error(
                            "Consensus timeout - no opponent hash/ACK received"
                        )
                        self._handle_error("Consensus timeout")
                        self.end_session()

        # If both moves are present but we're still waiting on ACK, resolve anyway
        if (
            self.session
            and self.session.state == SESSION_BATTLING
            and self.session.our_move is not None
            and self.session.opponent_move is not None
            and self.session.turn_move_sent
        ):
            self._maybe_resolve_turn(
                f"Both moves present for turn {self.session.turn_number}, resolving."
            )

        # Check session timeout
        if self.session:
            if self.session.state == SESSION_CHALLENGING and self.session.is_expired(
                CHALLENGE_TIMEOUT_MS
            ):
                self.logger.warning("Challenge timeout")
                self._handle_error("Challenge timeout")
                self.end_session()
                self._notify_ui_cancel("challenge_timeout")

            elif self.session.state == SESSION_HANDSHAKING and self.session.is_expired(
                HANDSHAKE_TIMEOUT_MS
            ):
                self.logger.warning("Handshake timeout")
                self._handle_error("Handshake timeout")
                self.end_session()
                self._notify_ui_cancel("handshake_timeout")

            elif self.session.state == SESSION_BATTLING and self.session.is_expired(
                BATTLE_INACTIVITY_TIMEOUT_MS
            ):
                self.logger.warning("Inactivity timeout - opponent silent")
                self._handle_error("Inactivity timeout")
                self.end_session()

        # Clean up expired challenges (pending_challenges: addr -> (timestamp, name))
        expired = []
        for addr, info in self.pending_challenges.items():
            ts = (
                info[0] if isinstance(info, tuple) else info
            )  # Handle (ts, name) or just ts
            if time.ticks_diff(now, ts) > CHALLENGE_TIMEOUT_MS:
                expired.append(addr)
        for addr in expired:
            del self.pending_challenges[addr]

    def _process_pending_turn_resolve(self):
        """
        Process pending turn resolution deferred from BLE IRQ.

        Called from update() to handle turn order determination AND
        turn_resolve_callback outside of the BLE callback stack,
        avoiding MicroPython's low recursion limit (~50).

        Turn order is determined here (not in IRQ) because
        turn_order_callback can also exceed stack depth.
        """
        if self.pending_turn_resolve is None:
            return
        turn_num, our_move, opponent_move, is_challenger = self.pending_turn_resolve
        self.logger.info(
            f"[MainLoop] Processing pending turn resolve: turn={turn_num}, our_move={our_move[0]}, opponent_move={opponent_move[0]}, is_challenger={is_challenger}"
        )
        # --- DEBUG: Log full session state at turn resolve ---
        if self.session:
            self.logger.debug(
                f"[TurnResolve] session_id={ubinascii.hexlify(self.session.session_id).decode()}, state={self.session.state}, turn={self.session.turn_number}, turn_state={self.session.turn_state}, our_move={self.session.our_move}, opponent_move={self.session.opponent_move}, our_data_sent={self.session.our_data_sent}, opponent_data_received={self.session.opponent_data_received}, our_player_data={self.session.our_player_data}, opponent_player_data={self.session.opponent_player_data}"
            )
        self.pending_turn_resolve = None
        # Determine turn order (now safe - we're in main loop, not IRQ)
        we_go_first = is_challenger  # Default: challenger goes first
        if self.turn_order_callback:
            try:
                we_go_first = self.turn_order_callback(our_move, opponent_move)
            except Exception as e:
                self.logger.error(f"Turn order callback error: {e}")
                # Fall back to challenger-first on error
                we_go_first = is_challenger
        self.logger.info(
            f"Resolving turn {turn_num}: us={our_move[0]}, them={opponent_move[0]}, we_first={we_go_first}"
        )
        # NOTE: Do NOT call move_callback here - it conflicts with consensus!
        # The legacy move_callback executes moves without the deterministic RNG,
        # causing hash mismatches. All move execution happens in turn_resolve_callback.
        # Call turn resolve callback with determined order
        if self.turn_resolve_callback:
            try:
                self.turn_resolve_callback(
                    turn_num, our_move, opponent_move, we_go_first
                )
            except Exception as e:
                self.logger.error(f"Turn resolve callback error: {e}")

    def is_in_battle(self):
        """Check if currently in an active battle."""
        return self.session is not None and self.session.state in (
            SESSION_HANDSHAKING,
            SESSION_BATTLING,
        )

    def get_session_info(self):
        """
        Get current session information.

        Returns:
            Dict with session details or None if no active session
        """
        if self.session:
            return {
                "session_id": ubinascii.hexlify(self.session.session_id).decode(),
                "opponent_addr": BluetoothManager.format_address(
                    self.session.opponent_addr
                ),
                "opponent_name": self.session.opponent_name,
                "state": self.session.state,
                "is_challenger": self.session.is_challenger,
                "duration_ms": self.session.duration_ms(),
                "age_ms": self.session.age_ms(),
            }
        return None

    # Callback setters

    def on_challenge_received(self, callback):
        """Set callback for incoming challenges: callback(opponent_addr, opponent_name)"""
        self.challenge_callback = callback

    def on_battle_start(self, callback):
        """Set callback for battle start: callback(session)"""
        self.battle_start_callback = callback

    def on_result_received(self, callback):
        """Set callback for battle results: callback(winner, result_data)"""
        self.result_callback = callback

    def on_error(self, callback):
        """Set callback for protocol errors: callback(error_code, message)"""
        self.error_callback = callback

    def on_turn_order(self, callback):
        """
        Set callback for determining turn order.

        callback(our_move, opponent_move) -> bool
            our_move: tuple (move_id, move_data)
            opponent_move: tuple (move_id, move_data)
            Returns: True if we go first, False if opponent goes first

        If not set, challenger always goes first.
        """
        self.turn_order_callback = callback

    def on_turn_resolve(self, callback):
        """
        Set callback for turn resolution (both moves selected).

        callback(turn_number, our_move, opponent_move, we_go_first)
            turn_number: int
            our_move: tuple (move_id, move_data)
            opponent_move: tuple (move_id, move_data)
            we_go_first: bool

        Use this to calculate damage, apply effects, etc.
        """
        self.turn_resolve_callback = callback

    def on_consensus(self, callback):
        """
        Set callback for consensus verification.

        callback(turn_number, agreed: bool, their_hash: bytes)
            turn_number: int
            agreed: bool - True if hashes match
            their_hash: bytes - Opponent's 16-byte hash

        If agreed is False, battle should be voided.
        """
        self.consensus_callback = callback

    def on_battle_ready(self, callback):
        """
        Set callback for peer UI/asset readiness.

        callback() -> None
        """
        self.battle_ready_callback = callback

    def send_consensus_hash(self, outcome_hash, turn_number=None):
        """
        Send outcome hash for consensus verification.

        Call after computing turn outcome. Both devices must send
        their hashes and verify they match before committing.

        Args:
            outcome_hash (bytes): 16-byte outcome hash.
            turn_number (int): Turn number this hash is for. If None, uses session.turn_number - 1
                              (compensating for the increment in _resolve_turn).

        Returns:
            bool: True if sent successfully.
        """
        if not self.session or self.session.state != SESSION_BATTLING:
            self.logger.error("Cannot send consensus: not in battle")
            return False

        # Use explicit turn number, or current-1 (since _resolve_turn already incremented)
        if turn_number is None:
            turn_number = max(0, self.session.turn_number - 1)

        payload = struct.pack("<BH", MSG_TURN_CONSENSUS, turn_number)
        payload += outcome_hash[:16]

        # Store our hash for verification
        self.session.our_consensus_hash = outcome_hash[:16]
        self.session.consensus_turn = turn_number
        try:
            self.session.last_consensus_send_ts = time.ticks_ms()
        except Exception:
            self.session.last_consensus_send_ts = 0
        self.session.consensus_send_attempts = 1

        # Check if opponent's hash already arrived (they computed faster)
        their_hash = self.session.their_consensus_hash
        if their_hash is not None:
            # Compare hashes now that we have both
            agreed = outcome_hash[:16] == their_hash

            if self.consensus_callback:
                try:
                    self.consensus_callback(turn_number, agreed, their_hash)
                except Exception as e:
                    self.logger.error(f"Consensus callback error: {e}")

            if not agreed:
                self.logger.warning(f"Consensus FAILED for turn {turn_number}!")
                self._send_consensus_fail(turn_number)
            else:
                self._send_consensus_ack(turn_number)
            self._mark_consensus_resolved()

        return self._send_message(payload)

    def _mark_consensus_resolved(self):
        """Clear consensus resend tracking once a turn is verified."""
        if not self.session:
            return
        self.session.consensus_turn = None
        self.session.last_consensus_send_ts = 0
        self.session.consensus_send_attempts = 0

    def _handle_consensus(self, data):
        """
        Handle consensus hash from opponent.

        Args:
            data (bytes): Consensus message with turn number and hash.
        """
        if not self.session or self.session.state not in (SESSION_BATTLING, SESSION_COMPLETE):
            return

        self.session.update_activity()

        if len(data) < 19:  # 1 + 2 + 16
            self.logger.warning("Invalid consensus message")
            return

        turn_num = struct.unpack_from("<H", data, 1)[0]
        their_hash = data[3:19]

        self.logger.debug(f"Received consensus hash for turn {turn_num}")

        # Store opponent's hash
        self.session.their_consensus_hash = their_hash

        # Check if we have our hash already
        our_hash = self.session.our_consensus_hash
        if our_hash is not None:
            # Compare hashes
            agreed = our_hash == their_hash

            if self.consensus_callback:
                try:
                    self.consensus_callback(turn_num, agreed, their_hash)
                except Exception as e:
                    self.logger.error(f"Consensus callback error: {e}")

            if not agreed:
                self.logger.warning(f"Consensus FAILED for turn {turn_num}!")
                self._send_consensus_fail(turn_num)
            else:
                self._send_consensus_ack(turn_num)
            self._mark_consensus_resolved()

    def _send_consensus_ack(self, turn_number):
        """Send consensus acknowledgment."""
        payload = struct.pack("<BH", MSG_CONSENSUS_ACK, turn_number)
        self._send_message(payload)

    def _send_consensus_fail(self, turn_number):
        """Send consensus failure notification."""
        payload = struct.pack("<BH", MSG_CONSENSUS_FAIL, turn_number)
        self._send_message(payload)
        # Consensus failed - void the battle
        self._handle_error("Consensus failed - battle voided", code=99)
        self._mark_consensus_resolved()

    def get_turn_state(self):
        """
        Get current turn state for turn-based battles.

        Returns:
            tuple: (turn_number, turn_state) or (0, TURN_SELECTING) if no session.
        """
        if not self.session:
            return (0, TURN_SELECTING)
        return (self.session.turn_number, self.session.turn_state)

    def is_our_turn(self):
        """
        Check if we can select a move this turn.

        We can select when:
        - We're in a battle session
        - We haven't selected our move yet (our_move is None)

        Note: Opponent may have already sent their move (TURN_WAITING state),
        but we can still select ours. Turn only advances to TURN_RESOLVING
        after BOTH moves are submitted.

        Returns:
            bool: True if we can still select a move.
        """
        if not self.session or self.session.state != SESSION_BATTLING:
            return False
        # Can select if in SELECTING or WAITING state, as long as we haven't chosen yet
        return (
            self.session.turn_state in (TURN_SELECTING, TURN_WAITING)
            and self.session.our_move is None
        )

    # Internal protocol methods

    def _discover_services(self):
        """
        Discover GATT services and characteristics after connection.

        This is called automatically after connecting to an opponent.
        Discovers the game service and characteristic for data exchange.
        Once discovery completes, sends the challenge request.
        """
        self.logger.debug("[COMMS] _discover_services: entered")

        if not self.bt.is_connected():
            self.logger.error("Not connected - cannot discover services")
            return
        self.logger.debug("[COMMS] _discover_services: confirmed connected")

        conn_info = self.bt.get_connection_info()
        if not conn_info:
            self.logger.error("No connection info available")
            return
        self.logger.debug("[COMMS] _discover_services: got conn_info")

        conn_handle = conn_info["conn_handle"]
        self.logger.debug("[COMMS] _discover_services: conn_handle={}".format(conn_handle))

        try:
            # Discover all services (no uuid filter - MicroPython doesn't support kwargs)
            # The IRQ handler will filter for our service UUID
            self.logger.debug("[COMMS] _discover_services: calling gattc_discover_services...")
            self.bt.ble.gattc_discover_services(conn_handle)
            self.logger.debug("[COMMS] _discover_services: gattc_discover_services returned")

            # Note: Service and characteristic results will come via IRQ handler
            # When char_handle is set, we can proceed with challenge

            # Give discovery time to complete, then send challenge
            # In a real implementation, this should be event-driven via IRQ
            for _ in range(10):  # up to 1s total
                time.sleep_ms(100)
                if self.bt.char_handle is not None:
                    break
            self.logger.info(
                "[COMMS] _discover_services: waited, char_handle={}".format(
                    self.bt.char_handle
                )
            )

            if self.bt.char_handle is None:
                # Fallback: discover characteristics for the service
                # gattc_discover_characteristics(conn_handle, start_handle, end_handle)
                self.logger.info(
                    "[COMMS] _discover_services: calling gattc_discover_characteristics..."
                )
                self.bt.ble.gattc_discover_characteristics(conn_handle, 1, 65535)
                self.logger.info(
                    "[COMMS] _discover_services: gattc_discover_characteristics returned"
                )
                for _ in range(10):  # up to 1s total
                    time.sleep_ms(100)
                    if self.bt.char_handle is not None:
                        break
                self.logger.info(
                    "[COMMS] _discover_services: waited (chars), char_handle={}".format(
                        self.bt.char_handle
                    )
                )

            if self.bt.char_handle is not None:
                self.logger.debug("[COMMS] _discover_services: discovery complete!")
                self.logger.info("Service discovery complete, sending challenge...")
                self._send_challenge_request()
            else:
                self.logger.debug("[COMMS] _discover_services: no char_handle found")
                self.logger.error("Failed to discover game characteristic")
                self._handle_error("Service discovery failed")
                self.end_session()

        except Exception as e:
            self.logger.debug("[COMMS] _discover_services: EXCEPTION: {}".format(e))
            self.logger.error("Service discovery error: {}".format(e))
            self._handle_error("Service discovery failed")
            self.end_session()

    def _validate_message(self, data):
        """
        Validate message authentication using session token HMAC.

        Args:
            data: Message bytes including signature (last 16 bytes)

        Returns:
            bool: True if signature valid, False otherwise
        """
        if not self.session or not self.session.session_token:
            return False

        if len(data) < 17:  # Minimum: 1 byte type + 16 byte signature
            return False

        message = data[:-16]
        received_signature = data[-16:]

        # Compute expected signature
        expected = uhashlib.sha1(message + self.session.session_token).digest()[:16]

        return received_signature == expected

    def _send_message(self, payload):
        """
        Send a protocol message over BLE with authentication.

        For battle messages, appends HMAC signature for authentication.
        Automatically uses server notifications or client writes based on mode.

        Args:
            payload: Message bytes (must start with message type)

        Returns:
            True if sent successfully
        """
        self.logger.info(
            "[COMMS] _send_message: {} bytes, server_mode={}, server_conn={}".format(
                len(payload), self.server_mode, self.server_conn_handle
            )
        )

        if len(payload) > MAX_MESSAGE_SIZE - 16:  # Reserve space for signature
            self.logger.error(f"Message too large: {len(payload)} bytes")
            return False

        self.logger.debug("[COMMS] _send_message: size check passed")

        # Add HMAC signature for battle messages (when session exists)
        self.logger.info(
            "[COMMS] _send_message: session={}, has_token={}".format(
                self.session is not None,
                self.session.session_token is not None if self.session else False,
            )
        )

        if self.session and self.session.session_token:
            msg_type = payload[0]
            # Sign battle-phase messages
            if msg_type in (
                MSG_BATTLE_STATUS,
                MSG_BATTLE_RESULT,
                MSG_TURN_READY,
                MSG_TURN_CONSENSUS,
                MSG_TURN_ACK,
                MSG_BATTLE_READY,
            ):
                self.logger.debug("[COMMS] _send_message: computing signature...")
                signature = uhashlib.sha1(
                    payload + self.session.session_token
                ).digest()[:16]
                payload = payload + signature
                self.logger.info(
                    "[COMMS] _send_message: signature added, payload now {} bytes".format(
                        len(payload)
                    )
                )

        # Use server notifications if in server mode with connection
        if self.server_mode and self.server_conn_handle is not None:
            self.logger.debug("[COMMS] _send_message: using server_notify")
            return self.bt.server_notify(payload, self.server_conn_handle)

        # Otherwise use client write
        self.logger.debug("[COMMS] _send_message: checking connection...")
        if not self.bt.is_connected():
            self.logger.warning("Not connected - cannot send message")
            return False

        self.logger.info(
            "[COMMS] _send_message: using write_data, char_handle={}".format(
                self.bt.char_handle
            )
        )
        result = self.bt.write_data(payload, wait_for_response=False)
        self.logger.debug("[COMMS] _send_message: write_data returned {}".format(result))
        return result

    def _send_challenge_request(self):
        """Send challenge request message."""
        # Message format: [MSG_CHALLENGE_REQUEST, protocol_version(2), device_name_len(1), device_name]
        name_bytes = self.device_name.encode("utf-8")[:32]  # Limit name to 32 bytes
        payload = struct.pack(
            "<BHB", MSG_CHALLENGE_REQUEST, PROTOCOL_VERSION, len(name_bytes)
        )
        payload += name_bytes
        self.logger.info(
            "[COMMS] _send_challenge_request: payload={} bytes, char_handle={}".format(
                len(payload), self.bt.char_handle
            )
        )
        result = self._send_message(payload)
        self.logger.info(
            "[COMMS] _send_challenge_request: _send_message returned {}".format(result)
        )

    def _send_challenge_accept(self):
        """Send challenge acceptance message."""
        name_bytes = self.device_name.encode("utf-8")[:32]
        payload = struct.pack(
            "<BHB", MSG_CHALLENGE_ACCEPT, PROTOCOL_VERSION, len(name_bytes)
        )
        payload += name_bytes
        self._send_message(payload)

        # Move to handshake phase
        self.session.state = SESSION_HANDSHAKING
        self._send_handshake()

    def _send_challenge_decline(self, opponent_addr):
        """Send challenge decline message."""
        payload = struct.pack("<B", MSG_CHALLENGE_DECLINE)
        self._send_message(payload)

    def _send_handshake(self):
        """
        Send handshake message to establish session.

        Packet format (27 bytes total):
            - MSG_HANDSHAKE: 1 byte
            - protocol_version: 2 bytes (uint16 LE)
            - session_id: 8 bytes
            - session_token: 16 bytes
        """
        if not self.session:
            return

        # Generate session token from session ID and timestamp
        token_seed = self.session.session_id + str(time.ticks_ms()).encode()
        self.session.session_token = uhashlib.sha1(token_seed).digest()[:16]

        self.logger.info(
            f"[COMMS] _send_handshake: generated token={self.session.session_token[:8].hex()}..."
        )

        payload = struct.pack("<BH", MSG_HANDSHAKE, PROTOCOL_VERSION)
        payload += self.session.session_id
        payload += self.session.session_token

        self.logger.debug(
            "[COMMS] _send_handshake: payload={} bytes (1+2+8+16=27 expected)".format(
                len(payload)
            )
        )

        self._send_message(payload)

    def _send_handshake_ack(self):
        """
        Send handshake acknowledgment.

        Packet format (9 bytes total):
            - MSG_HANDSHAKE_ACK: 1 byte
            - session_id: 8 bytes
        """
        payload = struct.pack("<B", MSG_HANDSHAKE_ACK)
        payload += self.session.session_id
        self._send_message(payload)

        # Handshake complete - transition to data exchange state
        self.session.state = SESSION_EXCHANGING_DATA
        self.logger.info("Handshake complete - exchanging player data...")

        # Send our player data
        self._send_player_data()

    def _send_player_data(self):
        """
        Send our player data to opponent.

        Packet format:
            - MSG_PLAYER_DATA: 1 byte
            - num_fields: 1 byte
            - For each field: [field_id: 1 byte][length: 1 byte][data: N bytes]
        """
        if not self.session:
            return

        # If session doesn't have player data yet, get it from provider
        if not self.session.our_player_data:
            if self.player_data_provider:
                # Call provider to get current player data from authoritative source
                data = self.player_data_provider()
                if data:
                    char_id = data.get("character_id")
                    # Convert string ID to numeric if needed
                    if isinstance(char_id, str):
                        char_id = CHARACTER_TO_ID.get(char_id)
                    if char_id is None or char_id not in ID_TO_CHARACTER:
                        self.logger.error(
                            f"Invalid player data from provider - unknown character_id: {data.get('character_id')}"
                        )
                        self._handle_error("Invalid player data", code=2)
                        self.end_session()
                        return

                    self.session.our_player_data = {
                        PLAYER_DATA_CHARACTER_ID: char_id,
                        PLAYER_DATA_LEVEL: min(255, max(1, data.get("level", 1))),
                    }
                    if data.get("name"):
                        self.session.our_player_data[PLAYER_DATA_NAME] = data["name"]
                    if data.get("wins", 0) > 0:
                        self.session.our_player_data[PLAYER_DATA_WINS] = data["wins"]
                    if data.get("losses", 0) > 0:
                        self.session.our_player_data[PLAYER_DATA_LOSSES] = data[
                            "losses"
                        ]

                    if data.get("care_activity"):
                        self.session.our_player_data[
                            PLAYER_DATA_CARE_ACTIVITY
                        ] = data["care_activity"]
                    if data.get("care_food"):
                        self.session.our_player_data[
                            PLAYER_DATA_CARE_FOOD
                        ] = data["care_food"]
                    if data.get("powers"):
                        powers_val = data["powers"]
                        if isinstance(powers_val, (list, tuple)):
                            powers_val = ",".join([p for p in powers_val if p])
                        elif not isinstance(powers_val, str):
                            powers_val = str(powers_val)
                        if powers_val:
                            self.session.our_player_data[PLAYER_DATA_POWERS] = powers_val

                    # Station flag - stations set is_station=1 in their player_data_provider
                    if data.get("is_station"):
                        self.session.our_player_data[PLAYER_DATA_IS_STATION] = 1
                        self.logger.debug(
                            f"Got player data from provider: {self.session.our_player_data}"
                        )

            if not self.session.our_player_data:
                self.logger.error("No player data available - cannot start battle")
                self._handle_error("Missing player data", code=2)
                self.end_session()
                return

        payload = bytearray([MSG_PLAYER_DATA, 0])
        max_payload = MAX_MESSAGE_SIZE - 16

        # Encode each field: field_id, length, data
        fields = self.session.our_player_data
        char_id = fields.get(PLAYER_DATA_CHARACTER_ID)
        char_str = ID_TO_CHARACTER.get(char_id, "UNKNOWN")
        self.logger.info(
            f"Sending player data: character_id={char_id} ({char_str}), fields={fields}"
        )
        field_count = 0

        for field_id, value in fields.items():
            encoded_value = None
            if isinstance(value, int):
                # Keep integer fields in protocol-safe bounds.
                if value < 0:
                    value = 0
                if value <= 255:
                    encoded_value = bytes([value & 0xFF])
                else:
                    if value > 0xFFFF:
                        value = 0xFFFF
                    encoded_value = struct.pack("<H", value)
            elif isinstance(value, bytes):
                encoded_value = bytes(value[:255])
            elif isinstance(value, str):
                encoded_value = value.encode("utf-8")[:32]  # Max 32 chars
            else:
                # Skip unknown types
                continue

            entry_len = 2 + len(encoded_value)
            if len(payload) + entry_len > max_payload:
                self.logger.warning(
                    f"Skipping player data field {field_id}: packet size limit reached"
                )
                continue

            payload.append(field_id)
            payload.append(len(encoded_value))
            payload.extend(encoded_value)
            field_count += 1
            if field_count >= 255:
                break

        payload[1] = field_count

        self._send_message(bytes(payload))
        self.session.our_data_sent = True
        self.logger.debug(f"Sent player data: {self.session.our_player_data}")

        # Check if both data exchanged
        self._check_data_exchange_complete()

    def _check_data_exchange_complete(self):
        """Check if both players have exchanged data, transition to battle if so."""
        if not self.session:
            return

        if self.session.our_data_sent and self.session.opponent_data_received:
            self.session.state = SESSION_BATTLING
            self.set_availability(AVAILABILITY_IN_BATTLE)
            
            self.logger.info("Player data exchange complete - battle ready!")
            # Grace window while both sides load assets/UI
            self.session.disconnect_grace_until = time.ticks_add(
                time.ticks_ms(), READY_GRACE_TIMEOUT_MS
            )

            if self.battle_start_callback:
                try:
                    self.battle_start_callback(self.session)
                except Exception as e:
                    self.logger.error(f"Battle start callback error: {e}")

    def _send_keepalive(self):
        """Send keepalive message to maintain connection."""
        payload = struct.pack("<B", MSG_KEEPALIVE)
        self._send_message(payload)

    def send_battle_ready(self, force=False):
        """Notify peer that our UI/assets are ready. Idempotent unless force=True."""
        if not self.session or self.session.state != SESSION_BATTLING:
            self.logger.debug("send_battle_ready: not in battling state")
            return False
        if self.session.ready_sent and not force:
            self.logger.debug("send_battle_ready: already sent")
            return True
        payload = struct.pack("<B", MSG_BATTLE_READY)
        sent = self._send_message(payload)
        if sent:
            # Keep flag set so we don't spam, but allow forced retries
            self.session.ready_sent = True
            self.session.update_activity()
            if force:
                self.logger.info("Resent BATTLE_READY (retry)")
            else:
                self.logger.info("Sent BATTLE_READY")
        return sent

    def _send_error(self, error_code, message=""):
        """Send error message to opponent."""
        msg_bytes = message.encode("utf-8")[:128]
        payload = struct.pack("<BBB", MSG_ERROR, error_code, len(msg_bytes))
        payload += msg_bytes
        self._send_message(payload)

    def _handle_data(self, data):
        """
        Handle received BLE data.

        Parses message type, validates authentication, and dispatches
        to appropriate handler.

        Args:
            data: Received bytes from BLE characteristic
        """
        if not data or len(data) < 1:
            return

        msg_type = data[0]
        msg_type_str = {
            0x01: "CHALLENGE_REQUEST",
            0x02: "CHALLENGE_ACCEPT",
            0x03: "CHALLENGE_DECLINE",
            0x10: "HANDSHAKE",
            0x11: "HANDSHAKE_ACK",
            0x12: "PLAYER_DATA",
            0x13: "PLAYER_DATA_ACK",
            0x20: "BATTLE_MOVE",
            0x21: "BATTLE_STATUS",
            0x22: "BATTLE_RESULT",
            0x23: "BATTLE_FORFEIT",
            0x24: "TURN_READY",
            0x25: "TURN_RESOLVE",
            0x26: "TURN_CONSENSUS",
            0x27: "CONSENSUS_ACK",
            0x28: "CONSENSUS_FAIL",
            0x29: "TURN_ACK",
            0x2A: "BATTLE_READY",
            0xF0: "KEEPALIVE",
            0xFF: "ERROR",
        }.get(msg_type, f"UNKNOWN(0x{msg_type:02x})")
        
        self.logger.info(
            "[COMMS] _handle_data: {} bytes, msg_type=0x{:02x} ({})".format(
                len(data), msg_type, msg_type_str
            )
        )

        # Validate battle messages with HMAC
        if self.session and self.session.session_token:
            if msg_type in (
                MSG_BATTLE_STATUS,
                MSG_BATTLE_RESULT,
                MSG_TURN_READY,
                MSG_TURN_CONSENSUS,
                MSG_TURN_ACK,
                MSG_BATTLE_READY,
            ):
                if not self._validate_message(data):
                    self.logger.warning("Message authentication failed - ignoring")
                    return
                # Strip signature from payload
                data = data[:-16]

        try:
            if msg_type == MSG_CHALLENGE_REQUEST:
                self._handle_challenge_request(data)
            elif msg_type == MSG_CHALLENGE_ACCEPT:
                self._handle_challenge_accept(data)
            elif msg_type == MSG_CHALLENGE_DECLINE:
                self._handle_challenge_decline(data)
            elif msg_type == MSG_HANDSHAKE:
                self._handle_handshake(data)
            elif msg_type == MSG_HANDSHAKE_ACK:
                self._handle_handshake_ack(data)
            elif msg_type == MSG_PLAYER_DATA:
                self._handle_player_data(data)
            elif msg_type == MSG_BATTLE_STATUS:
                self._handle_battle_status(data)
            elif msg_type == MSG_BATTLE_RESULT:
                self._handle_battle_result(data)
            elif msg_type == MSG_BATTLE_FORFEIT:
                self._handle_battle_forfeit(data)
            elif msg_type == MSG_TURN_READY:
                self._handle_turn_ready(data)
            elif msg_type == MSG_TURN_ACK:
                self._handle_turn_ack(data)
            elif msg_type == MSG_TURN_RESOLVE:
                self._handle_turn_resolve(data)
            elif msg_type == MSG_TURN_CONSENSUS:
                self._handle_consensus(data)
            elif msg_type == MSG_CONSENSUS_ACK:
                self._handle_consensus_ack(data)
            elif msg_type == MSG_CONSENSUS_FAIL:
                self._handle_consensus_fail(data)
            elif msg_type == MSG_BATTLE_READY:
                self._handle_battle_ready(data)
            elif msg_type == MSG_KEEPALIVE:
                # Just update activity timestamp
                if self.session:
                    self.session.update_activity()
            elif msg_type == MSG_ERROR:
                self._handle_error_message(data)
            else:
                self.logger.warning(f"Unknown message type: 0x{msg_type:02x}")

        except Exception as e:
            self.logger.error(f"Error handling message type 0x{msg_type:02x}: {e}")

    def _handle_challenge_request(self, data):
        """Handle incoming challenge request."""
        if len(data) < 4:
            return

        protocol_ver, name_len = struct.unpack_from("<HB", data, 1)

        if protocol_ver != PROTOCOL_VERSION:
            self.logger.warning(
                f"Protocol version mismatch: {protocol_ver} != {PROTOCOL_VERSION}"
            )
            self._send_error(1, "Protocol version mismatch")
            return

        opponent_name = "Unknown"
        if len(data) >= 4 + name_len:
            try:
                opponent_name = data[4 : 4 + name_len].decode("utf-8")
            except Exception as exc:
                self.logger.debug(f"Challenge request name decode failed: {exc}")

        # Get opponent address from connection
        conn_info = self.bt.get_connection_info()
        if not conn_info:
            return

        opponent_addr = conn_info["addr"]
        now = time.ticks_ms()

        # If we're already in a session, decline additional challenges.
        if self.session and self.session.state in (
            SESSION_CHALLENGING,
            SESSION_CHALLENGED,
            SESSION_HANDSHAKING,
            SESSION_EXCHANGING_DATA,
            SESSION_BATTLING,
        ):
            self.logger.warning(
                "Rejecting challenge while busy (state={})".format(self.session.state)
            )
            self._send_challenge_decline(opponent_addr)
            return

        # Debounce duplicate challenges from the same opponent.
        if opponent_addr in self.pending_challenges:
            info = self.pending_challenges.get(opponent_addr)
            ts = info[0] if isinstance(info, tuple) else info
            if time.ticks_diff(now, ts) < 1500:
                self.logger.debug("Ignoring duplicate challenge from same opponent")
                return

        self.pending_challenges[opponent_addr] = (now, opponent_name)

        self.logger.info(f"Challenge received from '{opponent_name}'")

        if self.challenge_callback:
            try:
                self.challenge_callback(opponent_addr, opponent_name)
            except Exception as e:
                self.logger.error(f"Challenge callback error: {e}")

    def _handle_challenge_accept(self, data):
        """Handle challenge acceptance from opponent."""
        if not self.session or self.session.state != SESSION_CHALLENGING:
            return

        protocol_ver, name_len = struct.unpack_from("<HB", data, 1)

        if protocol_ver != PROTOCOL_VERSION:
            self.logger.warning(
                f"Protocol version mismatch: {protocol_ver} != {PROTOCOL_VERSION}"
            )
            self._send_error(1, "Protocol version mismatch")
            self.end_session()
            return

        opponent_name = "Unknown"
        if len(data) >= 4 + name_len:
            try:
                opponent_name = data[4 : 4 + name_len].decode("utf-8")
            except Exception as exc:
                self.logger.debug(f"Challenge accept name decode failed: {exc}")

        self.session.opponent_name = opponent_name
        self.session.state = SESSION_HANDSHAKING

        self.logger.info(f"Challenge accepted by '{opponent_name}'")

    def _handle_challenge_decline(self, data):
        """Handle challenge decline from opponent."""
        self.logger.info("Challenge declined by opponent")
        self._handle_error("Challenge declined")
        self.end_session()
        self._notify_ui_cancel("challenge_declined")

    def _handle_handshake(self, data):
        """
        Handle handshake message from opponent.

        Parses session token and opponent's character info (ID + level).

        Expected packet format (29 bytes minimum, 31 with char info):
            - MSG_HANDSHAKE: 1 byte
            - protocol_version: 2 bytes
            - session_id: 8 bytes
            - session_token: 16 bytes
        """
        if not self.session or self.session.state != SESSION_HANDSHAKING:
            return

        if len(data) < 27:  # 1 + 2 + 8 + 16
            self.logger.warning("Invalid handshake message")
            return

        protocol_ver = struct.unpack_from("<H", data, 1)[0]
        session_id = data[3:11]
        session_token = data[11:27]

        self.logger.debug(f"[COMMS] _handle_handshake: received token={session_token[:8].hex()}...")

        if protocol_ver != PROTOCOL_VERSION:
            self.logger.warning(f"Protocol version mismatch in handshake")
            self._send_error(1, "Protocol version mismatch")
            self.end_session()
            return

        # Store opponent's session info
        self.session.session_token = session_token

        # Send acknowledgment (this transitions to data exchange and sends player data)
        self._send_handshake_ack()

    def _handle_handshake_ack(self, data):
        """
        Handle handshake acknowledgment from opponent.

        Expected packet format:
            - MSG_HANDSHAKE_ACK: 1 byte
            - session_id: 8 bytes
        """
        if not self.session or self.session.state != SESSION_HANDSHAKING:
            return

        # Transition to data exchange and send our player data
        self.session.state = SESSION_EXCHANGING_DATA
        self.logger.info("Handshake ack received - exchanging player data...")

        # Send our player data
        self._send_player_data()

    def _handle_player_data(self, data):
        """
        Handle incoming player data from opponent.

        Parses TLV-style fields and stores in session.

        Packet format:
            - MSG_PLAYER_DATA: 1 byte
            - num_fields: 1 byte
            - For each field: [field_id: 1 byte][length: 1 byte][data: N bytes]
        """
        if not self.session or self.session.state != SESSION_EXCHANGING_DATA:
            self.logger.warning("Received player data in wrong state")
            return

        if len(data) < 2:
            return

        num_fields = data[1]
        offset = 2
        seen_fields = set()
        invalid_care = False

        for _ in range(num_fields):
            if offset + 2 > len(data):
                break

            field_id = data[offset]
            field_len = data[offset + 1]
            offset += 2

            if offset + field_len > len(data):
                break

            field_data = data[offset : offset + field_len]
            offset += field_len

            if field_id in seen_fields:
                if field_id in (PLAYER_DATA_CARE_ACTIVITY, PLAYER_DATA_CARE_FOOD):
                    invalid_care = True
                    self.logger.warning(
                        f"[PlayerData] Duplicate care field: {field_id}"
                    )
                # Ignore duplicate fields
                continue
            seen_fields.add(field_id)

            # Decode based on field type
            if field_id in (
                PLAYER_DATA_CHARACTER_ID,
                PLAYER_DATA_LEVEL,
                PLAYER_DATA_IS_STATION,
            ):
                # Numeric scalar (1-byte preferred, 2-byte legacy-compatible).
                if field_len >= 2:
                    value = struct.unpack("<H", field_data[:2])[0]
                elif field_len == 1:
                    value = field_data[0]
                else:
                    self.logger.warning(
                        f"[PlayerData] Ignoring empty numeric field: {field_id}"
                    )
                    continue
            elif field_id in (PLAYER_DATA_WINS, PLAYER_DATA_LOSSES):
                # 2-byte counter (accept 1-byte legacy payload).
                if field_len >= 2:
                    value = struct.unpack("<H", field_data[:2])[0]
                elif field_len == 1:
                    value = field_data[0]
                else:
                    self.logger.warning(
                        f"[PlayerData] Ignoring empty counter field: {field_id}"
                    )
                    continue
            elif field_id == PLAYER_DATA_NAME:
                # String
                try:
                    value = field_data.decode("utf-8")
                except Exception:
                    value = field_data.decode("utf-8", "ignore")
                value = value[:32]
            elif field_id == PLAYER_DATA_BADGE_ID:
                # Raw bytes
                value = bytes(field_data)
            elif field_id in (
                PLAYER_DATA_CARE_ACTIVITY,
                PLAYER_DATA_CARE_FOOD,
                PLAYER_DATA_POWERS,
            ):
                # Care effect ID string or power CSV
                if not field_data:
                    value = ""
                else:
                    try:
                        value = field_data.decode("utf-8")
                    except Exception:
                        value = field_data.decode("utf-8", "ignore")
                value = value[:64]
            else:
                # Unknown field, store as bytes
                value = bytes(field_data)

            self.session.opponent_player_data[field_id] = value

        if invalid_care:
            self._send_error(2, "Invalid care modifiers")
            self._handle_error("Invalid care modifiers", code=2)
            self.end_session()
            return

        # Require a valid character ID
        char_id = self.session.opponent_player_data.get(PLAYER_DATA_CHARACTER_ID, None)
        if char_id is None:
            self._send_error(2, "Missing character ID")
            self._handle_error("Missing opponent character ID", code=2)
            self.end_session()
            return
        if char_id not in ID_TO_CHARACTER:
            self._send_error(2, "Unknown character ID")
            self._handle_error(f"Unknown opponent character ID: {char_id}", code=2)
            self.end_session()
            return

        self.session.opponent_data_received = True
        # --- DEBUG: Log player data received ---
        char_str = ID_TO_CHARACTER.get(char_id, f"unknown({char_id})")
        self.logger.info(
            f"[PlayerData] Received opponent player data: character_id={char_id} ({char_str}), fields={self.session.opponent_player_data}"
        )
        # Check if both data exchanged
        self._check_data_exchange_complete()

    def _handle_battle_status(self, data):
        """Handle battle status update from opponent."""
        if not self.session or self.session.state not in (SESSION_BATTLING, SESSION_COMPLETE):
            return

        self.session.update_activity()

        if len(data) < 4:
            return

        hp, status_flags = struct.unpack_from("<HB", data, 1)
        status_data = data[4:] if len(data) > 4 else None

        # Store in session for game logic to access
        self.session.battle_data["opponent_hp"] = hp
        self.session.battle_data["opponent_status"] = status_flags

    def _handle_battle_result(self, data):
        """Handle battle result from opponent."""
        if not self.session or self.session.state not in (SESSION_BATTLING, SESSION_COMPLETE):
            return

        if len(data) < 2:
            return

        winner = data[1]
        result_data = data[2:] if len(data) > 2 else None

        self.session.state = SESSION_COMPLETE

        self.logger.info(f"Battle result received: winner={winner}")

        if self.result_callback:
            try:
                self.result_callback(winner, result_data)
            except Exception as e:
                self.logger.error(f"Result callback error: {e}")

    def _handle_battle_forfeit(self, data):
        """Handle forfeit from opponent."""
        if not self.session or self.session.state != SESSION_BATTLING:
            return

        self.session.state = SESSION_COMPLETE

        self.logger.info("Opponent forfeited the battle")

        # Treat as win for us
        if self.result_callback:
            try:
                self.result_callback(1, b"forfeit")  # 1 = we win
            except Exception as e:
                self.logger.error(f"Result callback error: {e}")

    def _handle_error_message(self, data):
        """Handle error message from opponent."""
        if len(data) < 3:
            return

        error_code, msg_len = struct.unpack_from("<BB", data, 1)
        error_msg = ""

        if len(data) >= 3 + msg_len:
            try:
                error_msg = data[3 : 3 + msg_len].decode("utf-8")
            except Exception as exc:
                self.logger.debug(f"Protocol error message decode failed: {exc}")

        self.logger.warning(
            f"Protocol error from opponent: code={error_code}, msg='{error_msg}'"
        )
        self._handle_error(error_msg, error_code)

    def _handle_turn_ready(self, data):
        """
        Handle opponent signaling they've selected their move.

        In turn-based battles, both players select moves, then once both
        are ready, moves are resolved based on speed priority.

        Args:
            data (bytes): Turn ready message with opponent's move selection.
        """
        if not self.session or self.session.state != SESSION_BATTLING:
            return

        self.session.update_activity()

        if len(data) < 4:
            return

        # Extract opponent's move selection
        turn_num, move_id = struct.unpack_from("<HH", data, 1)
        move_data = data[5:] if len(data) > 5 else None

        self.logger.debug(f"Opponent ready: turn={turn_num}, move={move_id}")

        # Store opponent's move
        self.session.opponent_move = (move_id, move_data)

        # Always ACK the move immediately
        self._send_turn_ack(turn_num)

        # If we already have our move, resolve or send as needed
        if self.session.our_move is not None:
            if not self.session.turn_move_sent:
                # We hadn't sent yet (defender pending), send now
                self._send_turn_ready_message()
            # If both moves present, resolve now
            self._maybe_resolve_turn(
                f"Both moves present after receiving opponent move for turn {turn_num}."
            )
        else:
            self.logger.info("Received opponent move; waiting for our selection.")

    def _send_turn_ack(self, turn_number):
        """Send acknowledgment for received turn move."""
        payload = struct.pack("<BH", MSG_TURN_ACK, turn_number)
        self._send_message(payload)

    def _handle_turn_ack(self, data):
        """
        Handle turn acknowledgment from opponent.
        """
        if not self.session or self.session.state != SESSION_BATTLING:
            return

        if len(data) < 3:
            return

        turn_num = struct.unpack_from("<H", data, 1)[0]
        self.logger.debug(f"Received TURN_ACK for turn {turn_num}")

        self.session.turn_move_acked = True
        self.session.last_turn_ready_ts = 0

        if not self.session.is_challenger:
            # Defender: We received ACK for our move.
            # We have both moves (since we only sent ours after receiving theirs).
            # We can now resolve the turn.
            if (
                self.session.our_move is not None
                and self.session.opponent_move is not None
            ):
                self.logger.info(
                    f"Defender: Move ACKed, both moves ready for turn {turn_num}, resolving."
                )
                self.session.turn_state = TURN_RESOLVING
                self._resolve_turn()

    def _handle_turn_resolve(self, data):
        """
        Handle turn resolution message from opponent.

        This is sent by the "arbiter" (challenger) after both moves are in.
        Contains the calculated turn outcome.

        Args:
            data (bytes): Turn resolution with damage/effects.
        """
        if not self.session or self.session.state != SESSION_BATTLING:
            return

        self.session.update_activity()

        # In current design, resolution is calculated locally
        # This message is for verification/sync purposes
        self.logger.debug("Turn resolve received")

    def send_turn_ready(self, move_id, move_data=None):
        """
        Signal that we've selected our move for this turn.

        Call this after player selects a move. Once both players have
        sent turn_ready, moves are resolved based on speed.

        Args:
            move_id (int): Selected move identifier.
            move_data (bytes, optional): Additional move parameters.

        Returns:
            bool: True if move recorded (and sent if appropriate).
        """
        if not self.session or self.session.state != SESSION_BATTLING:
            self.logger.error("Cannot send turn ready: not in battle")
            return False

        # Prevent duplicate sends
        if self.session.turn_move_sent:
            self.logger.debug("Move already sent for this turn, ignoring duplicate")
            return True

        # Store our move
        self.session.our_move = (move_id, move_data)
        self.logger.info(f"Selected move {move_id} (turn {self.session.turn_number})")

        # Challenger sends immediately; Defender waits until challenger move arrives
        if self.session.is_challenger:
            return self._send_turn_ready_message(force=False)

        # Defender path
        if self.session.opponent_move is not None:
            # Already have challenger move, send now
            return self._send_turn_ready_message(force=False)

        # Wait for challenger move before sending
        self.logger.info("Defender: Move selected, waiting for challenger move before sending.")
        self.session.turn_state = TURN_WAITING
        return True

    def _send_turn_ready_message(self, force=False):
        """Internal helper to send the actual TURN_READY message."""
        if not self.session or not self.session.our_move:
            return False

        # Guard against duplicate sends
        if self.session.turn_move_sent and not force:
            self.logger.debug("_send_turn_ready_message: already sent, skipping")
            return True

        move_id, move_data = self.session.our_move

        # Build message
        payload = struct.pack("<BHH", MSG_TURN_READY, self.session.turn_number, move_id)
        if move_data:
            payload += move_data

        success = self._send_message(payload)
        if success:
            self.session.turn_move_sent = True
            self.session.turn_state = TURN_WAITING
            self.logger.info(f"Sent TURN_READY for turn {self.session.turn_number}")
            try:
                self.session.last_turn_ready_ts = time.ticks_ms()
            except Exception:
                self.session.last_turn_ready_ts = 0
            # If we already have the opponent's move, resolve now regardless of role
            if self.session.opponent_move is not None and self.session.our_move is not None:
                self._maybe_resolve_turn(
                    f"Both moves ready after sending for turn {self.session.turn_number}."
                )

        return success

    def _resolve_turn(self):
        """
        Resolve the current turn after both moves are selected.

        DEFERS ALL processing to main loop to avoid stack overflow.
        MicroPython has low recursion limit (~50) and BLE IRQ stack is deep.

        Only captures the move data here - turn order determination and
        turn_resolve_callback are both processed in update().
        """
        if not self.session:
            return

        our_move = self.session.our_move
        opponent_move = self.session.opponent_move

        if our_move is None or opponent_move is None:
            self.logger.warning("Cannot resolve turn: missing moves")
            return

        turn_num = self.session.turn_number
        is_challenger = self.session.is_challenger

        self.logger.info(
            f"Turn {turn_num} moves ready: us={our_move[0]}, them={opponent_move[0]} - deferring to main loop"
        )

        # DEFER ALL processing to main loop (turn order + resolve callback)
        # Store raw data - turn order will be determined in _process_pending_turn_resolve()
        self.pending_turn_resolve = (turn_num, our_move, opponent_move, is_challenger)

        # Reset for next turn (do this now while we have session context)
        self.session.turn_number += 1
        self.session.turn_state = TURN_SELECTING
        self.session.our_move = None
        self.session.opponent_move = None
        self.session.turn_move_sent = False
        self.session.turn_move_acked = False
        self.session.last_turn_ready_ts = 0
        # Clear consensus hashes for next turn
        self.session.our_consensus_hash = None
        self.session.their_consensus_hash = None
        self.session.consensus_turn = None
        self.session.last_consensus_send_ts = 0
        self.session.consensus_send_attempts = 0

    def _maybe_resolve_turn(self, reason=None):
        """
        Resolve the turn if both moves are present and nothing is already pending.
        """
        if (
            not self.session
            or self.session.state != SESSION_BATTLING
            or self.pending_turn_resolve is not None
        ):
            return
        if self.session.our_move is None or self.session.opponent_move is None:
            return
        if reason:
            self.logger.info(reason)
        self.session.turn_state = TURN_RESOLVING
        self._resolve_turn()

    def _handle_consensus_ack(self, data):
        """Handle consensus acknowledgment from opponent."""
        if not self.session or self.session.state != SESSION_BATTLING:
            return

        if len(data) < 3:
            return

        turn_num = struct.unpack_from("<H", data, 1)[0]
        self.logger.debug(f"Consensus ACK for turn {turn_num}")

        # Ignore stray ACKs once we've already resolved consensus tracking
        if self.session.consensus_turn is None:
            return

        # If ACK includes sender hash, capture it
        if len(data) >= 19:
            self.session.their_consensus_hash = data[3:19]

        # If we still don't have their hash, treat ACK as confirmation of match
        if self.session.their_consensus_hash is None and self.session.our_consensus_hash is not None:
            self.session.their_consensus_hash = self.session.our_consensus_hash

        # Only proceed if we have our hash and ACK matches current consensus turn
        if self.session.our_consensus_hash is None:
            return
        if self.session.consensus_turn is not None and turn_num != self.session.consensus_turn:
            self.logger.debug(
                f"Consensus ACK turn mismatch (got {turn_num}, expected {self.session.consensus_turn})"
            )
            return

        agreed = self.session.our_consensus_hash == self.session.their_consensus_hash
        if self.consensus_callback:
            try:
                self.consensus_callback(turn_num, agreed, self.session.their_consensus_hash)
            except Exception as e:
                self.logger.error(f"Consensus callback error: {e}")

        if not agreed:
            self._send_consensus_fail(turn_num)

        self._mark_consensus_resolved()

    def _handle_consensus_fail(self, data):
        """Handle consensus failure from opponent."""
        if not self.session:
            return

        if len(data) < 3:
            return

        turn_num = struct.unpack_from("<H", data, 1)[0]
        self.logger.warning(f"Consensus FAIL from opponent for turn {turn_num}")

        # Void the battle
        self._handle_error("Consensus failed - opponent reported mismatch", code=99)
        self._mark_consensus_resolved()

    def _handle_battle_ready(self, data):
        """Handle peer UI/asset ready notification."""
        if not self.session:
            return
        self.session.update_activity()
        self.session.ready_received = True
        self.logger.info("Received BATTLE_READY from peer")
        if self.battle_ready_callback:
            try:
                self.battle_ready_callback()
            except Exception as e:
                self.logger.error(f"Battle ready callback error: {e}")

    def _handle_disconnect(self, conn_handle, addr_type, addr):
        """Handle BLE disconnection."""
        # Clear session FIRST to prevent recursion when error_callback calls end_session
        session = self.session
        self.session = None

        if session:
            if session.state == SESSION_CHALLENGING:
                self.logger.warning("Disconnected while challenging opponent")
                self._handle_error("Challenge failed: disconnected")
                self._notify_ui_cancel("challenge_disconnect")
                # Ensure we're available again
                try:
                    self.set_availability(AVAILABILITY_IDLE)
                except Exception as exc:
                    self.logger.warning(f"Failed to reset availability after disconnect: {exc}")
            elif session.state in (SESSION_HANDSHAKING, SESSION_BATTLING):
                now = time.ticks_ms()
                if session.disconnect_grace_until and time.ticks_diff(
                    session.disconnect_grace_until, now
                ) > 0:
                    # A disconnect during asset/UI load is still fatal: BLE won't auto-reconnect.
                    # Use a more specific message so BattleManager can surface better UX.
                    self.logger.warning("Disconnected during grace window (asset load)")
                self.logger.warning("Disconnected during battle session")
                self._handle_error("Connection lost")
                self._notify_ui_cancel("disconnect")
                # Ensure we fully tear down BLE state so the next matchmaking/battle
                # doesn't inherit a half-dead connection.
                self.end_session()

    def _handle_error(self, message, code=0):
        """Handle protocol error and invoke callback."""
        self.logger.error(f"Protocol error: {message} (code={code})")

        if self.error_callback:
            try:
                self.error_callback(code, message)
            except Exception as e:
                self.logger.error(f"Error callback failed: {e}")
        # Let UI reset spinners/status if needed
        if self.cancel_callback:
            try:
                self.cancel_callback("protocol_error")
            except Exception as e:
                self.logger.error(f"Cancel callback failed: {e}")
        # Let UI reset spinners/status if needed
        self._notify_ui_cancel("protocol_error")

    def _notify_ui_cancel(self, reason=""):
        """
        Notify UI layers (BattleManager/BattleMatchmaking) to reset spinners/status.
        This is called on errors/timeouts to avoid stuck UI states.
        """
        if self.cancel_callback:
            try:
                self.cancel_callback(reason)
            except Exception as e:
                self.logger.error(f"Cancel callback failed: {e}")
