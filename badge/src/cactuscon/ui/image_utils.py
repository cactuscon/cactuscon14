"""Image loading utilities - RGB565 image handling for LVGL."""

import os
import lvgl as lv
import sys
import ubinascii
import gc
from cactuscon.utils import Logger
from cactuscon import config

# Global flag for whether to swap bytes (big-endian source -> little-endian display)
# Default False because our display uses rgb565_byte_swap=True which handles
# the byte swapping at the hardware level - no software swap needed.
_swap_bytes = False

logger = Logger(getattr(config, "LOG_LEVEL", 20))


def _log_icon_error(msg: str, exc: Exception = None) -> None:
    """Lightweight icon helper logging."""
    try:
        logger.info(msg)
        if exc:
            try:
                sys.print_exception(exc)
            except Exception:
                pass
    except Exception:
        # Never let logging break icon creation
        pass


def set_byte_swap_enabled(enabled: bool):
    """
    Enable/disable byte swapping for RGB565 image loading.

    Set to True when:
    - Source images are big-endian (like from pic_to_rgb565.py)
    - Display uses rgb565_byte_swap=True

    Args:
        enabled: True to swap bytes when loading images
    """
    global _swap_bytes
    _swap_bytes = enabled


def is_byte_swap_enabled() -> bool:
    """
    Check if byte swapping is enabled.

    Returns:
        True if bytes will be swapped when loading images
    """
    return _swap_bytes


def swap_bytes_rgb565(buf, length=None) -> None:
    """
    Swap bytes in an RGB565 buffer in-place.

    Converts between big-endian and little-endian byte order for each
    16-bit pixel. Use this when source images have different endianness
    than what the display expects.

    Args:
        buf: Mutable bytearray containing RGB565 pixel data (modified in-place)
    """
    if length is None:
        length = len(buf)
    for i in range(0, length, 2):
        # Swap adjacent bytes
        buf[i], buf[i + 1] = buf[i + 1], buf[i]


def invert_rgb565_buffer(buf: bytearray) -> None:
    """
    Invert colors in an RGB565 buffer in-place (legacy function).

    For RGB565, inversion means flipping all 16 bits of each pixel.
    Note: This is typically NOT needed if hardware inversion is used.

    Args:
        buf: Mutable bytearray containing RGB565 pixel data (modified in-place)
    """
    for i in range(0, len(buf), 2):
        # Read 16-bit pixel (little-endian)
        pixel = buf[i] | (buf[i + 1] << 8)
        # Invert all bits
        inverted = (~pixel) & 0xFFFF
        # Write back (little-endian)
        buf[i] = inverted & 0xFF
        buf[i + 1] = (inverted >> 8) & 0xFF


def load_rgb565_single_frame(path: str, width: int, height: int, do_swap: bool = None) -> bytearray:
    """
    Load a single-frame RGB565 image with known dimensions.
    Avoids unnecessary work when no sprite sheet slicing is needed.
    """
    buf = load_rgb565_file(path, do_swap=do_swap)
    expected_bytes = width * height * 2
    if len(buf) != expected_bytes:
        _log_icon_error(f"Size mismatch for {path}: expected {expected_bytes} bytes, got {len(buf)}")
    return buf


def load_rgb565_file(path: str, do_swap: bool = None) -> bytearray:
    """
    Load an RGB565 binary file into a bytearray.

    Automatically swaps bytes if enabled (for big-endian to little-endian
    conversion), unless explicitly overridden.

    Args:
        path: Path to RGB565 binary file
        do_swap: Override byte swapping (None = use global state)

    Returns:
        bytearray with (optionally byte-swapped) RGB565 pixel data

    Raises:
        OSError: If file not found or read error
    """

    try:
        # Get file size
        stat = os.stat(path)
        file_size = stat[6]
        if file_size == 0:
            _log_icon_error(f"File {path} is zero-length (corrupt or empty)")
            raise OSError(f"File {path} is zero-length (corrupt or empty)")

        # Load into mutable buffer
        buf = bytearray(file_size)
    except OSError as e:
        _log_icon_error(f"Failed to stat or allocate buffer for {path}: {e}")
        raise
    
    try:
        with open(path, "rb") as f:
            n = f.readinto(buf)
            if n != file_size:
                _log_icon_error(f"Read {n} bytes from {path}, expected {file_size}")
                raise OSError(f"Read {n} bytes from {path}, expected {file_size}")
    except OSError as e:
        _log_icon_error(f"readinto() failed for {path}: {e}")
        # Try fallback: read() instead of readinto()
        try:
            with open(path, "rb") as f:
                data = f.read()
                if len(data) != file_size:
                    _log_icon_error(f"Fallback read() got {len(data)} bytes from {path}, expected {file_size}")
                    raise OSError(f"Fallback read() got {len(data)} bytes from {path}, expected {file_size}")
                buf = bytearray(data)
        except Exception as e2:
            _log_icon_error(f"Fallback read() also failed for {path}: {e2}")
            raise

    # Determine if we should swap bytes
    should_swap = do_swap if do_swap is not None else _swap_bytes

    if should_swap:
        swap_bytes_rgb565(buf, length=len(buf))

    return buf


def load_rgb565_file_into(path: str, buf, do_swap: bool = None, size: int = None):
    """
    Load an RGB565 binary file into an existing buffer.

    Args:
        path: Path to RGB565 binary file
        buf: Writable buffer (bytearray or memoryview) to fill
        do_swap: Override byte swapping (None = use global state)
        size: If provided, number of bytes to read (defaults to full file size)

    Returns:
        memoryview of the populated buffer slice
    """
    stat = os.stat(path)
    file_size = stat[6]
    if file_size == 0:
        _log_icon_error(f"File {path} is zero-length (corrupt or empty)")
        raise OSError(f"File {path} is zero-length (corrupt or empty)")

    target_size = file_size if size is None else size
    if target_size != file_size:
        _log_icon_error(
            f"Size mismatch for {path}: expected {target_size} bytes, got {file_size}"
        )
        raise OSError(f"Size mismatch for {path}: expected {target_size} got {file_size}")

    view = buf if isinstance(buf, memoryview) else memoryview(buf)
    view = view[:target_size]
    if len(view) < target_size:
        raise ValueError(f"Buffer too small for {path}: need {target_size}, have {len(view)}")

    with open(path, "rb") as f:
        n = f.readinto(view)
        if n != target_size:
            _log_icon_error(f"Read {n} bytes from {path}, expected {target_size}")
            raise OSError(f"Read {n} bytes from {path}, expected {target_size}")

    should_swap = do_swap if do_swap is not None else _swap_bytes
    if should_swap:
        swap_bytes_rgb565(view, length=target_size)

    return view


def create_image_descriptor(data, width: int, height: int) -> "lv.image_dsc_t":
    """
    Create an LVGL image descriptor from RGB565 data.

    Args:
        data: RGB565 pixel data (bytes or bytearray)
        width: Image width in pixels
        height: Image height in pixels

    Returns:
        lv.image_dsc_t that can be passed to lv.image.set_src()
    """
    if isinstance(data, (bytearray, memoryview)):
        raw = data
    else:
        raw = data
    return lv.image_dsc_t(
        {
            "header": {"w": width, "h": height, "cf": lv.COLOR_FORMAT.RGB565},
            "data_size": len(raw),
            "data": raw,
        }
    )


def load_rgb565_image(path: str, width: int, height: int, do_swap: bool = None):
    """
    Load an RGB565 image file and create an LVGL image descriptor.

    Convenience function that combines load_rgb565_file() and create_image_descriptor().
    Automatically handles byte swapping based on global state.

    Args:
        path: Path to RGB565 binary file
        width: Expected image width in pixels
        height: Expected image height in pixels
        do_swap: Override byte swapping (None = use global state)

    Returns:
        tuple: (lv.image_dsc_t, bytes) - descriptor and data
               Keep reference to both to prevent garbage collection!

    Raises:
        ValueError: If file size doesn't match expected dimensions
        OSError: If file not found
    """
    # Validate file size
    stat = os.stat(path)
    file_size = stat[6]
    expected_size = width * height * 2  # RGB565 = 2 bytes per pixel

    if file_size != expected_size:
        raise ValueError(
            f"Image size mismatch: expected {expected_size} bytes "
            f"({width}x{height}), got {file_size} bytes"
        )

    # Load and optionally swap bytes
    buf = load_rgb565_file(path, do_swap)

    # Convert to immutable bytes for LVGL
    data = bytes(buf)

    # Create descriptor
    img_dsc = create_image_descriptor(data, width, height)

    return img_dsc, data


def load_rgb565_image_raw(path: str, width: int, do_swap: bool = None):
    """
    Load an RGB565 image file without size validation.

    Use this for images where the height may vary (like keyboard overlays).
    Height is calculated from file size assuming width is known.

    Args:
        path: Path to RGB565 binary file
        width: Image width in pixels
        do_swap: Override byte swapping (None = use global state)

    Returns:
        tuple: (lv.image_dsc_t, bytes, height) - descriptor, data, and calculated height
               Keep reference to data to prevent garbage collection!

    Raises:
        OSError: If file not found
    """
    # Get file size and calculate height(round up to not lose partial rows)
    stat = os.stat(path)
    file_size = stat[6]
    bytes_per_row = width * 2  # RGB565 = 2 bytes per pixel
    height = (file_size + bytes_per_row - 1) // bytes_per_row  # Ceiling division

    # Load and optionally swap bytes
    buf = load_rgb565_file(path, do_swap)

    # Pad buffer if needed to match declared height (avoid reading past buffer)
    expected_size = width * height * 2
    if len(buf) < expected_size:
        # Pad with zeros (black pixels)
        buf.extend(bytes(expected_size - len(buf)))

    # Convert to immutable bytes for LVGL
    data = bytes(buf)

    # Create descriptor
    img_dsc = create_image_descriptor(data, width, height)

    return img_dsc, data, height


# ---------- Embedded asset support ----------


def _write_bytes_literal(
    f,
    var_name: str,
    src_path: str,
    chunk_size: int = 16384,
    fast_threshold_kb: int = 160,
):
    """
    Stream a file into a series of bytes.fromhex() appends to avoid large allocations.
    Uses a fast-path for files <= fast_threshold_kb by reading once.

    Args:
        f: open file handle for the generated module
        var_name: python variable name to assign
        src_path: source file path to read
        chunk_size: read size per iteration
    """
    f.write(f"{var_name} = b''\n")
    try:
        stat = os.stat(src_path)
        size_bytes = stat[6] if isinstance(stat, (tuple, list)) else stat.st_size
    except Exception:
        size_bytes = None

    # Fast path: load once if under threshold
    if size_bytes is not None and size_bytes <= fast_threshold_kb * 1024:
        with open(src_path, "rb") as src:
            data = src.read()
        hex_chunk = ubinascii.hexlify(data).decode()
        f.write(f"{var_name} += bytes.fromhex('{hex_chunk}')\n")
        return

    # Streaming path for large files
    with open(src_path, "rb") as src:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            hex_chunk = ubinascii.hexlify(chunk).decode()
            f.write(f"{var_name} += bytes.fromhex('{hex_chunk}')\n")


def path_to_asset_id(path: str) -> str:
    """Convert asset path to variable name (assets/images/foo.rgb565 -> images_foo)."""
    rel = path.lstrip("/")
    if rel.startswith("assets/"):
        rel = rel[len("assets/") :]
    rel_no_ext = rel.rsplit(".", 1)[0]
    return rel_no_ext.replace("/", "_").replace("-", "_").replace(".", "_")


def file_exists(path: str) -> bool:
    """
    Check if a file exists (MicroPython compatible).

    Args:
        path: File path to check

    Returns:
        True if file exists, False otherwise
    """
    try:
        os.stat(path)
        return True
    except OSError:
        return False
