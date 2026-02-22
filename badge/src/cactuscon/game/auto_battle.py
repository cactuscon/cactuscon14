"""Auto-battle mode for station and stress-testing peer-to-peer BLE battles."""

import time
import struct
import urandom
from micropython import const

from cactuscon.game.comms import (
    GameBTComms, BattleSession, 
    AVAILABILITY_OPEN, AVAILABILITY_IDLE, AVAILABILITY_IN_BATTLE,
    MSG_BATTLE_STATUS, MSG_BATTLE_RESULT,
    SESSION_BATTLING, SESSION_COMPLETE, PROTOCOL_VERSION,
    MOVE_TIMEOUT_MS
)
from cactuscon.utils import Logger
from cactuscon.game.engine.battle_rules import BattleRules
from cactuscon.game.engine.moves import get_move, MOVE_CAT_DAMAGE, MOVE_CAT_HEAVY, MOVE_CAT_SUPPORT, MOVE_CAT_RECOVERY
from cactuscon.game.engine.stations import get_station, DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD
from cactuscon.game.engine.characters import CharacterStats
from cactuscon.prefs import prefs, make_key

# Auto-battle state machine
AUTO_BATTLE_IDLE = const(0)
AUTO_BATTLE_CHALLENGE_PENDING = const(1)
AUTO_BATTLE_ACTIVE = const(2)
AUTO_BATTLE_TIMEOUT = const(3)

# Default auto-battle parameters
DEFAULT_AUTO_BATTLE_DURATION_MS = const(10000)
DEFAULT_AUTO_BATTLE_HP = const(100)
DEFAULT_AUTO_BATTLE_MOVE_INTERVAL_MS = const(2000)

# NVS keys for persistent station battle statistics
KEY_STATION_WINS = make_key("st", "win")
KEY_STATION_LOSSES = make_key("st", "loss")
KEY_STATION_CHALLENGES = make_key("st", "ch")


def calculate_winner_by_hp_percent(our_hp, our_max_hp, opponent_hp, opponent_max_hp):
    """
    Calculate battle winner based on HP percentage remaining.
    
    Higher HP percentage wins. This prevents gaming by having a tanky character
    with high HP - a character with 70/100 HP (70%) beats one with 100/200 HP (50%).
    
    Args:
        our_hp: Our current HP
        our_max_hp: Our maximum HP
        opponent_hp: Opponent's current HP
        opponent_max_hp: Opponent's maximum HP
        
    Returns:
        int: 0=draw, 1=we win, 2=opponent wins
    """
    # Avoid division by zero
    our_max = our_max_hp if our_max_hp > 0 else 1
    opp_max = opponent_max_hp if opponent_max_hp > 0 else 1
    
    our_percent = (our_hp / our_max) * 100
    opp_percent = (opponent_hp / opp_max) * 100
    
    # Use small epsilon for floating point comparison
    if abs(our_percent - opp_percent) < 0.01:
        return 0  # Draw
    elif our_percent > opp_percent:
        return 1  # We win
    else:
        return 2  # Opponent wins


class AutoBattleComms(GameBTComms):
    """
    Automated battle testing mode for CactusCon badge.
    
    Inherits from GameBTComms to:
    - Automatically accept all incoming challenges
    - Automatically respond to all moves via BattleRules
    - Automatically timeout and reset after battle duration expires
    - Log detailed state transitions for analysis
    
    Usage:
        auto_battle = AutoBattleComms(
            bt_mgr,
            device_name="TestBadge",
            auto_battle_duration_ms=5000,
            logger_level=20
        )
        
        # In main loop
        auto_battle.update()
    """
    
    def __init__(self, bluetooth_manager, device_name="AutoBattle", 
                 auto_battle_duration_ms=DEFAULT_AUTO_BATTLE_DURATION_MS,
                 difficulty=DIFFICULTY_MEDIUM,
                 station_id=None,
                 logger_level=20):
        """
        Initialize auto-battle communications.
        
        Args:
            bluetooth_manager: BluetoothManager instance for BLE operations
            device_name: This badge's display name
            auto_battle_duration_ms: How long each simulated battle lasts (milliseconds)
            difficulty: AI difficulty (DIFFICULTY_EASY/MEDIUM/HARD). If station_id is 
                provided, this is overridden by station configuration.
            station_id: Station identifier for loading character/difficulty config.
            logger_level: Logging level (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR)
        """
        super().__init__(bluetooth_manager, device_name, logger_level)
        
        # Battle rules for damage calculation
        self.rules = BattleRules()
        
        # Station configuration
        self.station_id = station_id
        self.station = None
        self.character_moves = [0, 1, 2, 3]
        
        # Load station config if provided
        if station_id:
            self.station = get_station(station_id)
            if self.station:
                difficulty = self.station.difficulty
                self.character_moves = self.station.get_moves()
                self.logger.info(f"Station {station_id}: char={self.station.character_id}, moves={self.character_moves}")
        
        # Auto-battle configuration
        self.auto_battle_duration_ms = auto_battle_duration_ms
        self.auto_battle_mode_enabled = False
        self.difficulty = difficulty
        
        # AI state - load from station character if available
        if station_id and self.station:
            self.our_stats = self.station.get_battle_stats()
            self.our_hp = self.our_stats.hp
            self.our_max_hp = self.our_stats.max_hp
        else:
            self.our_stats = CharacterStats()
            self.our_hp = DEFAULT_AUTO_BATTLE_HP
            self.our_max_hp = DEFAULT_AUTO_BATTLE_HP
        
        # Opponent stats (initialized on battle start)
        self.opponent_stats = CharacterStats()
        self.opponent_hp = DEFAULT_AUTO_BATTLE_HP
        self.opponent_max_hp = DEFAULT_AUTO_BATTLE_HP  # Track opponent's max HP for percentage calc
        
        # Auto-battle state machine
        self.auto_battle_state = AUTO_BATTLE_IDLE
        self.battle_start_time = 0
        self.last_move_time = 0
        
        # Battle statistics for testing - load persisted stats from NVS
        # These survive across reboots for station mode
        try:
            station_wins = prefs.get_int32(KEY_STATION_WINS, 0)
            station_losses = prefs.get_int32(KEY_STATION_LOSSES, 0)
            station_challenges = prefs.get_int32(KEY_STATION_CHALLENGES, 0)
        except Exception as e:
            self.logger.debug(f"Failed to load persisted station stats: {e}")
            station_wins = 0
            station_losses = 0
            station_challenges = 0
        
        self.stats = {
            'total_challenges': station_challenges,
            'accepted_challenges': 0,
            'completed_battles': 0,
            'failed_battles': 0,
            'total_moves_sent': 0,
            'total_moves_received': 0,
            'wins': station_wins,  # Persisted wins
            'losses': station_losses,  # Persisted losses
        }
        
        # NOTE: BattleManager handles all callbacks (on_turn_resolve, on_consensus, on_battle_start)
        # AutoBattleComms only provides auto-accept and AI move selection
        
        # Set player data provider to get data from station config
        self.player_data_provider = self._get_player_data
        
        self.logger.info(f"AutoBattleComms initialized (duration={auto_battle_duration_ms}ms, difficulty={difficulty})")
    
    def _get_player_data(self):
        """
        Get current player data from station configuration.
        
        For stations, uses the station's character.
        Fallback to 'deeno' (the starter character for all badges).
        
        Returns:
            dict: Player data with keys: character_id, level, name, wins, losses, is_station
        """
        char_id = 'deeno'  # Default starter character
        if self.station:
            char_id = self.station.character_id
        
        return {
            'character_id': char_id,
            'level': 1,  # Stations don't level up
            'name': getattr(self, 'device_name', None),
            'wins': self.stats.get('wins', 0),  # Return persisted wins
            'losses': self.stats.get('losses', 0),  # Return persisted losses
            'is_station': 1,  # AutoBattleComms is ONLY used by stations
        }
    
    def start_auto_battle_mode(self, duration_ms=None, difficulty=None):
        """
        Enable auto-battle testing mode.

        Sets badge to AVAILABILITY_OPEN, starts GATT server to accept 
        incoming connections, and prepares to auto-accept challenges.

        Args:
            duration_ms (int, optional): Override for auto-battle duration in milliseconds.
            difficulty (int, optional): Override AI difficulty level.

        Returns:
            bool: True if auto-battle mode activated.
        """
        if duration_ms:
            self.auto_battle_duration_ms = duration_ms
        
        if difficulty is not None:
            self.difficulty = difficulty
        
        # Start GATT server to accept incoming connections
        if not self.start_server_mode():
            self.logger.error("Failed to start GATT server for auto-battle")
            return False
        
        self.auto_battle_mode_enabled = True
        self.auto_battle_state = AUTO_BATTLE_IDLE
        
        # Reset battle HP to character stats or defaults
        if self.our_stats:
            self.our_hp = self.our_stats.hp
            self.our_max_hp = self.our_stats.max_hp
        else:
            self.our_hp = DEFAULT_AUTO_BATTLE_HP
            self.our_max_hp = DEFAULT_AUTO_BATTLE_HP
        self.opponent_hp = DEFAULT_AUTO_BATTLE_HP
        self.opponent_max_hp = DEFAULT_AUTO_BATTLE_HP
        
        # Advertise as OPEN and looking for battles
        self.start_advertising(AVAILABILITY_OPEN)
        
        difficulty_names = ["EASY", "MEDIUM", "HARD"]
        diff_name = difficulty_names[self.difficulty] if self.difficulty < len(difficulty_names) else "UNKNOWN"
        
        self.logger.info("=== AUTO-BATTLE MODE ENABLED ===")
        self.logger.info(f"Difficulty: {diff_name}")
        self.logger.info(f"Duration per battle: {self.auto_battle_duration_ms}ms")
        self.logger.info("GATT server running - accepting connections...")
        
        return True
    
    def stop_auto_battle_mode(self):
        """
        Disable auto-battle testing mode.

        Stops GATT server, advertising, and accepting challenges. Returns to normal mode.
        """
        self.auto_battle_mode_enabled = False
        
        # Stop any active battle
        if self.session:
            self.end_session()
        
        # Stop GATT server
        self.stop_server_mode()
        
        # Return to IDLE
        self.stop_advertising()
        self.set_availability(AVAILABILITY_IDLE)
        
        self.logger.info("=== AUTO-BATTLE MODE DISABLED ===")
        self.logger.info(f"Battle Statistics: {self.stats}")
    
    def get_auto_battle_stats(self):
        """
        Get current auto-battle statistics.

        Returns:
            dict: Current auto-battle state and statistics.
        """
        result = {
            'state': self.auto_battle_state,
            'enabled': self.auto_battle_mode_enabled,
            'duration_ms': self.auto_battle_duration_ms,
        }
        result.update(self.stats)
        return result
    
    def _sync_wins_losses_from_prefs(self):
        """
        Sync wins/losses from BattleManager's player keys (KEY_WINS/KEY_LOSSES).
        Called after battle completion so that updated stats are reflected in our stats dict.
        """
        try:
            # Import the keys from battle_manager
            from cactuscon.game.battle_manager import KEY_WINS, KEY_LOSSES
            wins = prefs.get_int32(KEY_WINS, 0)
            losses = prefs.get_int32(KEY_LOSSES, 0)
            self.stats['wins'] = wins
            self.stats['losses'] = losses
            self.logger.debug(f"[SYNC] Synced wins={wins}, losses={losses} from BattleManager keys")
        except Exception as e:
            self.logger.debug(f"Could not sync wins/losses from BattleManager: {e}")
    
    def _persist_stats_to_prefs(self):
        """
        Persist station battle statistics to NVS so they survive reboots.
        Called after each battle outcome.
        """
        try:
            prefs.begin(write=True, context="auto_battle.persist_stats")
            prefs.set_int32(KEY_STATION_WINS, self.stats.get('wins', 0))
            prefs.set_int32(KEY_STATION_LOSSES, self.stats.get('losses', 0))
            prefs.set_int32(KEY_STATION_CHALLENGES, self.stats.get('total_challenges', 0))
            prefs.end()
            self.logger.debug(
                f"[PERSIST] Station stats: wins={self.stats.get('wins', 0)}, "
                f"losses={self.stats.get('losses', 0)}, challenges={self.stats.get('total_challenges', 0)}"
            )
        except Exception as e:
            self.logger.error(f"Failed to persist station stats: {e}")
    
    def _clear_pending_callbacks(self):
        """
        Clear any pending callback state that was deferred from BLE IRQ context.
        This prevents stale callbacks from executing on the next battle.
        """
        # Clear pending turn resolution
        self.pending_turn_resolve = None
        
        # Clear any pending challenges
        self.pending_challenges = {}

    def _reset_battle_state(self):
        """
        Reset all per-battle state for a new battle.
        This should be called after a battle ends or before a new one starts.
        """
        # Reset HP and stats
        if self.station_id and self.station:
            self.our_stats = self.station.get_battle_stats()
            self.our_hp = self.our_stats.hp
            self.our_max_hp = self.our_stats.max_hp
        else:
            self.our_stats = CharacterStats()
            self.our_hp = DEFAULT_AUTO_BATTLE_HP
            self.our_max_hp = DEFAULT_AUTO_BATTLE_HP
        self.opponent_stats = CharacterStats()
        self.opponent_hp = DEFAULT_AUTO_BATTLE_HP
        self.opponent_max_hp = DEFAULT_AUTO_BATTLE_HP
        # Reset timers
        self.battle_start_time = 0
        self.last_move_time = 0
        # Clear any other per-battle state here if needed
        self.logger.info("[AutoBattle] Battle state reset for new session.")

    def update(self):
        """
        Update auto-battle state machine.

        Handles:
            - Auto-accepting incoming challenges
            - Simulating battle moves at intervals
            - Detecting battle timeouts
            - Resetting for next challenger

        Call this regularly (e.g., every 100-500ms in main loop).
        """
        # Always call parent update for core protocol handling
        super().update()
        
        if not self.auto_battle_mode_enabled:
            return
        
        now = time.ticks_ms()
        
        # State machine
        if self.auto_battle_state == AUTO_BATTLE_IDLE:
            self.logger.debug("[AutoBattle] State: IDLE")
            # Waiting for a challenge - ensure we're advertising OPEN
            if not self._is_advertising or self.availability != AVAILABILITY_OPEN:
                self.logger.debug("[AutoBattle] Advertising as OPEN in IDLE state.")
                self.start_advertising(AVAILABILITY_OPEN)
        
        elif self.auto_battle_state == AUTO_BATTLE_CHALLENGE_PENDING:
            self.logger.debug("[AutoBattle] State: CHALLENGE_PENDING")
            # Challenge received, waiting for session to be established
            # Parent class is handling handshake - just wait for session to reach BATTLING
            if self.session and self.session.state == SESSION_BATTLING:
                self.logger.info("[AutoBattle] Transition: CHALLENGE_PENDING -> ACTIVE")
                # Battle started!
                self.battle_start_time = now
                self.last_move_time = now
                self.auto_battle_state = AUTO_BATTLE_ACTIVE
                self.stats['accepted_challenges'] += 1
                self.logger.info("Battle session established, simulating moves...")
                # Send initial status
                self.send_status(DEFAULT_AUTO_BATTLE_HP, status_flags=0)
        
        elif self.auto_battle_state == AUTO_BATTLE_ACTIVE:
            self.logger.debug("[AutoBattle] State: ACTIVE")
            # Battle in progress
            if not self.session:
                self.logger.warning("Battle session lost")
                self.stats['failed_battles'] += 1
                self._persist_stats_to_prefs()
                self.logger.info("[AutoBattle] Transition: ACTIVE -> TIMEOUT (session lost)")
                self.auto_battle_state = AUTO_BATTLE_TIMEOUT
                return
            if self.session.state == SESSION_COMPLETE:
                self.logger.info("Battle completed")
                self.stats['completed_battles'] += 1
                self._sync_wins_losses_from_prefs()
                self._persist_stats_to_prefs()
                self.logger.info("[AutoBattle] Transition: ACTIVE -> TIMEOUT (session complete)")
                self.auto_battle_state = AUTO_BATTLE_TIMEOUT
                return
            if self.session.state != SESSION_BATTLING:
                self.logger.warning(f"Unexpected session state: {self.session.state}")
                self.stats['failed_battles'] += 1
                self._persist_stats_to_prefs()
                self.logger.info("[AutoBattle] Transition: ACTIVE -> TIMEOUT (unexpected state)")
                self.auto_battle_state = AUTO_BATTLE_TIMEOUT
                return
            # Turn-based: only send move when it's our turn to select
            if self.is_our_turn():
                move_id = self._select_ai_move()
                if self.send_turn_ready(move_id, move_data=None):
                    self.stats['total_moves_sent'] += 1
                    self.last_move_time = now
                    self.logger.debug(f"AI selected move {move_id} (waiting for opponent)")
            # Check for move timeout - opponent not responding
            if self.session.is_expired(MOVE_TIMEOUT_MS):
                self.logger.warning("Move timeout - ending auto-battle")
                self.stats['failed_battles'] += 1
                self._persist_stats_to_prefs()
                self.logger.info("[AutoBattle] Transition: ACTIVE -> TIMEOUT (move timeout)")
                self.auto_battle_state = AUTO_BATTLE_TIMEOUT
                return
        
        elif self.auto_battle_state == AUTO_BATTLE_TIMEOUT:
            self.logger.debug("[AutoBattle] State: TIMEOUT")
            # Battle just ended - cleanup and reset
            self.end_session()
            self._clear_pending_callbacks()
            self._reset_battle_state()
            self.logger.info("[AutoBattle] Transition: TIMEOUT -> IDLE")
            self.auto_battle_state = AUTO_BATTLE_IDLE
            # Ensure we're advertising again for next challenger
            self.start_advertising(AVAILABILITY_OPEN)
            self.logger.info("Ready for next challenge...")
    
    def _select_ai_move(self):
        """
        Select a move based on AI difficulty level and character's move set.
        
        Uses the character's actual moves from station_config if available.
        Categories:
            MOVE_CAT_DAMAGE: Standard damage move
            MOVE_CAT_HEAVY: High damage, high risk
            MOVE_CAT_SUPPORT: Status/buff moves
            MOVE_CAT_RECOVERY: HP healing moves
        
        Difficulty affects how often AI makes "smart" vs random choices:
            EASY: 70% random, 30% smart
            MEDIUM: 40% random, 60% smart
            HARD: 10% random, 90% smart
        
        Returns:
            int: Selected move ID from character's move set.
        """
        # Use character moves if available, otherwise defaults
        available_moves = self.character_moves if self.character_moves else [0, 1, 2, 3]
        
        # Difficulty-based randomness threshold
        random_thresholds = {
            DIFFICULTY_EASY: 0.70,
            DIFFICULTY_MEDIUM: 0.40,
            DIFFICULTY_HARD: 0.10,
        }
        random_chance = random_thresholds.get(self.difficulty, 0.40)
        
        # Random move from available set?
        if urandom.random() < random_chance:
            return urandom.choice(available_moves)
        
        # Smart move selection based on battle state and move categories
        max_hp = getattr(self, 'our_max_hp', DEFAULT_AUTO_BATTLE_HP)
        hp_percent = self.our_hp / max_hp
        opponent_hp_percent = self.opponent_hp / DEFAULT_AUTO_BATTLE_HP
        
        # Categorize available moves using Move classes
        recovery_moves = []
        damage_moves = []
        heavy_moves = []
        support_moves = []
        
        for move_id in available_moves:
            move = get_move(move_id)
            if move:
                cat = move.category
                if cat == MOVE_CAT_RECOVERY:
                    recovery_moves.append(move_id)
                elif cat == MOVE_CAT_HEAVY:
                    heavy_moves.append(move_id)
                elif cat == MOVE_CAT_SUPPORT:
                    support_moves.append(move_id)
                else:
                    damage_moves.append(move_id)
            else:
                damage_moves.append(move_id)  # Unknown moves default to damage
        
        # Low HP - prioritize healing if available
        if hp_percent < 0.3 and recovery_moves:
            return urandom.choice(recovery_moves)
        
        # We're winning - play aggressive
        if hp_percent > opponent_hp_percent + 0.2:
            aggressive = damage_moves + heavy_moves
            if aggressive:
                return urandom.choice(aggressive)
        
        # We're losing - try to turn the tide
        if hp_percent < opponent_hp_percent - 0.2:
            if heavy_moves and urandom.random() < 0.5:
                return urandom.choice(heavy_moves)  # Risky but high reward
            if recovery_moves:
                return urandom.choice(recovery_moves)
        
        # Even match - balanced approach, favor damage moves
        if damage_moves:
            return urandom.choice(damage_moves)
        
        # Fallback to any available move
        return urandom.choice(available_moves)
    
    def set_difficulty(self, difficulty):
        """
        Set AI difficulty level.
        
        Args:
            difficulty (int): DIFFICULTY_EASY, DIFFICULTY_MEDIUM, or DIFFICULTY_HARD.
        """
        self.difficulty = difficulty
        difficulty_names = ["EASY", "MEDIUM", "HARD"]
        diff_name = difficulty_names[difficulty] if difficulty < len(difficulty_names) else "UNKNOWN"
        self.logger.info(f"AI difficulty set to {diff_name}")
    
    # Override challenge handling
    
    def _handle_challenge_request(self, data):
        """
        Handle incoming challenge request (auto-accept mode).

        In auto-battle mode, automatically accept all challenges without user intervention.
        Does NOT call super() to avoid triggering challenge_callback which would cause
        double-acceptance (and recursion).

        Args:
            data (bytes): Challenge request message bytes.
        """
        if len(data) < 4:
            return
        
        # Extract opponent info directly (same as parent, but without triggering callback)
        protocol_ver, name_len = struct.unpack_from('<HB', data, 1)
        
        if protocol_ver != PROTOCOL_VERSION:
            self.logger.warning(f"Protocol version mismatch: {protocol_ver} != {PROTOCOL_VERSION}")
            self._send_error(1, "Protocol version mismatch")
            return
        
        opponent_name = "Unknown"
        if len(data) >= 4 + name_len:
            try:
                opponent_name = data[4:4+name_len].decode('utf-8')
            except Exception:
                pass
        
        # Get opponent address from connection
        conn_info = self.bt.get_connection_info()
        if not conn_info:
            self.logger.warning("No connection info for challenge request")
            return
        
        opponent_addr = conn_info['addr']
        self.pending_challenges[opponent_addr] = (time.ticks_ms(), opponent_name)
        
        self.logger.info(f"Challenge received from '{opponent_name}'")
        
        # In auto-battle mode, immediately accept the challenge
        if self.auto_battle_mode_enabled:
            self.stats['total_challenges'] += 1
            self._persist_stats_to_prefs()
            
            self.logger.info(f"Challenge from {opponent_name} - auto-accepting...")
            
            # NOTE: player_data_provider callback handles player data
            # when _send_player_data() is called after session is established
            
            # Accept the challenge
            self.accept_challenge(opponent_addr)
            
            # Move to challenge pending state to wait for battle to start
            self.auto_battle_state = AUTO_BATTLE_CHALLENGE_PENDING
    
    def _handle_challenge_accept(self, data):
        """
        Handle challenge acceptance (for when we initiate challenge).

        Args:
            data (bytes): Challenge accept message bytes.
        """
        super()._handle_challenge_accept(data)
        self.logger.debug("Challenge accepted (unexpected in auto-battle mode)")
    
    def _handle_battle_status(self, data):
        """
        Handle opponent's battle status update.
        
        Tracks opponent HP for percentage-based winner calculation on timeout.
        First status message sets opponent_max_hp (assumes opponent starts at full HP).
        
        Args:
            data (bytes): Battle status message bytes (type, hp:H, flags:B).
        """
        super()._handle_battle_status(data)
        
        if self.session and self.session.state == SESSION_BATTLING:
            if len(data) >= 4:
                hp = struct.unpack_from('<H', data, 1)[0]
                
                # First status message - assume opponent is at full HP, set as max
                if self.opponent_max_hp == DEFAULT_AUTO_BATTLE_HP and hp > 0:
                    self.opponent_max_hp = hp
                    self.logger.debug(f"Opponent max HP set to {hp}")
                
                self.opponent_hp = hp
                self.logger.debug(f"Opponent HP: {hp}/{self.opponent_max_hp}")

    def _handle_battle_result(self, data):
        """Handle battle result from opponent."""
        super()._handle_battle_result(data)
        
        # Transition to timeout state if we haven't already
        # (update() may have already transitioned when we sent our result)
        if self.auto_battle_state == AUTO_BATTLE_ACTIVE:
            self.logger.info("Battle result received from opponent")
            self.stats['completed_battles'] += 1
            self._sync_wins_losses_from_prefs()
            self._persist_stats_to_prefs()
            self.auto_battle_state = AUTO_BATTLE_TIMEOUT
    
    def _handle_disconnect(self, conn_handle, addr_type, addr):
        """
        Handle unexpected disconnection.

        Args:
            conn_handle (int): Connection handle.
            addr_type (int): Address type.
            addr (bytes): Device MAC address.
        """
        # Call parent to handle disconnect
        super()._handle_disconnect(conn_handle, addr_type, addr)
        
        # If we were in a battle, count as failed
        if self.auto_battle_state == AUTO_BATTLE_ACTIVE:
            self.logger.warning("Disconnected during battle")
            self.stats['failed_battles'] += 1
            self._persist_stats_to_prefs()
        
        # Reset to idle to accept next challenge
        self.auto_battle_state = AUTO_BATTLE_IDLE
        
        # Ensure advertising is running
        if not self._is_advertising:
            self.start_advertising(AVAILABILITY_OPEN)
    
    def _handle_error(self, message, code=0):
        """
        Handle protocol error.

        Args:
            message (str): Error message.
            code (int, optional): Error code.
        """
        # Call parent to handle error
        super()._handle_error(message, code)
        
        # Count as failed battle if we were battling
        if self.auto_battle_state == AUTO_BATTLE_ACTIVE:
            self.stats['failed_battles'] += 1
            self._persist_stats_to_prefs()
        
        # Reset to idle
        self.auto_battle_state = AUTO_BATTLE_IDLE
        
        # Ensure advertising is running
        if not self._is_advertising:
            self.start_advertising(AVAILABILITY_OPEN)
