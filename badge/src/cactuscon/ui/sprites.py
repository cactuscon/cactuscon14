"""LVGL sprite system - Sprite loading and animation."""

import uos
import lvgl as lv
import time
import framebuf
import math
import os
import gc

from cactuscon.utils import Logger, gc_if_needed
from cactuscon.ui.image_utils import (
    load_rgb565_file,
    load_rgb565_single_frame,
)
from cactuscon import config

logger = Logger(config.LOG_LEVEL)

_SPRITE_CACHE = {}


def _touch_cache_entry(path):
    entry = _SPRITE_CACHE.get(path)
    if entry:
        entry["last_used"] = time.ticks_ms()
    return entry


def get_cached_sprite(path):
    entry = _SPRITE_CACHE.get(path)
    if entry:
        entry["last_used"] = time.ticks_ms()
        logger.debug(f"[SPRITE_CACHE] HIT: {path} ({len(entry['buf'])} bytes)")
        return entry["buf"]
    logger.debug(f"[SPRITE_CACHE] MISS: {path} (cache has {len(_SPRITE_CACHE)} entries)")
    return None


def put_cached_sprite(path, sheet_buf):
    """
    Add sprite to cache, enforcing limits on non-essential sprites.
    
    Protected sprites (stations + player evo tree) are always cached.
    Non-protected sprites are limited by MAX_UNPROTECTED_CACHE_ENTRIES 
    and MAX_UNPROTECTED_CACHE_BYTES.
    """
    is_protected = path in _PROTECTED_PATHS or path in _PRELOADED_PATHS
    new_size = len(sheet_buf)
    
    # For non-protected sprites, enforce cache limits
    if not is_protected:
        if gc.mem_free() < MEMORY_PRESSURE_THRESHOLD_BYTES:
            on_memory_pressure()
        count, total_bytes = _count_unprotected_cache()
        
        # Evict until we have room
        while count >= MAX_UNPROTECTED_CACHE_ENTRIES or total_bytes + new_size > MAX_UNPROTECTED_CACHE_BYTES:
            freed = _evict_oldest_unprotected()
            if freed == 0:
                break  # No more to evict
            total_bytes -= freed
            count -= 1
    
    _SPRITE_CACHE[path] = {"buf": sheet_buf, "last_used": time.ticks_ms(), "size": new_size}
    logger.debug(f"[SPRITE_CACHE] PUT: {path} ({new_size} bytes, now {len(_SPRITE_CACHE)} entries)")


_PRELOADED_PATHS = set()

# Maximum number of non-essential (unprotected) sprites to keep cached
# Essential sprites (stations + player evo tree) don't count toward this limit
MAX_UNPROTECTED_CACHE_ENTRIES = 4  # ~200KB at ~50KB per sprite
MAX_UNPROTECTED_CACHE_BYTES = config.MAX_SPRITE_CACHE_BYTES  # Configurable limit for non-essential sprites
MEMORY_PRESSURE_THRESHOLD_BYTES = int(
    getattr(config, "SPRITE_MEMORY_PRESSURE_THRESHOLD_BYTES", 80 * 1024)
)
MEMORY_PRESSURE_CACHE_ENTRIES = int(
    getattr(config, "SPRITE_MEMORY_PRESSURE_CACHE_ENTRIES", 2)
)


def on_memory_pressure():
    """Tighten cache policy and evict stale sprites when free memory is low."""
    global MAX_UNPROTECTED_CACHE_ENTRIES
    MAX_UNPROTECTED_CACHE_ENTRIES = max(1, MEMORY_PRESSURE_CACHE_ENTRIES)
    evict_sprite_cache(keep_paths=None, min_free_percent=None, preserve_preloaded=True)


def _count_unprotected_cache():
    """Count non-protected cache entries and their total size."""
    count = 0
    total_bytes = 0
    for path, entry in _SPRITE_CACHE.items():
        if path not in _PROTECTED_PATHS and path not in _PRELOADED_PATHS:
            count += 1
            total_bytes += entry.get("size", 0)
    return count, total_bytes


def _evict_oldest_unprotected():
    """Evict the oldest non-protected sprite from cache. Returns bytes freed."""
    oldest_path = None
    oldest_time = None
    
    for path, entry in _SPRITE_CACHE.items():
        if path in _PROTECTED_PATHS or path in _PRELOADED_PATHS:
            continue
        last_used = entry.get("last_used", 0)
        if oldest_time is None or last_used < oldest_time:
            oldest_time = last_used
            oldest_path = path
    
    if oldest_path:
        freed = _SPRITE_CACHE[oldest_path].get("size", 0)
        logger.debug(f"[SPRITE_CACHE] EVICT (cache limit): {oldest_path} ({freed} bytes)")
        del _SPRITE_CACHE[oldest_path]
        return freed
    return 0


def evict_sprite_cache(keep_paths=None, max_age_ms=None, min_free_percent=20, preserve_preloaded=True):
    """
    Intelligently evict stale sprites based on memory pressure.
    
    Default behavior is conservative - only evict when memory is tight.
    - keep_paths: iterable of paths to keep
    - max_age_ms: if set, also evict entries unused for this long (default: no age-based eviction)
    - min_free_percent: only evict if free memory falls below this % of total (default: 20%)
                       e.g., min_free_percent=20 means "if free < 20%, start evicting"
                       Set to None to disable memory-based eviction entirely.
    - preserve_preloaded: if True, never evict preloaded/protected sprites unless memory is critically low
    
    Returns:
        dict: {'removed': int, 'freed_bytes': int, 'free_percent': float}
    """
    keep = set(keep_paths or [])
    
    # Always preserve preloaded character sprites unless memory is critical
    if preserve_preloaded:
        keep.update(_PRELOADED_PATHS)
        # Also protect station + player evo tree sprites
        keep.update(_PROTECTED_PATHS)
    
    # Calculate current memory pressure
    cache_mem = sum((entry.get("size", 0) for entry in _SPRITE_CACHE.values()), 0)
    total_mem = gc.mem_free() + cache_mem
    free_now = gc.mem_free()
    free_percent = (free_now / total_mem * 100) if total_mem > 0 else 100
    
    # Early exit if memory is healthy
    if min_free_percent is not None and free_percent >= min_free_percent:
        logger.debug(f"[SPRITE_CACHE] Memory healthy ({free_percent:.1f}% free), no eviction needed")
        return {'removed': 0, 'freed_bytes': 0, 'free_percent': free_percent}
    
    now = time.ticks_ms()
    removed = 0
    freed_bytes = 0
    
    if min_free_percent is not None and free_percent < min_free_percent:
        logger.info(f"[SPRITE_CACHE] Memory pressure ({free_percent:.1f}% free < {min_free_percent}%), starting eviction")
        
        # Evict stale raw sprite data (oldest first, except keep list)
        items = [
            (path, entry.get("last_used", 0), entry.get("size", 0))
            for path, entry in _SPRITE_CACHE.items()
            if path not in keep
        ]
        items.sort(key=lambda x: x[1])  # oldest first
        
        for path, _, size in items:
            if gc.mem_free() / total_mem * 100 >= min_free_percent:
                break
            logger.debug(f"[SPRITE_CACHE] EVICT (memory pressure): {path} ({size} bytes)")
            _SPRITE_CACHE.pop(path, None)
            freed_bytes += size
            removed += 1
    
    # If max_age_ms is specified, also evict old entries regardless of memory pressure
    if max_age_ms is not None:
        for path in list(_SPRITE_CACHE.keys()):
            if path in keep:
                continue
            entry = _touch_cache_entry(path)
            if not entry:
                continue
            age = time.ticks_diff(now, entry.get("last_used", now))
            if age > max_age_ms:
                size = entry.get("size", 0)
                logger.debug(f"[SPRITE_CACHE] EVICT (age={age}ms > {max_age_ms}ms): {path}")
                _SPRITE_CACHE.pop(path, None)
                freed_bytes += size
                removed += 1
    
    if removed > 0:
        gc_if_needed(force=True)
        free_after = gc.mem_free()
        free_percent_after = (free_after / total_mem * 100) if total_mem > 0 else 100
        logger.info(f"[SPRITE_CACHE] Evicted {removed} items, freed {freed_bytes:,} bytes, free now {free_percent_after:.1f}%")
    
    return {'removed': removed, 'freed_bytes': freed_bytes, 'free_percent': free_percent}


# Fallback station character IDs used if station registry cannot be queried.
STATION_CHARACTER_IDS = [
    'enigmox',      # Enigmox Gym (EASY)
    'hackachu',     # Hackachu Gym (MEDIUM)
    'voltreign',    # Voltreign Gym (HARD)
    'cinderserp',   # Cinderserp Gym (MEDIUM)
    'runewing',     # Runewing Gym (HARD)
]

# Protected paths that should never be evicted (station sprites + player's active evo tree)
_PROTECTED_PATHS = set()

# Current player's evolution tree genus (to detect changes)
_CURRENT_PLAYER_GENUS = None


def get_evolution_tree_sprite_paths(char_id):
    """
    Get sprite paths for all forms in a character's evolution tree.
    
    Args:
        char_id: Any character ID in the evolution line.
        
    Returns:
        list[str]: Sprite paths for all forms in the evolution tree (up to 3).
    """
    # Import here to avoid circular dependency
    from cactuscon.game.engine.characters import get_evolution_tree
    
    forms = get_evolution_tree(char_id)
    paths = []
    for form in forms:
        sprite_path = form.get('sprite_path')
        if sprite_path:
            paths.append(sprite_path)
    return paths


def get_station_sprite_paths():
    """
    Get sprite paths for all station creatures.
    
    Returns:
        list[str]: Sprite paths for station creatures.
    """
    # Import here to avoid circular dependency
    from cactuscon.game.engine.characters import get_character
    from cactuscon.game.engine.stations import get_station_character_ids

    paths = []
    station_character_ids = []
    try:
        station_character_ids = get_station_character_ids(include_default=False)
    except Exception:
        station_character_ids = []
    if not station_character_ids:
        station_character_ids = STATION_CHARACTER_IDS

    for char_id in station_character_ids:
        char = get_character(char_id)
        if char and hasattr(char, 'sprite_path') and char.sprite_path:
            paths.append(char.sprite_path)
    return paths


def _update_protected_paths(player_char_id=None):
    """
    Update the set of protected sprite paths.
    
    Protected paths include:
    - All station creature sprites (5 creatures)
    - Player's active evolution tree sprites (up to 3 creatures)
    - All achievement icon sprites
    
    Args:
        player_char_id: Player's current character ID (any form in their evo tree).
    """
    global _PROTECTED_PATHS
    
    _PROTECTED_PATHS = set()
    
    # Always protect station sprites
    for path in get_station_sprite_paths():
        _PROTECTED_PATHS.add(path)
    
    # Protect player's evolution tree
    if player_char_id:
        for path in get_evolution_tree_sprite_paths(player_char_id):
            _PROTECTED_PATHS.add(path)
    
    # Protect achievement icons (only if they exist - won't be present until OTA updates include them)
    try:
        from cactuscon.game.engine.achievements import get_achievement_icon_paths
        for path in get_achievement_icon_paths():
            # Only add if file exists; icons will load on-demand when earned
            try:
                os.stat(path)
                _PROTECTED_PATHS.add(path)
            except OSError:
                pass  # File not yet deployed via OTA
    except ImportError:
        pass  # achievements module may not be available
    
    logger.debug(f"[SPRITE_CACHE] Protected paths updated: {len(_PROTECTED_PATHS)} sprites")


def preload_essential_sprites(player_char_id=None, progress_callback=None):
    """
    Preload only essential sprites: station creatures + player's evolution tree.
    
    This dramatically reduces memory usage compared to preloading all 15 sprites.
    Only loads ~8 sprites max (5 stations + 3 player evo forms, with overlap).
    
    Args:
        player_char_id: Player's current character ID for evo tree loading.
        progress_callback: Optional callback(current, total, path) for progress updates.
        
    Returns:
        dict: {
            'raw_loaded': int,
            'raw_failed': int,
            'raw_bytes': int,
            'total_time_ms': int,
        }
    """
    global _PRELOADED_PATHS, _CURRENT_PLAYER_GENUS
    
    import time as time_module
    from cactuscon.game.engine.characters import get_genus_for_character
    
    start_time = time_module.ticks_ms()
    
    # Update protected paths
    _update_protected_paths(player_char_id)
    
    # Track player's genus for future change detection
    if player_char_id:
        _CURRENT_PLAYER_GENUS = get_genus_for_character(player_char_id)
    
    # Collect paths to load (deduplicated)
    paths_to_load = list(_PROTECTED_PATHS)
    
    raw_loaded = 0
    raw_failed = 0
    raw_bytes = 0
    
    total_raw = len(paths_to_load)
    
    logger.info(f"[SPRITE_CACHE] Preloading {total_raw} essential sprites (stations + player evo + achievement icons)")
    
    for i, path in enumerate(paths_to_load):
        if progress_callback:
            try:
                progress_callback(i, total_raw, path)
            except Exception:
                pass
        
        # Skip if already cached
        if get_cached_sprite(path):
            _PRELOADED_PATHS.add(path)
            raw_loaded += 1
            continue
        
        try:
            # Load the raw sprite data
            data = load_rgb565_file(path)
            if data:
                put_cached_sprite(path, data)
                _PRELOADED_PATHS.add(path)
                raw_loaded += 1
                raw_bytes += len(data)
                logger.debug(f"[PRELOAD] Sprite: {path} ({len(data)} bytes)")
            else:
                raw_failed += 1
                logger.warning(f"[PRELOAD] Failed to load sprite: {path}")
        except Exception as e:
            raw_failed += 1
            logger.warning(f"[PRELOAD] Error loading sprite {path}: {e}")
        
        gc_if_needed(force=True)
    
    total_time = time_module.ticks_diff(time_module.ticks_ms(), start_time)
    logger.info(f"[SPRITE_CACHE] Preload complete in {total_time}ms: {raw_loaded} sprites, {raw_bytes:,} bytes")
    
    return {
        'raw_loaded': raw_loaded,
        'raw_failed': raw_failed,
        'raw_bytes': raw_bytes,
        'total_time_ms': total_time,
    }


def switch_player_creature_cache(new_char_id):
    """
    Switch sprite cache when player changes to a different evolution tree.
    
    - If new creature is in the same evolution tree, no action needed.
    - If new creature is in a different tree:
      - Evict old tree sprites (except those used by stations)
      - Load new tree sprites into cache
    
    Args:
        new_char_id: The new character ID the player is switching to.
        
    Returns:
        dict: {'evicted': int, 'loaded': int, 'same_tree': bool}
    """
    global _CURRENT_PLAYER_GENUS, _PRELOADED_PATHS, _PROTECTED_PATHS
    
    from cactuscon.game.engine.characters import get_genus_for_character
    
    new_genus = get_genus_for_character(new_char_id)
    
    # If same evolution tree, nothing to do
    if new_genus == _CURRENT_PLAYER_GENUS:
        logger.debug(f"[SPRITE_CACHE] Same evolution tree ({new_genus}), no cache change needed")
        return {'evicted': 0, 'loaded': 0, 'same_tree': True}
    
    logger.info(f"[SPRITE_CACHE] Player creature change: {_CURRENT_PLAYER_GENUS} -> {new_genus}")
    
    # Get old tree paths (to potentially evict)
    old_tree_paths = set()
    if _CURRENT_PLAYER_GENUS:
        # Get any char from old genus to get the tree
        from cactuscon.game.engine.characters import get_evolution_index
        old_tree = get_evolution_index().get(_CURRENT_PLAYER_GENUS, [])
        for char in old_tree:
            if hasattr(char, 'sprite_path') and char.sprite_path:
                old_tree_paths.add(char.sprite_path)
    
    # Get station paths (never evict these)
    station_paths = set(get_station_sprite_paths())
    
    # Evict old tree paths that aren't station sprites
    evicted = 0
    for path in old_tree_paths:
        if path not in station_paths and path in _SPRITE_CACHE:
            logger.debug(f"[SPRITE_CACHE] Evicting old tree sprite: {path}")
            _SPRITE_CACHE.pop(path, None)
            _PRELOADED_PATHS.discard(path)
            evicted += 1
    
    if evicted > 0:
        gc_if_needed(force=True)
    
    # Update protected paths for new creature
    _update_protected_paths(new_char_id)
    _CURRENT_PLAYER_GENUS = new_genus
    
    # Load new tree sprites
    new_tree_paths = get_evolution_tree_sprite_paths(new_char_id)
    loaded = 0
    
    for path in new_tree_paths:
        if get_cached_sprite(path):
            continue  # Already cached (might be a station sprite)
        
        try:
            data = load_rgb565_file(path)
            if data:
                put_cached_sprite(path, data)
                _PRELOADED_PATHS.add(path)
                loaded += 1
                logger.debug(f"[SPRITE_CACHE] Loaded new tree sprite: {path}")
        except Exception as e:
            logger.warning(f"[SPRITE_CACHE] Failed to load {path}: {e}")
    
    if loaded > 0:
        gc_if_needed(force=True)
    
    logger.info(f"[SPRITE_CACHE] Tree switch complete: evicted {evicted}, loaded {loaded}")
    return {'evicted': evicted, 'loaded': loaded, 'same_tree': False}


# Legacy alias for backwards compatibility
CHARACTER_SPRITE_PATHS = [
    '/assets/images/sprites/hacktarchu.rgb565',
    '/assets/images/sprites/hackachu.rgb565',
    '/assets/images/sprites/hackachimon.rgb565',
    '/assets/images/sprites/voltiny.rgb565',
    '/assets/images/sprites/voltqueen.rgb565',
    '/assets/images/sprites/voltreign.rgb565',
    '/assets/images/sprites/cinderlet.rgb565',
    '/assets/images/sprites/cinderserp.rgb565',
    '/assets/images/sprites/cindervipe.rgb565',
    '/assets/images/sprites/blipbat.rgb565',
    '/assets/images/sprites/glyphbat.rgb565',
    '/assets/images/sprites/runewing.rgb565',
    '/assets/images/sprites/cipherkit.rgb565',
    '/assets/images/sprites/enigmox.rgb565',
    '/assets/images/sprites/cryptilox.rgb565',
]


def preload_character_sprites(progress_callback=None):
    """
    DEPRECATED: Use preload_essential_sprites() instead for better memory usage.
    
    This function now delegates to preload_essential_sprites with no player char,
    which loads only station sprites.
    """
    logger.warning("[SPRITE_CACHE] preload_character_sprites is deprecated, use preload_essential_sprites")
    return preload_essential_sprites(player_char_id=None, progress_callback=progress_callback)


class LVGLImage:
    """
    LVGL 9.4 compatible image loader for RGB565 sprite files.
    
    Wraps RGB565 binary files as LVGL image descriptors that can be
    displayed using lv.image() widgets. Supports grid-based sprite
    sheet layouts for frame-based animation.
    
    LVGL 9.4 uses image descriptors that point to raw pixel data in memory.
    This class handles:
    - Loading RGB565 data from disk
    - Creating proper LVGL image descriptor structures
    - Frame extraction from sprite sheets
    - Efficient memory management
    
    Usage Modes:
    
    1. Static Image (frames_per_row=None):
        # Auto-detects dimensions from file size
        static_img = LVGLImage('/assets/images/background.rgb565')
        
        # Or specify dimensions explicitly
        static_img = LVGLImage('/assets/images/logo.rgb565',
                               frame_width=320, frame_height=240)
    
    2. Sprite Sheet (frames_per_row >= 1):
        sprite_sheet = LVGLImage('/assets/images/sprites/deeno_grid.rgb565',
                                 frame_width=64,
                                 frame_height=64,
                                 frames_per_row=4,
                                 num_frames=16)
        
        # Get specific frame
        img_dsc = sprite_sheet.get_lvgl_src(frame_index=5)
    
    Display with LVGL:
        img = lv.image(parent_obj)
        img.set_src(sprite_image.get_lvgl_src())
        img.set_pos(100, 100)
    """
    
    def __init__(self, path, frame_width=None, frame_height=None, frames_per_row=None, num_frames=None, color_format=lv.COLOR_FORMAT.RGB565):
        """
        Initialize LVGL image loader.
        
        Args:
            path: Path to RGB565 binary file
            frame_width: Width of each frame in pixels (None = auto-detect from file)
            frame_height: Height of each frame in pixels (None = auto-detect from file)
            frames_per_row: Frames per row in sprite sheet (None = single static image)
            num_frames: Total frames (None = auto-calculate, 1 for static images)
            color_format: LVGL color format (default: RGB565)
        
        Color inversion is handled automatically based on display state
        via the centralized image_utils module.
        
        Static Image Mode (frames_per_row=None):
            Treats entire file as a single image. frame_width/frame_height are
            inferred from file size assuming a square-ish aspect ratio if not provided.
            
        Sprite Sheet Mode (frames_per_row >= 1):
            Validates file size against expected grid layout and extracts frames.
        """
        self.path = path
        self.color_format = color_format
        self.current_frame = 0
        # Use cached sheet if present
        embedded_data = get_cached_sprite(path)

        # Get file size to calculate dimensions
        if embedded_data is not None:
            file_bytes = len(embedded_data)
        else:
            stat = uos.stat(path)
            file_bytes = stat[6]
            
        bytes_per_pixel = 2  # RGB565
        total_pixels = file_bytes // bytes_per_pixel

        # Normalize single-frame sheets to static image mode
        if frames_per_row == 1 and (num_frames is None or num_frames == 1):
            frames_per_row = None
            num_frames = 1

        # Static image mode: frames_per_row=None means treat as single image
        if frames_per_row is None:
            # Auto-detect dimensions if not provided
            if frame_width is None or frame_height is None:
                w, h = self._auto_detect_static_dims(total_pixels)
                if w is None or h is None:
                    raise ValueError(f"Cannot auto-detect image dimensions for {file_bytes} bytes")
                self.frame_width, self.frame_height = w, h
            else:
                self.frame_width = frame_width
                self.frame_height = frame_height
            
            # Single static image
            self.frames_per_row = 1
            self.num_frames = 1
            self.frames_per_col = 1
            self.sheet_width = self.frame_width
            self.sheet_height = self.frame_height
            
            # Validate file size matches dimensions
            expected_bytes = self.sheet_width * self.sheet_height * bytes_per_pixel
            if file_bytes != expected_bytes:
                # Fallback: try auto-detection ignoring provided dimensions
                w, h = self._auto_detect_static_dims(total_pixels)
                if w is not None and h is not None:
                    self.frame_width = self.sheet_width = w
                    self.frame_height = self.sheet_height = h
                    expected_bytes = self.sheet_width * self.sheet_height * bytes_per_pixel
                if file_bytes != expected_bytes:
                    raise ValueError(
                        f"Static image file size mismatch: expected {expected_bytes} bytes, "
                        f"got {file_bytes} bytes (image {self.sheet_width}x{self.sheet_height})"
                    )
        else:
            # Sprite sheet mode: explicit grid layout
            if frame_width is None or frame_height is None:
                frame_width, frame_height = self._infer_frame_dims(total_pixels, frames_per_row, num_frames or 1)
                if frame_width is None or frame_height is None:
                    raise ValueError("Unable to infer frame dimensions for sprite sheet")
            self.frame_width = frame_width
            self.frame_height = frame_height
            self.frames_per_row = frames_per_row
            
            # If num_frames not specified, calculate from file size
            if num_frames is None:
                # Calculate how many frames fit in the file
                frame_pixels = frame_width * frame_height
                self.num_frames = total_pixels // frame_pixels if frame_pixels > 0 else 1
            else:
                self.num_frames = num_frames
            
            # Calculate actual sheet dimensions
            self.frames_per_col = (self.num_frames + self.frames_per_row - 1) // self.frames_per_row
            self.sheet_width = frame_width * frames_per_row
            self.sheet_height = frame_height * self.frames_per_col
            
            # Validate file size
            expected_bytes = self.sheet_width * self.sheet_height * bytes_per_pixel
            if file_bytes != expected_bytes:
                raise ValueError(
                    f"Sprite sheet file size mismatch: expected {expected_bytes} bytes, "
                    f"got {file_bytes} bytes (sheet {self.sheet_width}x{self.sheet_height})"
                )
        
        # Load sprite sheet into RAM
        self._from_cache = embedded_data is not None
        self._load_sheet(embedded_data)
        if self._from_cache:
            logger.debug(
                f"Sprite cache hit: {path} ({self.sheet_width}x{self.sheet_height}, {self.num_frames} frames)"
            )
        else:
            logger.info(f"Loaded LVGL image: {path} ({self.sheet_width}x{self.sheet_height}, {self.num_frames} frames)")
    
    # Helper to infer frame dimensions when only frames_per_row/num_frames are provided
    def _infer_frame_dims(self, total_pixels, frames_per_row, num_frames):
        if frames_per_row is None or num_frames is None or frames_per_row <= 0 or num_frames <= 0:
            return (None, None)
        frames_per_col = (num_frames + frames_per_row - 1) // frames_per_row
        total_cells = frames_per_row * frames_per_col
        if total_cells <= 0:
            return (None, None)
        frame_area = total_pixels // total_cells
        # Try perfect square
        side = int(math.sqrt(frame_area))
        if side * side == frame_area:
            return (side, side)
        # Try common square-ish sizes, prefer the most balanced aspect ratio
        candidates = [128, 96, 80, 72, 64]
        best_dims = None
        best_ratio = None
        for w in candidates:
            if frame_area % w != 0:
                continue
            h = frame_area // w
            ratio = max(w, h) / min(w, h)
            if best_ratio is None or ratio < best_ratio:
                best_dims = (w, h)
                best_ratio = ratio
        if best_dims:
            return best_dims
        # Last resort: use frame_area as height with width=frames_per_row?
        return (None, None)

    def _auto_detect_static_dims(self, total_pixels):
        side = int(math.sqrt(total_pixels))
        if side * side == total_pixels:
            return side, side
        for w in [320, 256, 240, 128, 64]:
            if total_pixels % w == 0:
                return w, total_pixels // w
        return (None, None)

    def _load_sheet(self, embedded_data=None):
        """Load entire sprite sheet into RAM with automatic color inversion."""
        if embedded_data is not None:
            # Reuse cached sheet buffer to avoid extra copies.
            self.sheet_buf = embedded_data
        else:
            # If explicitly single-frame with known dimensions, use lightweight loader
            if self.frames_per_row == 1 and self.num_frames == 1 and self.frame_width and self.frame_height:
                self.sheet_buf = load_rgb565_single_frame(
                    self.path, self.frame_width, self.frame_height
                )
            else:
                self.sheet_buf = load_rgb565_file(self.path)
            # Cache for reuse
            put_cached_sprite(self.path, self.sheet_buf)
            
            logger.debug(f"Loaded {len(self.sheet_buf)} bytes of sprite data into RAM")
    
    def get_frame_buffer(self, frame_index=None):
        """
        Extract single frame buffer from sprite sheet.
        
        Args:
            frame_index: Frame number (0-indexed). If None, uses current_frame.
            
        Returns:
            bytearray containing single frame in RGB565 format
        """
        if frame_index is None:
            frame_index = self.current_frame
        
        frame_index = frame_index % self.num_frames
        
        # Calculate frame position in sprite sheet grid
        x_idx = frame_index % self.frames_per_row
        y_idx = frame_index // self.frames_per_row
        
        frame_x = x_idx * self.frame_width * 2  # bytes, not pixels
        frame_y = y_idx * self.frame_height
        sheet_width_bytes = self.sheet_width * 2
        
        # Extract frame data
        frame_buf = bytearray(self.frame_width * self.frame_height * 2)
        
        for row in range(self.frame_height):
            src_offset = (frame_y + row) * sheet_width_bytes + frame_x
            dst_offset = row * self.frame_width * 2
            frame_buf[dst_offset:dst_offset + self.frame_width * 2] = \
                self.sheet_buf[src_offset:src_offset + self.frame_width * 2]
        
        return frame_buf
    
    def get_lvgl_src(self, frame_index=None):
        """
        Get LVGL image descriptor for current frame.
        
        LVGL 9.x uses lv.image_dsc_t with header containing width, height,
        and color format. This creates a proper image descriptor that can
        be passed to lv.image.set_src().
        
        Args:
            frame_index: Frame number (0-indexed). If None, uses current_frame.
            
        Returns:
            lv.image_dsc_t object that LVGL can render
        """
        frame_buf = self.get_frame_buffer(frame_index)
        
        # Create LVGL image descriptor with proper header
        # For RGB565: 2 bytes per pixel
        img_dsc = lv.image_dsc_t({
            'header': {
                'w': self.frame_width,
                'h': self.frame_height,
                'cf': lv.COLOR_FORMAT.RGB565
            },
            'data_size': len(frame_buf),
            'data': bytes(frame_buf)
        })
        
        return img_dsc
    
    def next_frame(self):
        """Advance to next frame."""
        self.current_frame = (self.current_frame + 1) % self.num_frames
    
    def set_frame(self, frame_index):
        """Set current frame by index."""
        self.current_frame = frame_index % self.num_frames
    
    def reset(self):
        """Reset to first frame."""
        self.current_frame = 0


class LVGLSpriteActor:
    """
    LVGL 9.4 compatible sprite actor for animated game characters.
    
    Manages animated character display using LVGL image widgets.
    Supports multiple named actions (idle, attack, defend, etc.)
    each with their own sprite sheet and animation timing.
    
    Usage:
        actor = LVGLSpriteActor(parent_container, x=100, y=100)
        
        # Add action sprites
        idle_sprite = LVGLImage('/assets/sprites/idle.rgb565', 64, 64, frames_per_row=4)
        attack_sprite = LVGLImage('/assets/sprites/attack.rgb565', 64, 64, frames_per_row=2)
        
        actor.add_action('idle', idle_sprite)
        actor.add_action('attack', attack_sprite)
        
        # Play action
        actor.set_action('idle')
        actor.show()
        
        # In main loop
        actor.update()  # Advance animation
    """
    
    def __init__(self, parent_container, x=0, y=0):
        """
        Initialize LVGL sprite actor.
        
        Args:
            parent_container: Parent LVGL object (e.g., screen or panel)
            x: X position in pixels
            y: Y position in pixels
        """
        self.parent = parent_container
        self.x = x
        self.y = y
        self.visible = False
        self.actions = {}  # action_name -> LVGLImage instance
        self.current_action = None
        self.animation_frame_delay = 100  # ms between frames
        self.last_frame_update = 0
        
        # Image widget for displaying sprites (created on first draw)
        self.img_obj = None
        # Keep reference to image descriptor to prevent GC
        self._current_img_dsc = None
        # Cache frame image descriptors to prevent memory fragmentation
        self._frame_dsc_cache = {}  # (action_name, frame_index) -> lv.image_dsc_t
        # Track if we're in fallback mode
        self._is_fallback = False
        
        logger.debug(f"Created LVGLSpriteActor at ({x}, {y})")
    
    def add_action(self, name, sprite_image):
        """
        Register a named action sprite.
        
        Args:
            name: Action name (e.g., 'idle', 'attack', 'defend')
            sprite_image: LVGLImage instance for this action
        """
        self.actions[name] = sprite_image
        
        # Pre-cache all frame descriptors for this action to prevent
        # memory fragmentation during animation
        for frame_idx in range(sprite_image.num_frames):
            self._get_cached_frame_dsc(name, frame_idx)
        
        if self.current_action is None:
            self.current_action = name
            self._update_display()
        
        logger.debug(f"Added action '{name}' to sprite actor ({sprite_image.num_frames} frames cached)")
    
    def set_action(self, name, reset_animation=True):
        """
        Switch to a different action sprite.
        
        Args:
            name: Action name to activate
            reset_animation: If True, reset animation to first frame
        """
        if name not in self.actions:
            logger.warning(f"Action '{name}' not found in sprite actor")
            return
        
        self.current_action = name
        if reset_animation:
            self.actions[name].reset()
        
        self._update_display()
        logger.debug(f"Switched to action '{name}'")
    
    def _get_cached_frame_dsc(self, action_name, frame_index):
        """
        Get or create cached image descriptor for a frame.
        
        Caching prevents memory fragmentation from constantly creating new
        lv.image_dsc_t objects on every frame update.
        """
        cache_key = (action_name, frame_index)
        if cache_key in self._frame_dsc_cache:
            return self._frame_dsc_cache[cache_key]
        
        sprite = self.actions.get(action_name)
        if not sprite:
            return None
        
        # Create and cache the image descriptor
        try:
            frame_buf = sprite.get_frame_buffer(frame_index)
            img_dsc = lv.image_dsc_t({
                'header': {
                    'w': sprite.frame_width,
                    'h': sprite.frame_height,
                    'cf': lv.COLOR_FORMAT.RGB565
                },
                'data_size': len(frame_buf),
                'data': bytes(frame_buf)
            })
            self._frame_dsc_cache[cache_key] = img_dsc
            return img_dsc
        except Exception as e:
            logger.warning(f"Failed to create frame descriptor: {e}")
            return None
    
    def _update_display(self):
        """Update LVGL image widget with current frame."""
        if not self.current_action or self.current_action not in self.actions:
            return
        
        # Don't update if we're in fallback mode
        if self._is_fallback:
            return
        
        sprite = self.actions[self.current_action]
        
        # Create image widget if not exists
        if self.img_obj is None:
            self.img_obj = lv.image(self.parent)
            self.img_obj.set_pos(self.x, self.y)
            # Remove scrollable flag to prevent interaction issues
            self.img_obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
        
        # Get cached or create new LVGL image descriptor for current frame
        try:
            frame_dsc = self._get_cached_frame_dsc(self.current_action, sprite.current_frame)
            if frame_dsc:
                self._current_img_dsc = frame_dsc
                self.img_obj.set_src(self._current_img_dsc)
                # Invalidate to ensure proper redraw
                self.img_obj.invalidate()
                logger.debug(f"Image updated: {sprite.frame_width}x{sprite.frame_height}")
            else:
                self._create_fallback_display(sprite)
        except Exception as e:
            logger.warning(f"Image update failed: {e}")
            self._create_fallback_display(sprite)
    
    def _create_fallback_display(self, sprite):
        """Create fallback colored box when image loading fails."""
        # Only create fallback once
        if self._is_fallback:
            return
            
        self._is_fallback = True
        
        if self.img_obj:
            try:
                self.img_obj.delete()
            except Exception:
                pass
            self.img_obj = None
        
        # Create a simple colored box as fallback
        fallback = lv.obj(self.parent)
        fallback.set_size(sprite.frame_width, sprite.frame_height)
        fallback.set_pos(self.x, self.y)
        fallback.set_style_bg_color(lv.color_hex(0x00AA00), 0)
        fallback.set_style_border_width(1, 0)
        fallback.set_style_border_color(lv.color_hex(0xFFFF00), 0)
        fallback.remove_flag(lv.obj.FLAG.SCROLLABLE)
        # Store as img_obj so move_to still works
        self.img_obj = fallback
        logger.info("Using fallback display for sprite")
    
    def update(self, current_time_ms=None):
        """
        Update animation frame (call regularly from main loop).
        
        Args:
            current_time_ms: Current time in ms (uses ticks_ms if None)
        """
        if not self.visible or not self.current_action:
            return
        
        # Skip animation updates if in fallback mode
        if self._is_fallback:
            return
        
        if current_time_ms is None:
            current_time_ms = time.ticks_ms()
        
        # Check if enough time has passed for next frame
        if current_time_ms - self.last_frame_update >= self.animation_frame_delay:
            sprite = self.actions[self.current_action]
            sprite.next_frame()
            self._update_display()
            self.last_frame_update = current_time_ms
    
    def move_to(self, x, y):
        """Move actor to new position with proper invalidation."""
        old_x, old_y = self.x, self.y
        self.x = x
        self.y = y
        if self.img_obj:
            # Invalidate old position area before moving
            self.img_obj.invalidate()
            # Move to new position
            self.img_obj.set_pos(x, y)
            # Invalidate new position area after moving
            self.img_obj.invalidate()
    
    def set_frame_delay(self, ms):
        """Set animation frame delay in milliseconds."""
        self.animation_frame_delay = ms
    
    def show(self):
        """Show sprite actor."""
        self.visible = True
        if self.img_obj:
            self.img_obj.remove_flag(lv.obj.FLAG.HIDDEN)
    
    def hide(self):
        """Hide sprite actor."""
        self.visible = False
        if self.img_obj:
            self.img_obj.add_flag(lv.obj.FLAG.HIDDEN)
    
    def destroy(self):
        """Clean up resources and delete LVGL objects."""
        self.visible = False
        self.current_action = None
        
        # Clear frame descriptor cache
        self._frame_dsc_cache.clear()
        self._current_img_dsc = None
        
        # Delete LVGL image object
        if self.img_obj:
            try:
                self.img_obj.delete()
            except Exception:
                pass
            self.img_obj = None
        
        # Clear action references
        self.actions.clear()
        self._is_fallback = False
        
        logger.debug("LVGLSpriteActor destroyed")

class Sprite:
    def __init__(self, path, frame_width, frame_height, num_frames, frames_per_row=None, color_format=framebuf.RGB565):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.num_frames = num_frames
        self.color_format = color_format
        self.current_frame = 0

        self.path = path
        self.frame_size = frame_width * frame_height * 2  # RGB565 = 2 bytes per pixel

        # Require explicit layout
        if frames_per_row is None:
            # Default: horizontal strip
            self.frames_per_row = num_frames
        else:
            self.frames_per_row = frames_per_row
        self.frames_per_col = (num_frames + self.frames_per_row - 1) // self.frames_per_row
        self.sheet_width = self.frame_width * self.frames_per_row
        self.sheet_height = self.frame_height * self.frames_per_col

        # Validate file size
        stat = uos.stat(path)
        file_bytes = stat[6]
        expected_bytes = self.sheet_width * self.sheet_height * 2
        if file_bytes != expected_bytes:
            raise ValueError(f"Sprite sheet file size mismatch: expected {expected_bytes} bytes, got {file_bytes} bytes")

        # Load entire sprite sheet into RAM (or use streaming if needed)
        self._load_sheet()

    def _load_sheet(self):
        logger.info(f"Loading sprite sheet from {self.path} with size {self.sheet_width}x{self.sheet_height} size")
        file_size = self.sheet_width * self.sheet_height * 2
        self.sheet_buf = bytearray(file_size)

        with open(self.path, 'rb') as f:
            f.readinto(self.sheet_buf)

        self.sheet_fb = framebuf.FrameBuffer(self.sheet_buf, self.sheet_width, self.sheet_height, self.color_format)

    def get_frame_buffer(self):
        # Create a buffer for one frame
        frame_buf = bytearray(self.frame_size)
        fb = framebuf.FrameBuffer(frame_buf, self.frame_width, self.frame_height, self.color_format)

        # Calculate sprite_x and sprite_y based on grid
        x_idx = self.current_frame % self.frames_per_row
        y_idx = self.current_frame // self.frames_per_row
        sprite_x = x_idx * self.frame_width
        sprite_y = y_idx * self.frame_height

        # Copy from sprite sheet to frame
        fb.blit(self.sheet_fb, -sprite_x, -sprite_y)

        return frame_buf

    def draw(self, display, x, y):
        frame_buf = self.get_frame_buffer()
        display.draw_sprite(frame_buf, x, y, self.frame_width, self.frame_height)

    def next_frame(self):
        self.current_frame = (self.current_frame + 1) % self.num_frames

    def set_frame(self, frame_index):
        self.current_frame = frame_index % self.num_frames

    def reset(self):
        self.current_frame = 0


class SpriteActor:
    def __init__(self, display, x=0, y=0):
        self.display = display
        self.x = x
        self.y = y
        self.actions = {}  # action_name -> Sprite instance
        self.current_action = None
        self.visible = False

    def add_action(self, name, sprite):
        self.actions[name] = sprite
        if self.current_action is None:
            self.current_action = name

    def set_action(self, name):
        if name in self.actions:
            self.current_action = name
            self.actions[name].reset()

    def update(self):
        """Advance current animation frame."""
        if self.visible and self.current_action:
            self.actions[self.current_action].next_frame()

    def draw(self):
        """Draw current frame of current action."""
        if self.visible and self.current_action:
            sprite = self.actions[self.current_action]
            sprite.draw(self.display, self.x, self.y)

    def move_to(self, x, y):
        self.x = x
        self.y = y

    def hide(self):
        self.visible = False

    def show(self):
        self.visible = True
