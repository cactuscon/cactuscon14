import gc
import sys
import os
try:
    import utime as time
except Exception:
    import time


# Track previous memory state for delta reporting
_last_mem_alloc = 0
_last_gc_ms = 0

from config import config

class Logger:
    """
    Simple logger with level-based output.
    
    Supports multiple arguments like print(), concatenating them with spaces.

    Args:
        level (int): Logging level (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=FATAL).
    """
    def __init__(self, level):
        """
        Initialize the logger.

        Args:
            level (int): Logging level.
        """
        self.level = level
        self.out = sys.stdout

    def debug(self, *args, **kwargs):
        """
        Log a debug message.

        Args:
            *args: Values to log (concatenated with spaces).
            **kwargs: Optional sep (separator, default ' ') and end (default '\\n').
        """
        if self.level <= 10:
            sep = kwargs.get('sep', ' ')
            end = kwargs.get('end', '\n')
            msg = sep.join(str(arg) for arg in args)
            self.out.write(f"DEBUG: {msg}{end}")

    def info(self, *args, **kwargs):
        """
        Log an info message.

        Args:
            *args: Values to log (concatenated with spaces).
            **kwargs: Optional sep (separator, default ' ') and end (default '\\n').
        """
        if self.level <= 20:
            sep = kwargs.get('sep', ' ')
            end = kwargs.get('end', '\n')
            msg = sep.join(str(arg) for arg in args)
            self.out.write(f"INFO: {msg}{end}")

    def warning(self, *args, **kwargs):
        """
        Log a warning message.

        Args:
            *args: Values to log (concatenated with spaces).
            **kwargs: Optional sep (separator, default ' ') and end (default '\\n').
        """
        if self.level <= 30:
            sep = kwargs.get('sep', ' ')
            end = kwargs.get('end', '\n')
            msg = sep.join(str(arg) for arg in args)
            self.out.write(f"WARNING: {msg}{end}")

    def error(self, *args, **kwargs):
        """
        Log an error message.

        Args:
            *args: Values to log (concatenated with spaces).
            **kwargs: Optional sep (separator, default ' ') and end (default '\\n').
        """
        if self.level <= 40:
            sep = kwargs.get('sep', ' ')
            end = kwargs.get('end', '\n')
            msg = sep.join(str(arg) for arg in args)
            self.out.write(f"ERROR: {msg}{end}")

    def fatal(self, *args, **kwargs):
        """
        Log a fatal error message.

        Args:
            *args: Values to log (concatenated with spaces).
            **kwargs: Optional sep (separator, default ' ') and end (default '\\n').
        """
        if self.level <= 50:
            sep = kwargs.get('sep', ' ')
            end = kwargs.get('end', '\n')
            msg = sep.join(str(arg) for arg in args)
            self.out.write(f"FATAL: {msg}{end}")

logger = Logger(config.LOG_LEVEL)

MIN_GC_INTERVAL_MS = int(getattr(config, "MIN_GC_INTERVAL_MS", 1000))


def _ticks_ms():
    try:
        return time.ticks_ms()
    except Exception:
        return int(time.time() * 1000)


def _ticks_diff(now_ms, then_ms):
    try:
        return time.ticks_diff(now_ms, then_ms)
    except Exception:
        return now_ms - then_ms


def gc_if_needed(force=False, min_interval_ms=None):
    """
    Run garbage collection with a minimum interval to reduce jitter.

    Args:
        force: If True, always run gc.collect().
        min_interval_ms: Optional override for minimum interval between runs.

    Returns:
        bool: True when gc.collect() ran, False when skipped.
    """
    global _last_gc_ms
    interval = MIN_GC_INTERVAL_MS if min_interval_ms is None else int(min_interval_ms)
    now_ms = _ticks_ms()
    if (not force) and _last_gc_ms and _ticks_diff(now_ms, _last_gc_ms) < interval:
        return False
    gc.collect()
    _last_gc_ms = now_ms
    return True

def mem_info(label="", show_modules=False, show_delta=True):
    """
    Print memory utilization info for debugging.
    
    Args:
        label: Description of current boot phase
        show_modules: If True, also print sys.modules count
        show_delta: If True, show delta from last call
    """
    global _last_mem_alloc
    gc.collect()
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    total = free + alloc
    pct = (alloc / total) * 100 if total > 0 else 0
    
    delta_str = ""
    if show_delta and _last_mem_alloc > 0:
        delta = alloc - _last_mem_alloc
        sign = "+" if delta >= 0 else ""
        delta_str = f" (Δ{sign}{delta:,})"
    
    mod_str = ""
    if show_modules:
        mod_count = len(sys.modules)
        mod_str = f" [modules: {mod_count}]"
    
    logger.debug(f"[MEM] {label}: {alloc:,} used / {free:,} free ({pct:.1f}% used){delta_str}{mod_str}")
    _last_mem_alloc = alloc


def mem_modules_summary():
    """Print summary of loaded modules for debugging memory usage."""
    gc.collect()
    mod_count = len(sys.modules)
    logger.debug(f"[MEM-MODULES] Total loaded: {mod_count}")
    
    # Group by prefix to identify heavy packages
    prefixes = {}
    for name in sys.modules.keys():
        prefix = name.split('.')[0]
        prefixes[prefix] = prefixes.get(prefix, 0) + 1
    
    # Sort by count descending
    sorted_prefixes = sorted(prefixes.items(), key=lambda x: -x[1])
    for prefix, count in sorted_prefixes[:10]:
        logger.info(f"  {prefix}: {count} modules")


def dirname(path):
    """
    Return the directory name of a path.

    Args:
        path (str): File or directory path.

    Returns:
        str: Directory name of the path.
    """
    if path == '/':
        return '/'
    stat = os.stat(path)
    if stat[0] & 0x4000:
        # Remove trailing slash for directories
        if path[-1] == '/':
            path = path[:-1]
        return path
    return path.rsplit('/', 1)[0]

def basename(path):
    """
    Return the base name of a file path.

    Args:
        path (str): File path.

    Returns:
        str: Base name of the file.
    """
    stat = os.stat(path)
    if stat[0] & 0x4000:
        raise ValueError(f"Is a directory: '{path}'")
    return path.rsplit('/', 1)[1]
