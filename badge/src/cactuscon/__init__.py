"""CactusCon14 Badge Firmware Package.

Modules are NOT re-exported here to enable lazy loading and reduce RAM usage.

Use explicit imports:
    from cactuscon.application import BadgeApplication
    from cactuscon.prefs import prefs
    from cactuscon.hw.bluetooth import BluetoothManager
    from cactuscon.hw.wifi import WiFiManager
    from cactuscon.hw.screen import TFT
    from cactuscon.game.battle_manager import BattleManager
    from cactuscon.game.comms import GameBTComms
    from cactuscon.ui.graphics import GameUI
    etc.

Panels are loaded on-demand via GameUI.show_panel('panel_name').
"""

# Only re-export config since it's needed everywhere and is lightweight
try:
    from config import BadgeConfig, config
except ImportError:
    import sys
    sys.path.insert(0, '..')
    from config import BadgeConfig, config
