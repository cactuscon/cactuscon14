"""Bluetooth Low Energy (BLE) management for ESP32-S3 badge."""

import bluetooth
import network
import struct
import time
import _thread
import gc
from micropython import const

from cactuscon.utils import Logger
from cactuscon import config

# Module-level logger for IRQ handlers and static methods

logger = Logger(config.LOG_LEVEL)

# BLE advertisement types
_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID16_COMPLETE = const(0x03)
_ADV_TYPE_UUID128_COMPLETE = const(0x07)
_ADV_TYPE_MANUFACTURER = const(0xFF)

# BLE IRQ events - Client (GATTC)
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_READ_RESULT = const(15)
_IRQ_GATTC_WRITE_DONE = const(17)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_MTU_EXCHANGED = const(21)

# BLE IRQ events - Server (GATTS)
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_GATTS_INDICATE_DONE = const(20)

# Connection states
STATE_IDLE = const(0)
STATE_SCANNING = const(1)
STATE_CONNECTING = const(2)
STATE_CONNECTED = const(3)
STATE_DISCONNECTING = const(4)

# Default configuration - OPTIMIZED for memory-constrained devices sharing heap with LVGL
DEFAULT_SCAN_DURATION_MS = const(2000)   # 2 seconds (shorter scans, less memory pressure)
DEFAULT_SCAN_INTERVAL_US = const(100000) # 100ms interval (less aggressive than 30ms)
DEFAULT_SCAN_WINDOW_US = const(50000)    # 50ms window (50% duty cycle, not 100%)
DEFAULT_MAX_DEVICES = const(12)          # Track top 10 devices (was 20)
DEFAULT_RSSI_THRESHOLD = const(-85)      # Minimum RSSI (was -90, filter more aggressively)
DEFAULT_RXBUF_SIZE = const(256)          # BLE receive buffer size

# Badge availability states (for matchmaking) - exported for game layer use
AVAILABILITY_IDLE = const(0)           # Badge running, but not open to battles
AVAILABILITY_OPEN = const(1)           # Badge actively looking for battles
AVAILABILITY_IN_BATTLE = const(2)      # Badge currently in battle

# CactusCon badge UUID pattern bytes (little-endian)
# Original UUID format: CC140001-XXXX-XXXX-XXXX-CAC71B072026
# In BLE little-endian, the bytes are reversed
CACTUSCON_UUID_PREFIX_LE = bytes([0x01, 0x00, 0x14, 0xCC])  # CC140001 reversed
CACTUSCON_UUID_SUFFIX_LE = bytes([0x26, 0x20, 0x07, 0x1B, 0xC7, 0xCA])  # CAC71B072026 reversed

CACTUSCON_DEVICE_MAX_TTL_MS = const(25000)  # 25 seconds before forgetting a device
CACTUSCON_DEVICE_MIN_RSSI = const(-78)        # Minimum RSSI to consider a badge nearby


class BluetoothDevice:
    """
    Represents a discovered Bluetooth device with metadata.

    Tracks device address, name, RSSI, last seen timestamp, and parsed availability.
    Memory-optimized: stores parsed fields instead of raw adv_data (~31 bytes saved per device).
    """
    
    __slots__ = ('addr_type', 'addr', 'name', 'rssi', 'last_seen', 'availability', 'service_uuid_bytes')
    
    def __init__(self, addr_type, addr, name=None, rssi=-100,
                 availability=None, service_uuid_bytes=None):
        """
        Initialize a Bluetooth device record.

        Args:
            addr_type (int): Address type (0=public, 1=random).
            addr (bytes): 6-byte MAC address.
            name (str, optional): Device name string (max 20 chars stored).
            rssi (int): Signal strength in dBm.
            availability (int, optional): Parsed availability state (0=IDLE, 1=OPEN, 2=IN_BATTLE).
            service_uuid_bytes (bytes, optional): 16-byte service UUID if CactusCon badge.
        """
        self.addr_type = addr_type
        self.addr = addr
        # Allow slightly longer names (up to 32 bytes) so opponent handles aren't cut prematurely
        self.name = (name[:32] if name and len(name) > 32 else name) or "Unknown"
        self.rssi = rssi
        self.last_seen = time.ticks_ms()
        self.availability = availability  # None = unknown, 0=IDLE, 1=OPEN, 2=IN_BATTLE
        self.service_uuid_bytes = service_uuid_bytes  # Store only if CactusCon badge
    
    def addr_str(self):
        """
        Return MAC address as formatted hex string (XX:XX:XX:XX:XX:XX).

        Returns:
            str: Formatted MAC address.
        """
        return BluetoothManager.format_address(self.addr)
    
    def update(self, rssi, name=None, availability=None,
               service_uuid_bytes=None):
        """
        Update device metadata from a new scan result.

        Args:
            rssi (int): New RSSI value.
            name (str, optional): Updated device name.
            availability (int, optional): Updated availability state.
            service_uuid_bytes (bytes, optional): Updated service UUID.
        """
        self.rssi = rssi
        self.last_seen = time.ticks_ms()
        if name:
            # Keep the longest name seen so scan-response names don't get overwritten
            candidate = name[:32] if len(name) > 32 else name
            if self.name == "Unknown" or len(candidate) > len(self.name):
                self.name = candidate
        if availability is not None:
            self.availability = availability
        if service_uuid_bytes is not None:
            self.service_uuid_bytes = service_uuid_bytes
    
    def age_ms(self):
        """
        Return milliseconds since the device was last seen.

        Returns:
            int: Milliseconds since last seen.
        """
        return time.ticks_diff(time.ticks_ms(), self.last_seen)
    
    @property
    def is_cactuscon_badge(self):
        """
        Check if this device is a CactusCon badge.
        
        Returns:
            bool: True if device has CactusCon service UUID.
        """
        return self.service_uuid_bytes is not None
    
    def is_available(self):
        """
        Check if this device is available for battle (AVAILABILITY_OPEN).
        
        Returns:
            bool: True if availability is OPEN, False otherwise.
        """
        return self.availability == AVAILABILITY_OPEN
    
    def get_embedded_mac(self):
        """
        Extract the MAC address embedded in the service UUID.
        
        CactusCon badge UUIDs embed the device MAC in the middle:
        CC140001-AABB-CCDD-EEFF-CAC71B072026 -> MAC is AA:BB:CC:DD:EE:FF
        
        Returns:
            bytes: 6-byte MAC address, or None if not a CactusCon badge.
        """
        if not self.service_uuid_bytes or len(self.service_uuid_bytes) != 16:
            return None
        # UUID bytes are little-endian
        # Bytes 6-11 contain the MAC address (middle of UUID)
        return bytes(reversed(self.service_uuid_bytes[6:12]))
    
    def __repr__(self):
        avail = ['IDLE', 'OPEN', 'BATTLE'][self.availability] if self.availability is not None else '?'
        return f"<BluetoothDevice {self.addr_str()} '{self.name}' RSSI={self.rssi} {avail}>"


class BluetoothManager:
    """
    Core Bluetooth Low Energy manager for ESP32-S3 badge.

    Provides operating modes:
        1. Passive scanning: Discover nearby devices for proximity detection.
        2. Active connection: Establish P2P link with a specific device (as GATT client).
        3. GATT Server: Accept incoming connections from other badges.

    Design considerations:
        - Memory efficient: Limited device tracking, parsed data only (no raw adv_data).
        - Non-blocking: Uses IRQ callbacks, minimal processing in handler.
        - Thread-safe: All state changes protected by lock for IRQ safety.
        - Power aware: Optimized scan parameters for battery life.
        - Shares memory with LVGL: Configured for constrained heap (~2MB total).

    Memory Optimization:
        - Configured rxbuf to handle scan bursts without exhausting NimBLE pools
        - 50% scan duty cycle reduces IRQ frequency
        - Parses and discards adv_data immediately, stores only essential fields
        - Shorter scan duration reduces sustained memory pressure

    Usage:
        bt = BluetoothManager(max_devices=10)
        bt.start_scan()
        # Later...
        nearby = bt.get_nearby_devices(min_rssi=-70)
    """
    
    # CactusCon badge UUID pattern for filtering
    # Format: CC140001-XXXX-XXXX-XXXX-CAC71B072026
    CACTUSCON_UUID_PREFIX = b'\xcc\x14\x00\x01'
    CACTUSCON_UUID_SUFFIX = b'\xca\xc7\x1b\x07\x20\x26'
    
    @staticmethod
    def format_address(addr):
        """
        Format a BLE MAC address as a colon-separated hex string.

        Args:
            addr (bytes or bytearray): 6-byte MAC address.

        Returns:
            str: Formatted MAC address (e.g., 'aa:bb:cc:dd:ee:ff').
        """
        return ':'.join('{:02x}'.format(b) for b in addr)
    
    @staticmethod
    def parse_address(addr_str):
        """
        Parse a colon-separated MAC address string into bytes.

        Args:
            addr_str (str): Address string like 'AA:BB:CC:DD:EE:FF'.

        Returns:
            bytes: 6-byte address.

        Raises:
            ValueError: If address format is invalid.
        """
        try:
            parts = addr_str.split(':')
            if len(parts) != 6:
                raise ValueError("Address must have 6 octets")
            return bytes(int(b, 16) for b in parts)
        except (ValueError, AttributeError) as e:
            raise ValueError("Invalid address format: {}".format(addr_str))

    @staticmethod
    def uuid_to_bytes(uuid):
        """
        Convert a bluetooth.UUID object to bytes.

        Handles both 16-bit and 128-bit UUIDs properly for ESP32-S3.
        MicroPython's bluetooth.UUID doesn't have a .bytes attribute,
        so we need to extract the bytes based on the UUID type.

        Args:
            uuid (bluetooth.UUID): UUID object.

        Returns:
            bytes: UUID as raw bytes (2 bytes for 16-bit, 16 bytes for 128-bit).
        """
        # Convert UUID to string and parse it
        uuid_str = str(uuid)
        
        # MicroPython's str(UUID) returns "UUID('...')" format, extract the actual UUID
        if uuid_str.startswith("UUID('") and uuid_str.endswith("')"):
            uuid_str = uuid_str[6:-2]  # Extract content between UUID(' and ')
        elif uuid_str.startswith('UUID("') and uuid_str.endswith('")'):
            uuid_str = uuid_str[6:-2]  # Extract content between UUID(" and ")
        
        # Check if it's a 16-bit UUID (4 hex chars, possibly 0x prefix)
        if uuid_str.startswith('0x') or (len(uuid_str) == 4 and all(c in '0123456789abcdefABCDEF' for c in uuid_str)):
            # 16-bit UUID
            if uuid_str.startswith('0x'):
                uuid_int = int(uuid_str, 16)
            else:
                uuid_int = int(uuid_str, 16)
            return struct.pack('<H', uuid_int)  # Little-endian 16-bit
        else:
            # 128-bit UUID string format: "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
            # Remove dashes and convert to bytes
            uuid_hex = uuid_str.replace('-', '')
            if len(uuid_hex) != 32:
                raise ValueError(f"Invalid UUID format: {uuid_str}")
            
            # Convert hex string to bytes (reverse for little-endian)
            uuid_bytes = bytes.fromhex(uuid_hex)
            # BLE UUIDs are transmitted in little-endian order
            return bytes(reversed(uuid_bytes))

    @staticmethod
    def get_mac_address():
        """
        Get the device's BLE MAC address.

        Returns:
            bytes: 6-byte MAC address.
        """
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        mac = wlan.config('mac')
        wlan.active(False)
        return bytes(mac)

    @staticmethod
    def create_device_uuid(base_uuid, mac_address=None):
        """
        Create a device-specific UUID by embedding the MAC address.

        Takes a base UUID like 'CC140001-XXXX-XXXX-XXXX-CAC71B072026' and replaces
        the middle 12 hex characters with the device's MAC address.

        Args:
            base_uuid (str or bluetooth.UUID): Template UUID string or UUID object.
            mac_address (bytes, optional): 6-byte MAC address (None = auto-detect).

        Returns:
            bluetooth.UUID: UUID with embedded MAC address.
        """
        if mac_address is None:
            mac_address = BluetoothManager.get_mac_address()
        
        # Convert base UUID to string
        base_str = str(base_uuid)
        if base_str.startswith("UUID('") or base_str.startswith('UUID("'):
            base_str = base_str[6:-2]
        
        # Format: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
        # Replace middle 12 chars (positions 9-20) with MAC address
        mac_hex = ''.join('{:02x}'.format(b) for b in mac_address)
        
        # Build new UUID: prefix + MAC (with dashes) + suffix
        # CC140001-AABB-CCDD-EEFF-CAC71B072026
        parts = base_str.split('-')
        if len(parts) != 5:
            raise ValueError("Invalid base UUID format")
        
        device_uuid = f"{parts[0]}-{mac_hex[0:4]}-{mac_hex[4:8]}-{mac_hex[8:12]}-{parts[4]}"
        
        return bluetooth.UUID(device_uuid)

    @staticmethod
    def extract_mac_from_uuid(service_uuid):
        """
        Extract the MAC address embedded in a CactusCon device's service UUID.
        
        CactusCon badge UUIDs embed the device MAC address in the middle:
        CC140001-AABB-CCDD-EEFF-CAC71B072026 -> MAC is AA:BB:CC:DD:EE:FF
        
        Args:
            service_uuid: bluetooth.UUID object, bytes (16), or string.
            
        Returns:
            bytes: 6-byte MAC address, or None if not a valid CactusCon UUID.
            
        Example:
            >>> mac = BluetoothManager.extract_mac_from_uuid("CC140001-AABB-CCDD-EEFF-CAC71B072026")
            >>> BluetoothManager.format_address(mac)
            'aa:bb:cc:dd:ee:ff'
        """
        # Handle bytes input (from BluetoothDevice.service_uuid_bytes)
        if isinstance(service_uuid, (bytes, bytearray)):
            if len(service_uuid) != 16:
                return None
            # UUID bytes are little-endian, MAC is in bytes 6-11
            # Need to reverse to get correct order
            return bytes(reversed(service_uuid[6:12]))
        
        # Handle string or UUID object
        uuid_str = str(service_uuid)
        
        # Strip UUID(' ... ') wrapper if present
        if uuid_str.startswith("UUID('") or uuid_str.startswith('UUID("'):
            uuid_str = uuid_str[6:-2]
        
        # Format: CC140001-AABB-CCDD-EEFF-CAC71B072026
        parts = uuid_str.split('-')
        if len(parts) != 5:
            return None
        
        # Verify CactusCon prefix and suffix
        if parts[0].upper() != 'CC140001' or parts[4].upper() != 'CAC71B072026':
            return None
        
        # Extract MAC from middle 3 parts: AABB-CCDD-EEFF
        try:
            mac_hex = parts[1] + parts[2] + parts[3]
            if len(mac_hex) != 12:
                return None
            return bytes.fromhex(mac_hex)
        except Exception:
            return None

    @staticmethod
    def is_cactuscon_uuid(uuid_bytes):
        """
        Check if UUID bytes match the CactusCon badge pattern.
        
        Args:
            uuid_bytes (bytes): 16-byte UUID in little-endian format.
            
        Returns:
            bool: True if this is a CactusCon badge UUID.
        """
        if not uuid_bytes or len(uuid_bytes) != 16:
            return False
        # Check prefix (bytes 12-15) and suffix (bytes 0-5)
        return (uuid_bytes[12:16] == CACTUSCON_UUID_PREFIX_LE and
                uuid_bytes[0:6] == CACTUSCON_UUID_SUFFIX_LE)
    
    def __init__(self, max_devices=DEFAULT_MAX_DEVICES, rssi_threshold=DEFAULT_RSSI_THRESHOLD,
                 rxbuf_size=DEFAULT_RXBUF_SIZE, logger_level=20):
        """
        Initialize the Bluetooth manager.

        Args:
            max_devices (int): Maximum number of devices to track by RSSI.
            rssi_threshold (int): Minimum RSSI to consider a device (-80 dBm default).
            rxbuf_size (int): BLE receive buffer size (handles scan result bursts).
            logger_level (int): Logging level (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR).
        """
        self.logger = Logger(logger_level)
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        
        # Try to configure BLE receive buffer to handle scan bursts
        # This is optional - not all MicroPython builds support it
        # If not supported, NimBLE uses its default buffer configuration
        try:
            self.ble.config(rxbuf=rxbuf_size)
            self.logger.debug(f"BLE rxbuf set to {rxbuf_size} bytes")
        except (ValueError, OSError) as e:
            # rxbuf config not supported on this build - that's OK
            self.logger.debug(f"rxbuf config not supported (using defaults)")
        
        # Device tracking - memory efficient
        self.max_devices = max_devices
        self.rssi_threshold = rssi_threshold
        self.devices = {}  # addr_bytes -> BluetoothDevice (minimal data)
        self.lock = _thread.allocate_lock()
        
        # Scan state
        self.state = STATE_IDLE
        self.scan_active = False
        self.scan_callback = None
        
        # Advertising state
        self.adv_active = False
        self.adv_params = {}  # Store params for restart after GATT registration
        
        # Connection state (as GATT client)
        self.conn_handle = None
        self.connected_addr = None
        self.connect_callback = None
        self.disconnect_callback = None
        self.data_callback = None
        self._pending_connect = None  # (conn_handle, addr_type, addr)
        self.negotiated_mtu = 23  # Default BLE MTU (20 byte payload)
        
        # Service/characteristic handles (set by higher-level modules)
        self.service_uuid = None
        self.char_uuid = None
        self.char_handle = None
        self._service_start_handle = None  # For characteristic discovery range
        self._service_end_handle = None
        
        # GATT Server state
        self.server_running = False
        self.server_service_handle = None
        self.server_char_handle = None
        self.server_connections = {}  # conn_handle -> addr_bytes
        self.server_data_callback = None
        
        # Pending data queue (deferred from IRQ to avoid stack overflow)
        # List of (conn_handle, data_bytes) tuples for server mode
        # List of data_bytes for client mode (notifications)
        self._pending_server_data = []  # Server: writes from central
        self._pending_client_data = []  # Client: notifications from server
        self._pending_disconnect = None  # For deferred disconnect
        self.max_server_connections = 1  # Badges only allow 1 connection (stations can override)
        
        # Register IRQ handler
        self.ble.irq(self._irq_handler)
        
        self.logger.info("BluetoothManager initialized")
    
    def _irq_handler(self, event, data):
        """
        Internal BLE interrupt handler.

        Processes BLE events from the radio and updates internal state.
        Called from BLE stack context - keep processing minimal.

        Args:
            event (int): BLE event constant (_IRQ_*).
            data (tuple): Event-specific data tuple.
        """
        if event == _IRQ_SCAN_RESULT:
            # Scan result: (addr_type, addr, adv_type, rssi, adv_data)
            addr_type, addr, adv_type, rssi, adv_data = data
            self._handle_scan_result(addr_type, addr, adv_type, rssi, adv_data)
            
        elif event == _IRQ_SCAN_DONE:
            # Scan completed
            self._handle_scan_done()
            
        elif event == _IRQ_PERIPHERAL_CONNECT:
            # Connection established: (conn_handle, addr_type, addr)
            conn_handle, addr_type, addr = data
            self._handle_connect(conn_handle, addr_type, addr)
            
        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            # Disconnection: (conn_handle, addr_type, addr)
            conn_handle, addr_type, addr = data
            self._handle_disconnect(conn_handle, addr_type, addr)
            
        elif event == _IRQ_GATTC_SERVICE_RESULT:
            # Service discovery result: (conn_handle, start_handle, end_handle, uuid)
            conn_handle, start_handle, end_handle, uuid = data
            # Store service handle range for characteristic discovery
            self._service_start_handle = start_handle
            self._service_end_handle = end_handle
            self.logger.debug(f"Service found: handles={start_handle}-{end_handle}")
            
        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            # Characteristic discovery: (conn_handle, def_handle, value_handle, properties, uuid)
            conn_handle, def_handle, value_handle, properties, uuid = data
            logger.debug("[BT-IRQ] CHAR_RESULT: def={}, value={}, props={}, uuid={}".format(
                def_handle, value_handle, properties, bytes(uuid)))
            
            # Check if this matches our target characteristic UUID
            # We need WRITE capability (props & 0x08) for sending data
            uuid_bytes = bytes(uuid)
            target_uuid_bytes = bytes(self.char_uuid) if self.char_uuid else None
            
            if target_uuid_bytes and uuid_bytes == target_uuid_bytes:
                # Exact UUID match - this is our characteristic
                self.char_handle = value_handle
                logger.debug("[BT-IRQ] MATCHED char_uuid! char_handle={}".format(value_handle))
                self.logger.debug(f"Found game characteristic: handle={value_handle}")
            elif self.char_handle is None and target_uuid_bytes is None and (properties & 0x08):
                # Fallback: only when no UUID set, take first writable characteristic
                self.char_handle = value_handle
                logger.debug("[BT-IRQ] Fallback: saved writable char_handle={}".format(value_handle))
                self.logger.debug(f"Fallback characteristic handle: {value_handle}")
            
        elif event == _IRQ_GATTC_READ_RESULT:
            # Read result: (conn_handle, value_handle, char_data)
            conn_handle, value_handle, char_data = data
            # DEFER callback to process_pending() - avoid stack overflow in IRQ
            if self.data_callback:
                self._pending_client_data.append(bytes(char_data))
            
        elif event == _IRQ_GATTC_WRITE_DONE:
            # Write completed: (conn_handle, value_handle, status)
            conn_handle, value_handle, status = data
            logger.debug("[BT-IRQ] WRITE_DONE: conn={}, handle={}, status={}".format(conn_handle, value_handle, status))
            self.logger.debug(f"Write done: status={status}")
            
        elif event == _IRQ_GATTC_NOTIFY:
            # Notification received: (conn_handle, value_handle, notify_data)
            conn_handle, value_handle, notify_data = data
            logger.debug("[BT-IRQ] NOTIFY: conn={}, handle={}, len={}".format(
                conn_handle, value_handle, len(notify_data)))
            # DEFER callback to process_pending() - avoid stack overflow in IRQ
            if self.data_callback:
                self._pending_client_data.append(bytes(notify_data))
                logger.debug("[BT-IRQ] NOTIFY: queued for process_pending")
            else:
                logger.debug("[BT-IRQ] NOTIFY: NO data_callback!")
        
        elif event == _IRQ_MTU_EXCHANGED:
            # MTU exchange complete: (conn_handle, mtu)
            conn_handle, mtu = data
            self.negotiated_mtu = mtu
            self.logger.info(f"MTU exchanged: {mtu} bytes (payload: {mtu - 3} bytes)")
        
        # GATT Server events (when acting as peripheral)
        elif event == _IRQ_CENTRAL_CONNECT:
            # Central connected to us: (conn_handle, addr_type, addr)
            logger.debug("[BT-IRQ] CENTRAL_CONNECT")
            conn_handle, addr_type, addr = data
            self._handle_central_connect(conn_handle, addr_type, addr)
            
        elif event == _IRQ_CENTRAL_DISCONNECT:
            # Central disconnected: (conn_handle, addr_type, addr)
            logger.debug("[BT-IRQ] CENTRAL_DISCONNECT")
            conn_handle, addr_type, addr = data
            self._handle_central_disconnect(conn_handle, addr_type, addr)
            
        elif event == _IRQ_GATTS_WRITE:
            # Central wrote to our characteristic: (conn_handle, attr_handle)
            logger.debug("[BT-IRQ] GATTS_WRITE: conn={}, attr={}".format(data[0], data[1]))
            conn_handle, attr_handle = data
            self._handle_gatts_write(conn_handle, attr_handle)
            
        elif event == _IRQ_GATTS_READ_REQUEST:
            # Central requested read (optional handling)
            logger.debug("[BT-IRQ] GATTS_READ_REQUEST")
            conn_handle, attr_handle = data
            self.logger.debug(f"GATTS read request: handle={attr_handle}")
            
        elif event == _IRQ_GATTS_INDICATE_DONE:
            # Indication acknowledged: (conn_handle, value_handle, status)
            conn_handle, value_handle, status = data
            self.logger.debug(f"Indicate done: status={status}")
    
    def _handle_scan_result(self, addr_type, addr, adv_type, rssi, adv_data):
        """
        Process a scan result and update device tracking.
        
        Memory-optimized: parses adv_data immediately and discards it.
        Only stores essential fields (name, RSSI, availability, UUID).
        
        CRITICAL: This runs in IRQ context - keep allocations minimal!
        The addr and adv_data are memoryviews that become invalid after return.

        Args:
            addr_type (int): Address type (0=public, 1=random).
            addr (memoryview): 6-byte MAC address (MUST copy before storing).
            rssi (int): Signal strength in dBm.
            adv_data (memoryview): Raw advertisement payload (parsed immediately).
        """
        # Filter weak signals early (before any allocations)
        if rssi < self.rssi_threshold:
            return
        
        # Copy address immediately (memoryview becomes invalid after IRQ returns)
        addr_bytes = bytes(addr)
        
        # Parse essential data from advertisement or scan response (don't store raw adv_data)
        name = None
        availability = None
        service_uuid_bytes = None
        is_scan_response = adv_type == 0x04
        
        # Single pass through adv_data to extract what we need
        if adv_data:
            i = 0
            adv_len = len(adv_data)
            while i < adv_len:
                field_len = adv_data[i]
                if field_len == 0 or i + field_len >= adv_len:
                    break
                
                field_type = adv_data[i + 1]
                field_data = adv_data[i + 2:i + 1 + field_len]
                
                # Complete Local Name (0x09) or Shortened Name (0x08)
                if field_type in (0x08, 0x09) and not name:
                    try:
                        name = bytes(field_data).decode('utf-8')
                    except Exception:
                        pass
                
                # Manufacturer Data (0xFF) - may contain name after 2-byte company ID
                # Format: [company_id_lo, company_id_hi, name_bytes...]
                elif field_type == 0xFF and len(field_data) >= 3 and not name:
                    try:
                        # Skip 2-byte company ID, rest is name
                        mfr_name = bytes(field_data[2:]).decode('utf-8')
                        if mfr_name:
                            name = mfr_name
                    except Exception:
                        pass
                
                # 128-bit Service Data (0x21) - contains UUID + availability
                elif field_type == 0x21 and len(field_data) >= 17:
                    uuid_bytes = bytes(field_data[:16])
                    # Check if this is a CactusCon badge UUID
                    # Format: CC140001-XXXX-XXXX-XXXX-CAC71B072026 (little-endian)
                    # In little-endian: last 4 bytes are prefix, first 6 are suffix
                    if (len(uuid_bytes) == 16 and 
                        uuid_bytes[12:16] == b'\x01\x00\x14\xcc' and  # CC140001 reversed
                        uuid_bytes[0:6] == b'\x26\x20\x07\x1b\xc7\xca'):  # CAC71B072026 reversed
                        service_uuid_bytes = uuid_bytes
                        # Availability is the byte after the UUID
                        if len(field_data) >= 17:
                            availability = field_data[16]
                
                i += 1 + field_len
        
        # Update or create device record
        # NOTE: No lock here - IRQ handlers must not block
        existing = self.devices.get(addr_bytes)
        if existing:
            # Prefer scan-response name if present; otherwise keep longest or replace Unknown
            chosen_name = None
            if name:
                if is_scan_response or existing.name == "Unknown" or len(name) > len(existing.name):
                    chosen_name = name
            existing.update(rssi, chosen_name, availability, service_uuid_bytes)
        else:
            # Create new device record
            device = BluetoothDevice(addr_type, addr_bytes, name, rssi, availability, service_uuid_bytes)
            self.devices[addr_bytes] = device
            
            # Enforce max devices limit - evict weakest signal
            if len(self.devices) > self.max_devices:
                weakest_addr = min(self.devices.keys(), key=lambda a: self.devices[a].rssi)
                del self.devices[weakest_addr]
        
        # Invoke scan callback if registered
        if self.scan_callback:
            try:
                self.scan_callback(self.devices[addr_bytes])
            except Exception as e:
                self.logger.error(f"Scan callback error: {e}")
    
    def _handle_scan_done(self):
        """
        Handle scan completion event.
        """
        # NOTE: No lock here - IRQ handlers must not block
        self.scan_active = False
        self.state = STATE_IDLE
        self.logger.debug("Scan completed")
    
    def _handle_connect(self, conn_handle, addr_type, addr):
        """
        Handle successful connection establishment.
        
        NOTE: This runs in IRQ context! Do NOT do heavy operations here.
        The callback is deferred to process_pending() which runs in main loop.

        Args:
            conn_handle (int): Connection handle for future operations.
            addr_type (int): Address type of connected device.
            addr (bytes): MAC address of connected device.
        """
        logger.debug("[BT-IRQ] _handle_connect entered")
        # Copy addr immediately - memoryview becomes invalid after IRQ
        addr_bytes = bytes(addr)
        logger.debug("[BT-IRQ] addr copied")
        
        # NOTE: No lock here - IRQ handlers must not block
        # These writes are atomic on ESP32
        self.conn_handle = conn_handle
        self.connected_addr = addr_bytes
        self.state = STATE_CONNECTED
        logger.debug("[BT-IRQ] state updated")
        # Defer callback to outside IRQ context
        if self.connect_callback:
            self._pending_connect = (conn_handle, addr_type, addr_bytes)
            logger.debug("[BT-IRQ] pending_connect set")
        logger.debug("[BT-IRQ] _handle_connect done")
    
    def _handle_disconnect(self, conn_handle, addr_type, addr):
        """
        Handle disconnection event.

        DEFERS callback to process_pending() to avoid stack overflow.

        Args:
            conn_handle (int): Connection handle that was disconnected.
            addr_type (int): Address type of disconnected device.
            addr (bytes): MAC address of disconnected device.
        """
        addr_bytes = bytes(addr)  # Copy memoryview before it becomes invalid
        
        # NOTE: No lock here - IRQ handlers must not block
        # These writes are atomic on ESP32
        self.conn_handle = None
        self.connected_addr = None
        self.char_handle = None
        self.state = STATE_IDLE
        
        addr_str = self.format_address(addr_bytes)
        self.logger.info("Disconnected from {}".format(addr_str))
        
        # DEFER callback to process_pending() - avoid stack overflow in IRQ
        if self.disconnect_callback:
            self._pending_disconnect = (conn_handle, addr_type, addr_bytes)
    
    def _parse_name(self, adv_data):
        """
        Extract device name from BLE advertisement data.

        Parses standard BLE advertisement format (length, type, data).
        Looks for complete or shortened local name (types 0x08, 0x09).

        Args:
            adv_data (bytes): Raw advertisement payload bytes.

        Returns:
            str or None: Device name string or None if not found.
        """
        if not adv_data:
            return None
        
        i = 0
        while i < len(adv_data):
            # Advertisement data format: [length, type, data...]
            length = adv_data[i]
            if length == 0:
                break
            
            if i + length >= len(adv_data):
                break
            
            ad_type = adv_data[i + 1]
            ad_data = adv_data[i + 2:i + 1 + length]
            
            # 0x08 = Shortened Local Name, 0x09 = Complete Local Name
            if ad_type in (0x08, 0x09):
                try:
                    return ad_data.decode('utf-8')
                except Exception:
                    return None
            
            i += 1 + length
        
        return None
    
    def _parse_service_uuids(self, adv_data):
        """
        Extract service UUIDs from BLE advertisement data.

        Parses standard BLE advertisement format to find advertised services.
        Supports both 16-bit and 128-bit UUIDs.

        Args:
            adv_data (bytes): Raw advertisement payload bytes.

        Returns:
            list: List of bluetooth.UUID objects, or empty list if none found.
        """
        if not adv_data:
            return []
        
        uuids = []
        i = 0
        
        while i < len(adv_data):
            # Advertisement data format: [length, type, data...]
            length = adv_data[i]
            if length == 0:
                break
            
            if i + length >= len(adv_data):
                break
            
            ad_type = adv_data[i + 1]
            ad_data = adv_data[i + 2:i + 1 + length]
            
            # 0x02 = 16-bit UUID (incomplete), 0x03 = 16-bit UUID (complete)
            if ad_type in (0x02, 0x03) and len(ad_data) >= 2:
                # Parse 16-bit UUIDs
                for j in range(0, len(ad_data), 2):
                    if j + 1 < len(ad_data):
                        uuid16 = struct.unpack('<H', ad_data[j:j+2])[0]
                        uuids.append(bluetooth.UUID(uuid16))
            
            # 0x06 = 128-bit UUID (incomplete), 0x07 = 128-bit UUID (complete)
            elif ad_type in (0x06, 0x07) and len(ad_data) >= 16:
                # Parse 128-bit UUIDs
                for j in range(0, len(ad_data), 16):
                    if j + 15 < len(ad_data):
                        uuid_bytes = bytes(ad_data[j:j+16])
                        # Convert to standard UUID string format
                        uuid_str = '-'.join([
                            uuid_bytes[0:4].hex(),
                            uuid_bytes[4:6].hex(),
                            uuid_bytes[6:8].hex(),
                            uuid_bytes[8:10].hex(),
                            uuid_bytes[10:16].hex()
                        ])
                        try:
                            uuids.append(bluetooth.UUID(uuid_str))
                        except Exception:
                            pass
            
            i += 1 + length
        
        return uuids
    
    def has_service_uuid(self, device, service_uuid):
        """
        Check if a device is a CactusCon badge with matching service UUID.
        
        Uses pre-parsed service_uuid_bytes from device record instead of
        re-parsing adv_data (which is no longer stored).

        Args:
            device (BluetoothDevice): Device to check.
            service_uuid (bluetooth.UUID): Service UUID to check for.

        Returns:
            bool: True if device has the service UUID, False otherwise.
        """
        if not device.service_uuid_bytes:
            return False
        
        # Convert service_uuid to bytes for comparison
        try:
            uuid_bytes = self.uuid_to_bytes(service_uuid)
            return device.service_uuid_bytes == uuid_bytes
        except Exception:
            return False
    
    def start_scan(self, duration_ms=DEFAULT_SCAN_DURATION_MS, interval_us=DEFAULT_SCAN_INTERVAL_US, 
                   window_us=DEFAULT_SCAN_WINDOW_US, callback=None, active=False):
        """
        Start scanning for nearby BLE devices.

        Scanning is non-blocking and results are delivered via IRQ handler.
        Previous device list is NOT cleared - call clear_devices() first if needed.

        Args:
            duration_ms (int): Scan duration in milliseconds (0 = continuous).
            interval_us (int): Time between scan windows in microseconds.
            window_us (int): Active scan window duration in microseconds.
            callback (callable): Optional callback(device) called for each discovery.
            active (bool): True for active scanning (sends scan requests), False for passive.
                          Passive scanning uses less memory but won't get scan responses.

        Returns:
            bool: True if scan started, False if already scanning or connected.
        """
        with self.lock:
            if self.state != STATE_IDLE:
                self.logger.warning(f"Cannot scan in state {self.state}")
                return False
            
            self.scan_callback = callback
            self.scan_active = True
            self.state = STATE_SCANNING
        
        try:
            # Start BLE scan with specified parameters
            self.ble.gap_scan(duration_ms, interval_us, window_us, active)
            self.logger.info(f"Scan started (duration={duration_ms}ms, active={active})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start scan: {e}")
            with self.lock:
                self.scan_active = False
                self.state = STATE_IDLE
            return False
    
    def stop_scan(self):
        """
        Stop active scanning.

        Returns:
            bool: True if scan stopped, False if not scanning.
        """
        with self.lock:
            if not self.scan_active:
                return False
        
        try:
            self.ble.gap_scan(None)  # Stop scan
            # Small delay to let NimBLE release resources
            # This prevents os_memblock_get failures when quickly switching operations
            time.sleep_ms(30)
            self.logger.info("Scan stopped")
            with self.lock:
                self.scan_active = False
                self.state = STATE_IDLE
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop scan: {e}")
            return False
    
    def is_scanning(self):
        """
        Check if currently scanning for devices.

        Returns:
            bool: True if scanning, False otherwise.
        """
        with self.lock:
            return self.scan_active
    
    def get_nearby_devices(self, min_rssi=None, max_age_ms=None, limit=None) -> list:
        """
        Get list of nearby devices sorted by signal strength.

        Args:
            min_rssi (int, optional): Minimum RSSI filter (default: use threshold from init).
            max_age_ms (int, optional): Maximum age in milliseconds (filter stale devices).
            limit (int, optional): Maximum number of devices to return.

        Returns:
            list[BluetoothDevice]: List of BluetoothDevice objects sorted by RSSI (strongest first).
        """
        if min_rssi is None:
            min_rssi = self.rssi_threshold
        
        with self.lock:
            devices = list(self.devices.values())
        
        # Apply filters
        if max_age_ms is not None:
            devices = [d for d in devices if d.age_ms() <= max_age_ms]
        
        devices = [d for d in devices if d.rssi >= min_rssi]
        
        # Sort by RSSI (strongest first)
        devices.sort(key=lambda d: d.rssi, reverse=True)
        
        if limit:
            devices = devices[:limit]
        
        return devices
    
    def get_cactuscon_badges(self, min_rssi=CACTUSCON_DEVICE_MIN_RSSI, max_age_ms=CACTUSCON_DEVICE_MAX_TTL_MS):
        """
        Get list of nearby CactusCon badges (filtered by service UUID).

        Args:
            min_rssi (int, optional): Minimum RSSI filter (default: use threshold from init).
            max_age_ms (int): Maximum age in milliseconds (default: 5 seconds).

        Returns:
            list: List of BluetoothDevice objects that are CactusCon badges.
        """
        devices = self.get_nearby_devices(min_rssi=min_rssi, max_age_ms=max_age_ms)
        return [d for d in devices if d.is_cactuscon_badge]
    
    def get_available_badges(self, min_rssi=CACTUSCON_DEVICE_MIN_RSSI, max_age_ms=CACTUSCON_DEVICE_MAX_TTL_MS, limit=None):
        """
        Get list of nearby CactusCon badges available for battle.
        
        Convenience method that filters to badges with AVAILABILITY_OPEN state.
        This is the primary method game code should use to find opponents.

        Args:
            min_rssi (int, optional): Minimum RSSI filter (default: -70 for stable connection).
            max_age_ms (int): Maximum age in milliseconds (default: 5 seconds).
            limit (int, optional): Maximum number of badges to return.

        Returns:
            list: List of BluetoothDevice objects that are available for battle,
                  sorted by RSSI (strongest signal first).
        """
        if min_rssi is None:
            min_rssi = -70  # Use stricter threshold for battle connections
        
        badges = self.get_cactuscon_badges(min_rssi=min_rssi, max_age_ms=max_age_ms)
        available = [d for d in badges if d.is_available()]
        
        if limit:
            available = available[:limit]
        
        return available
    
    def get_device_by_addr(self, addr):
        """
        Retrieve device by MAC address.

        Args:
            addr (bytes or str): MAC address as bytes or formatted string (XX:XX:XX:XX:XX:XX).

        Returns:
            BluetoothDevice or None: The device if found, else None.
        """
        if isinstance(addr, str):
            addr = self.parse_address(addr)
        
        with self.lock:
            return self.devices.get(addr)
    
    def clear_devices(self):
        """
        Clear all tracked devices (useful before starting a fresh scan).
        """
        with self.lock:
            self.devices.clear()
            gc.collect()
        self.logger.debug("Device list cleared")
    
    def start_advertising(self, name=None, services=None, appearance=0, interval_us=100000, 
                          manufacturer_data=None, service_data=None):
        """
        Start BLE advertising to make this badge discoverable.

        Supports multiple BLE advertisement data types simultaneously:
            - Flags (mandatory)
            - Complete Local Name
            - Service UUIDs (128-bit)
            - Service Data (UUID + application data)
            - Manufacturer Data (company ID + custom data)

        All data types are optional except flags. The method will fit as much
        as possible within the 31-byte legacy BLE advertisement limit.

        Args:
            name (str, optional): Device name to advertise (default: 'Badge', max 20 chars).
            services (list, optional): List of service UUIDs to advertise.
            appearance (int): BLE appearance value (default: 0 = unknown).
            interval_us (int): Advertising interval in microseconds (default: 100ms).
            manufacturer_data (bytes, optional): Manufacturer-specific data.
            service_data (dict, optional): Dict mapping service UUID to data bytes.

        Returns:
            bool: True if advertising started successfully, False otherwise.
        """
        if name is None:
            name = "Badge"
        
        try:
            # Build advertisement payload with multiple data types
            adv_data = bytearray()
            
            # 1. Flags (mandatory) - 3 bytes
            adv_data.extend(b'\x02\x01\x06')  # General Discoverable + BR/EDR Not Supported
            
            # 2. Complete Local Name - will truncate if needed at end
            name_bytes = name.encode('utf-8')
            name_len = min(len(name_bytes), 20)  # Start with max 20, may reduce later
            name_field = bytearray([name_len + 1, 0x09]) + name_bytes[:name_len]
            
            # 3. Service Data (if provided) - most space efficient way to advertise service + data
            service_data_field = bytearray()
            if service_data:
                for service_uuid, data in service_data.items():
                    uuid_bytes = self.uuid_to_bytes(service_uuid)
                    
                    if len(uuid_bytes) == 2:
                        # 16-bit UUID Service Data (type 0x16)
                        field_len = 1 + len(uuid_bytes) + len(data)  # type + UUID + data
                        service_data_field.append(field_len)
                        service_data_field.append(0x16)
                        service_data_field.extend(uuid_bytes)
                        service_data_field.extend(data)
                    elif len(uuid_bytes) == 16:
                        # 128-bit UUID Service Data (type 0x21)
                        field_len = 1 + len(uuid_bytes) + len(data)
                        service_data_field.append(field_len)
                        service_data_field.append(0x21)
                        service_data_field.extend(uuid_bytes)
                        service_data_field.extend(data)
                    break  # Only advertise first service data to save space
            
            # 4. Service UUIDs (if provided and no service_data)
            # Skip if we already have service_data since it includes the UUID
            service_uuid_field = bytearray()
            if services and not service_data:
                for service_uuid in services:
                    uuid_bytes = self.uuid_to_bytes(service_uuid)
                    
                    if len(uuid_bytes) == 2:
                        # 16-bit UUID
                        service_uuid_field.append(3)
                        service_uuid_field.append(0x03)  # Complete 16-bit UUIDs
                        service_uuid_field.extend(uuid_bytes)
                    elif len(uuid_bytes) == 16:
                        # 128-bit UUID
                        service_uuid_field.append(17)
                        service_uuid_field.append(0x07)  # Complete 128-bit UUIDs
                        service_uuid_field.extend(uuid_bytes)
                    break  # Only advertise one service UUID to save space
            
            # 5. Manufacturer Data (if provided)
            manufacturer_field = bytearray()
            if manufacturer_data and len(manufacturer_data) >= 2:
                # Type 0xFF = Manufacturer Specific Data
                field_len = 1 + len(manufacturer_data)
                manufacturer_field.append(field_len)
                manufacturer_field.append(0xFF)
                manufacturer_field.extend(manufacturer_data)
            
            # 6. Appearance (optional, low priority)
            appearance_field = bytearray()
            if appearance:
                appearance_field.extend(struct.pack('<BBH', 3, 0x19, appearance))
            
            # Now assemble in priority order, truncating name if needed
            # Priority: flags > service_data > service_uuid > manufacturer > name > appearance
            
            adv_data = bytearray(b'\x02\x01\x06')  # Start with flags
            
            # Add service data (high priority - contains game state)
            if service_data_field:
                adv_data.extend(service_data_field)
            
            # Add service UUID (if no service data)
            if service_uuid_field:
                adv_data.extend(service_uuid_field)
            
            # Add manufacturer data
            if manufacturer_field:
                adv_data.extend(manufacturer_field)
            
            # Build scan response data with full name (up to 29 bytes after header)
            # This allows devices doing active scans to get the full name
            resp_data = bytearray()
            resp_name_len = min(len(name_bytes), 29)  # 31 - 2 for header
            if resp_name_len > 0:
                resp_data.append(resp_name_len + 1)
                resp_data.append(0x09)  # Complete Local Name
                resp_data.extend(name_bytes[:resp_name_len])
            
            # Add appearance to scan response if provided
            if appearance_field:
                space_remaining = 31 - len(resp_data)
                if len(appearance_field) <= space_remaining:
                    resp_data.extend(appearance_field)
            
            # For main adv_data, add shortened name only if space permits (for passive scanners)
            space_remaining = 31 - len(adv_data) - 2  # -2 for name header (len + type)
            if space_remaining > 0:
                short_name_len = min(name_len, space_remaining)
                if short_name_len > 0:
                    adv_data.append(short_name_len + 1)
                    # Use 0x08 (Shortened Local Name) since full name is in scan response
                    adv_data.append(0x08 if short_name_len < len(name_bytes) else 0x09)
                    adv_data.extend(name_bytes[:short_name_len])
            
            # Validate final size
            if len(adv_data) > 31:
                self.logger.error(f"Advertisement data too large: {len(adv_data)} bytes (max 31)")
                return False
            
            self.logger.debug(f"Advertisement: {len(adv_data)} bytes (flags={3}, "
                            f"service_data={len(service_data_field)}, "
                            f"service_uuid={len(service_uuid_field)}, "
                            f"manufacturer={len(manufacturer_field)}, "
                            f"name={len(adv_data) - 3 - len(service_data_field) - len(service_uuid_field) - len(manufacturer_field)})")
            
            # Start advertising with scan response for full name
            # gap_advertise(interval_us, adv_data, resp_data, connectable)
            # Different MicroPython builds have different signatures
            resp = bytes(resp_data) if resp_data else None
            try:
                # Try positional first (older builds)
                if resp:
                    self.ble.gap_advertise(interval_us, bytes(adv_data), resp)
                else:
                    self.ble.gap_advertise(interval_us, bytes(adv_data))
            except TypeError:
                # Fallback to keyword-only (newer builds)
                self.ble.gap_advertise(interval_us, bytes(adv_data), resp_data=resp)
            
            # Track advertising state for restart after GATT registration
            self.adv_active = True
            self.adv_params = {
                'name': name,
                'services': services,
                'appearance': appearance,
                'interval_us': interval_us,
                'manufacturer_data': manufacturer_data,
                'service_data': service_data
            }
            
            # Log with full name in scan response, shortened name in adv
            adv_name = name[:min(name_len, 31 - len(adv_data))] if len(adv_data) < 31 else ""
            self.logger.info(f"Advertising as '{name}' (adv={len(adv_data)}b, resp={len(resp_data)}b)")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start advertising: {e}")
            return False
    
    def stop_advertising(self):
        """
        Stop BLE advertising.

        Returns:
            bool: True if advertising stopped successfully, False otherwise.
        """
        if not self.adv_active:
            # Already stopped; avoid calling into NimBLE unnecessarily.
            return True
        try:
            self.ble.gap_advertise(None)  # Stop advertising
            self.adv_active = False
            # Small delay to let NimBLE release advertising resources
            time.sleep_ms(30)
            self.logger.info("Advertising stopped")
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop advertising: {e}")
            return False
    
    def _restart_advertising(self):
        """
        Restart advertising with previously saved parameters.
        
        Used internally after GATT service registration.
        """
        if self.adv_params:
            self.start_advertising(**self.adv_params)
    
    def connect(self, addr, addr_type=0, timeout_ms=5000, callback=None):
        """
        Initiate connection to a specific BLE device.

        Connection is asynchronous - result delivered via callback.
        Only one connection at a time is supported.

        Args:
            addr (bytes or str): MAC address as bytes or formatted string.
            addr_type (int): Address type (0=public, 1=random).
            timeout_ms (int): Connection timeout in milliseconds.
            callback (callable, optional): Callback(conn_handle, addr_type, addr) on success.

        Returns:
            bool: True if connection initiated, False if already connected/connecting.
        """
        if isinstance(addr, str):
            addr = self.parse_address(addr)
        
        with self.lock:
            if self.state not in (STATE_IDLE, STATE_SCANNING):
                self.logger.warning("Cannot connect in state {}".format(self.state))
                return False
            
            self.connect_callback = callback
            self.state = STATE_CONNECTING
        
        # Stop scanning if active
        if self.scan_active:
            self.stop_scan()
        
        try:
            self.ble.gap_connect(addr_type, addr, timeout_ms)
            addr_str = self.format_address(addr)
            self.logger.info("Connecting to {}...".format(addr_str))
            return True
        except Exception as e:
            self.logger.error("Failed to connect: {}".format(e))
            with self.lock:
                self.state = STATE_IDLE
            return False
    
    def disconnect(self):
        """
        Disconnect from the connected device.

        Returns:
            bool: True if disconnect initiated, False if not connected.
        """
        with self.lock:
            if self.state != STATE_CONNECTED or self.conn_handle is None:
                return False
            conn_handle = self.conn_handle
            self.state = STATE_DISCONNECTING
        
        try:
            self.ble.gap_disconnect(conn_handle)
            self.logger.info("Disconnecting...")
            return True
        except Exception as e:
            self.logger.error(f"Failed to disconnect: {e}")
            with self.lock:
                self.state = STATE_CONNECTED  # Revert state
            return False
    
    def reset_connection_state(self):
        """
        Force reset all connection state to idle.
        
        Use this to recover from failed connections or stuck states.
        Does NOT disconnect active connections - call disconnect() first if needed.
        """
        with self.lock:
            self.conn_handle = None
            self.connected_addr = None
            self.char_handle = None
            self._pending_connect = None
            self._service_start_handle = None
            self._service_end_handle = None
            self.negotiated_mtu = 23  # Reset to default MTU
            if self.state != STATE_SCANNING:
                self.state = STATE_IDLE
        self.logger.debug("Connection state reset to idle")
    
    def is_connected(self):
        """
        Check if connected to a device.

        Returns:
            bool: True if connected, False otherwise.
        """
        # NOTE: Avoid lock here - can cause deadlock with IRQ handlers
        # State and conn_handle reads are atomic on ESP32
        return self.state == STATE_CONNECTED and self.conn_handle is not None
    
    def get_state(self):
        """
        Get current connection state (STATE_* constant).

        Returns:
            int: Current state constant.
        """
        # NOTE: Avoid lock here - can cause deadlock with IRQ handlers
        # State read is atomic on ESP32
        return self.state
    
    def write_data(self, data, wait_for_response=True):
        """
        Write data to the connected device's characteristic.

        Must be connected and characteristic handle must be set.
        Higher-level modules should configure service/char UUIDs and
        perform service discovery before calling this.

        Args:
            data (bytes): Bytes to write.
            wait_for_response (bool): Wait for write confirmation.

        Returns:
            bool: True if write initiated, False if not connected or no char handle.
        """
        logger.debug("[BT] write_data: {} bytes, wait={}".format(len(data), wait_for_response))
        
        conn_handle = None
        char_handle = None
        
        # Check if lock is available (non-blocking check)
        logger.debug("[BT] write_data: attempting to acquire lock...")
        acquired = self.lock.acquire(False)  # Non-blocking acquire
        if not acquired:
            logger.debug("[BT] write_data: LOCK HELD BY ANOTHER - cannot proceed!")
            return False
        
        try:
            logger.debug("[BT] write_data: lock acquired, checking state...")
            if self.state != STATE_CONNECTED or self.char_handle is None:
                self.logger.warning("Cannot write: not connected or no characteristic")
                logger.debug("[BT] write_data: FAILED - state={}, char_handle={}".format(self.state, self.char_handle))
                return False
            conn_handle = self.conn_handle
            char_handle = self.char_handle
        finally:
            self.lock.release()
            logger.debug("[BT] write_data: lock released")
        
        logger.debug("[BT] write_data: conn_handle={}, char_handle={}".format(conn_handle, char_handle))
        
        try:
            mode = 1 if wait_for_response else 0  # 1=write with response, 0=write no response
            logger.debug("[BT] write_data: calling gattc_write with mode={}".format(mode))
            result = self.ble.gattc_write(conn_handle, char_handle, data, mode)
            logger.debug("[BT] write_data: gattc_write returned {}".format(result))
            return True
        except OSError as e:
            logger.debug("[BT] write_data: OSError: {} (errno={})".format(e, getattr(e, 'errno', 'N/A')))
            self.logger.error(f"Write failed (OSError): {e}")
            return False
        except Exception as e:
            logger.debug("[BT] write_data: EXCEPTION: {} ({})".format(e, type(e).__name__))
            self.logger.error(f"Write failed: {e}")
            return False
    
    def read_data(self):
        """
        Read data from the connected device's characteristic.

        Result delivered asynchronously via data_callback.

        Returns:
            bool: True if read initiated, False if not connected.
        """
        with self.lock:
            if self.state != STATE_CONNECTED or self.char_handle is None:
                self.logger.warning("Cannot read: not connected or no characteristic")
                return False
            conn_handle = self.conn_handle
            char_handle = self.char_handle
        
        try:
            self.ble.gattc_read(conn_handle, char_handle)
            return True
        except Exception as e:
            self.logger.error(f"Read failed: {e}")
            return False
    
    def set_data_callback(self, callback):
        """
        Set callback for received data (read results and notifications).

        Args:
            callback (callable): Function(data) called when data received.
        """
        self.data_callback = callback
    
    def set_disconnect_callback(self, callback):
        """
        Set callback for disconnection events.

        Args:
            callback (callable): Function(conn_handle, addr_type, addr) called on disconnect.
        """
        self.disconnect_callback = callback
    
    def process_pending(self):
        """
        Process pending callbacks that were deferred from IRQ context.
        
        Call this regularly from main loop to handle deferred operations
        like connection callbacks and data callbacks that can't run in IRQ context.
        
        CRITICAL: All BLE data callbacks are now deferred here to avoid
        exceeding MicroPython's shallow stack limit (~50 frames).
        
        Returns:
            bool: True if any pending operations were processed.
        """
        processed = False
        
        # Debug: log queue sizes to detect stuck state
        client_q = len(self._pending_client_data)
        server_q = len(self._pending_server_data)
        if client_q > 0 or server_q > 0:
            logger.debug(f"[BT] process_pending: client_q={client_q}, server_q={server_q}")
        
        # Process pending connection callback
        pending = None
        with self.lock:
            if self._pending_connect:
                pending = self._pending_connect
                self._pending_connect = None
        
        if pending and self.connect_callback:
            processed = True
            conn_handle, addr_type, addr_bytes = pending
            self.logger.info("Connected to {}".format(self.format_address(addr_bytes)))
            try:
                self.connect_callback(conn_handle, addr_type, addr_bytes)
            except Exception as e:
                logger.debug("[BT] process_pending: callback error: {}".format(e))
                self.logger.error(f"Connect callback error: {e}")
        
        # Process pending server data (writes from central)
        # Process ALL queued items to avoid lag
        while self._pending_server_data:
            processed = True
            conn_handle, data = self._pending_server_data.pop(0)
            if self.server_data_callback:
                try:
                    self.server_data_callback(conn_handle, data)
                except Exception as e:
                    logger.debug("[BT] process_pending: server_data_callback error: {}".format(e))
                    self.logger.error(f"Server data callback error: {e}")
        
        # Process pending client data (notifications from server)
        while self._pending_client_data:
            processed = True
            data = self._pending_client_data.pop(0)
            if self.data_callback:
                try:
                    self.data_callback(data)
                except Exception as e:
                    logger.debug("[BT] process_pending: data_callback error: {}".format(e))
                    self.logger.error(f"Data callback error: {e}")
        
        # Process pending disconnect
        pending_dc = None
        with self.lock:
            if self._pending_disconnect:
                pending_dc = self._pending_disconnect
                self._pending_disconnect = None
        
        if pending_dc and self.disconnect_callback:
            processed = True
            conn_handle, addr_type, addr_bytes = pending_dc
            try:
                self.disconnect_callback(conn_handle, addr_type, addr_bytes)
            except Exception as e:
                logger.debug("[BT] process_pending: disconnect_callback error: {}".format(e))
                self.logger.error(f"Disconnect callback error: {e}")
        
        return processed
    
    def device_count(self):
        """
        Get the number of tracked devices.

        Returns:
            int: Number of tracked devices.
        """
        with self.lock:
            return len(self.devices)
    
    def get_connection_info(self):
        """
        Get current connection information.

        Returns:
            dict or None: Dict with conn_handle, addr, state, or None if not connected.
        """
        with self.lock:
            if self.state == STATE_CONNECTED and self.conn_handle is not None:
                return {
                    'conn_handle': self.conn_handle,
                    'addr': self.connected_addr,
                    'addr_str': self.format_address(self.connected_addr),
                    'state': self.state
                }
            return None
    
    def deinit(self):
        """
        Shutdown Bluetooth manager and cleanup resources.

        Stops scanning, disconnects active connection, deactivates radio.
        Call this before destroying the BluetoothManager instance.
        """
        self.logger.info("Shutting down BluetoothManager...")
        
        if self.scan_active:
            self.stop_scan()
        
        if self.server_running:
            self.stop_gatt_server()
        
        if self.is_connected():
            self.disconnect()
            time.sleep_ms(100)  # Give disconnect time to complete
        
        self.ble.active(False)
        self.logger.info("Bluetooth deactivated")
    
    # ========== GATT Server Methods ==========
    
    def setup_gatt_server(self, service_uuid, char_uuid, char_flags=None):
        """
        Register a GATT service and characteristic for incoming connections.
        
        This allows the badge to act as a peripheral (server) that accepts
        connections from other badges acting as centrals (clients).
        
        Note: GATT services must be registered when BLE is not actively
        advertising or scanning. This method will temporarily stop those
        operations if needed.
        
        Args:
            service_uuid (bluetooth.UUID): Service UUID to register.
            char_uuid (bluetooth.UUID): Characteristic UUID for data exchange.
            char_flags (int, optional): Characteristic flags. Default: READ|WRITE|NOTIFY.
        
        Returns:
            bool: True if server started successfully.
        
        Example:
            bt.setup_gatt_server(
                bluetooth.UUID("CC140001-..."),
                bluetooth.UUID("CC140002-...")
            )
        """
        if self.server_running:
            self.logger.warning("GATT server already running")
            return True
        
        if char_flags is None:
            # Default: readable, writable, and can notify
            char_flags = bluetooth.FLAG_READ | bluetooth.FLAG_WRITE | bluetooth.FLAG_NOTIFY
        
        # Must stop advertising/scanning before registering GATT services
        # ESP32 returns error 16 (ESP_ERR_INVALID_STATE) otherwise
        was_advertising = self.adv_active
        was_scanning = self.scan_active
        
        if was_advertising:
            self.stop_advertising()
        if was_scanning:
            self.stop_scan()
        
        try:
            # Define service with single characteristic
            service_def = (service_uuid, ((char_uuid, char_flags),))
            
            logger.debug("[BT] setup_gatt_server: registering services...")
            # Register services - returns tuple of tuples of handles
            # ((service_handle, (char_handle,)),)
            handles = self.ble.gatts_register_services((service_def,))
            logger.debug("[BT] setup_gatt_server: handles={}".format(handles))
            
            # Extract handles from nested structure
            # handles = ((char_value_handle,),) for our single service/char
            self.server_service_handle = handles[0]
            self.server_char_handle = handles[0][0]
            
            # Set buffer size to allow larger writes (default is 20 bytes)
            # Must be called AFTER registering services
            # 128 bytes is sufficient for all game messages (largest ~35 bytes with HMAC)
            self.ble.gatts_set_buffer(self.server_char_handle, 128)
            logger.debug("[BT] setup_gatt_server: set buffer size to 128 bytes")
            
            self.server_running = True
            logger.debug("[BT] setup_gatt_server: server_char_handle={}".format(self.server_char_handle))
            self.logger.info(f"GATT server started, char_handle={self.server_char_handle}")
            
            # Restore advertising if it was active (now with GATT services registered)
            if was_advertising:
                self._restart_advertising()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup GATT server: {e}")
            # Try to restore advertising even on failure
            if was_advertising:
                self._restart_advertising()
            return False
    
    def stop_gatt_server(self):
        """
        Stop the GATT server and disconnect any connected centrals.
        
        Returns:
            bool: True if stopped successfully.
        """
        if not self.server_running:
            return True
        
        # Disconnect all connected centrals
        for conn_handle in list(self.server_connections.keys()):
            try:
                self.ble.gap_disconnect(conn_handle)
            except Exception:
                pass
        
        self.server_connections.clear()
        self.server_running = False
        self.server_char_handle = None
        self.server_service_handle = None
        
        self.logger.info("GATT server stopped")
        return True
    
    def is_server_running(self):
        """
        Check if GATT server is active.
        
        Returns:
            bool: True if server is running.
        """
        return self.server_running
    
    def get_server_connections(self):
        """
        Get list of connected centrals.
        
        Returns:
            list: List of (conn_handle, addr_bytes) tuples.
        """
        with self.lock:
            return list(self.server_connections.items())
    
    def server_notify(self, data, conn_handle=None):
        """
        Send notification to connected central(s).
        
        This is how the server (target badge) responds to the client (challenger).
        
        Args:
            data (bytes): Data to send.
            conn_handle (int, optional): Specific connection. None = all connections.
        
        Returns:
            bool: True if notification sent successfully.
        """
        if not self.server_running or self.server_char_handle is None:
            self.logger.warning("Server not running or no characteristic")
            return False
        
        try:
            if conn_handle is not None:
                # Send to specific connection
                self.ble.gatts_notify(conn_handle, self.server_char_handle, data)
            else:
                # Send to all connected centrals
                with self.lock:
                    connections = list(self.server_connections.keys())
                for ch in connections:
                    try:
                        self.ble.gatts_notify(ch, self.server_char_handle, data)
                    except Exception as e:
                        self.logger.warning(f"Notify failed for conn {ch}: {e}")
            return True
            
        except Exception as e:
            self.logger.error(f"Server notify failed: {e}")
            return False
    
    def set_server_data_callback(self, callback):
        """
        Set callback for data received via GATT server writes.
        
        Args:
            callback (callable): Function(conn_handle, data) called on incoming write.
        """
        self.server_data_callback = callback
    
    def _handle_central_connect(self, conn_handle, addr_type, addr):
        """
        Handle central connecting to our GATT server.
        
        Enforces max_server_connections limit (1 for badges, more for stations).
        If at capacity, immediately disconnects the new connection.
        
        Args:
            conn_handle (int): Connection handle.
            addr_type (int): Address type.
            addr (bytes): Central's MAC address.
        """
        addr_bytes = bytes(addr)
        addr_str = self.format_address(addr_bytes)
        
        # NOTE: No lock here - IRQ handlers must not block
        # Enforce connection limit (badges = 1, stations can be higher)
        if len(self.server_connections) >= self.max_server_connections:
            self.logger.warning(f"Rejecting connection from {addr_str}: at capacity ({self.max_server_connections})")
            try:
                self.ble.gap_disconnect(conn_handle)
            except Exception as e:
                self.logger.error(f"Failed to disconnect excess connection: {e}")
            return
        
        self.server_connections[conn_handle] = addr_bytes
        
        # Also track in general connection state if not already connected as client
        if self.conn_handle is None:
            self.conn_handle = conn_handle
            self.connected_addr = addr_bytes
            self.state = STATE_CONNECTED
        
        self.logger.info(f"Central connected: {addr_str} (handle={conn_handle})")
    
    def _handle_central_disconnect(self, conn_handle, addr_type, addr):
        """
        Handle central disconnecting from our GATT server.
        
        Args:
            conn_handle (int): Connection handle.
            addr_type (int): Address type.
            addr (bytes): Central's MAC address.
        """
        addr_bytes = bytes(addr)  # Copy memoryview before it becomes invalid
        addr_str = self.format_address(addr_bytes)
        
        # NOTE: No lock here - IRQ handlers must not block
        if conn_handle in self.server_connections:
            del self.server_connections[conn_handle]
        
        # Update general state if this was our tracked connection
        if self.conn_handle == conn_handle:
            self.conn_handle = None
            self.connected_addr = None
            self.state = STATE_IDLE
        
        self.logger.info(f"Central disconnected: {addr_str}")
        
        # DEFER callback to process_pending() - avoid stack overflow in IRQ
        if self.disconnect_callback:
            self._pending_disconnect = (conn_handle, addr_type, addr_bytes)
    
    def _handle_gatts_write(self, conn_handle, attr_handle):
        """
        Handle incoming write to our GATT characteristic.
        
        DEFERS data callback to process_pending() to avoid stack overflow.
        MicroPython IRQ stack is shallow - callbacks must be deferred.
        
        Args:
            conn_handle (int): Connection handle of writer.
            attr_handle (int): Attribute handle that was written.
        """
        logger.debug("[BT-SERVER] _handle_gatts_write: conn={}, attr={}, server_char={}".format(
            conn_handle, attr_handle, self.server_char_handle))
        
        if attr_handle != self.server_char_handle:
            logger.debug("[BT-SERVER] _handle_gatts_write: wrong attr_handle, ignoring")
            return
        
        # Read the written data
        try:
            data = self.ble.gatts_read(attr_handle)
            logger.debug("[BT-SERVER] _handle_gatts_write: read {} bytes".format(len(data)))
            self.logger.debug(f"GATTS write received: {len(data)} bytes")
            
            # DEFER callback to process_pending() - avoid stack overflow in IRQ
            # Queue the data for processing in main loop
            if self.server_data_callback:
                self._pending_server_data.append((conn_handle, bytes(data)))
                logger.debug("[BT-SERVER] _handle_gatts_write: queued for process_pending")
                    
        except Exception as e:
            self.logger.error(f"Failed to read GATTS write: {e}")
