"""Panel layout utilities - Screen-relative positioning helpers."""

import lvgl as lv


def get_screen_size(screen=None):
    """
    Get the current screen dimensions.
    
    Args:
        screen: LVGL screen object. If None, uses active screen.
        
    Returns:
        tuple: (width, height) in pixels
    """
    if screen is None:
        screen = lv.screen_active()
    return screen.get_width(), screen.get_height()


def get_obj_size(obj, refresh=True):
    """
    Get an object's dimensions.
    
    Args:
        obj: LVGL object
        refresh: If True, force LVGL to recalculate size first.
                 Required after setting image src, label text, etc.
        
    Returns:
        tuple: (width, height) in pixels
    """
    if refresh:
        # Force LVGL to recalculate dimensions
        # This is required after set_src(), set_text(), etc.
        obj.update_layout()
    return obj.get_width(), obj.get_height()


# =============================================================================
# Centering Functions
# =============================================================================

def center_horizontal(obj, parent=None):
    """
    Center an object horizontally within its parent.
    
    Args:
        obj: LVGL object to center
        parent: Parent container. If None, uses obj's parent or active screen.
    """
    if parent is None:
        parent = obj.get_parent()
        if parent is None:
            parent = lv.screen_active()
    
    # Force layout update to get accurate dimensions
    obj.update_layout()
    
    parent_width = parent.get_width()
    obj_width = obj.get_width()
    x = (parent_width - obj_width) // 2
    obj.set_x(x)


def center_vertical(obj, parent=None):
    """
    Center an object vertically within its parent.
    
    Args:
        obj: LVGL object to center
        parent: Parent container. If None, uses obj's parent or active screen.
    """
    if parent is None:
        parent = obj.get_parent()
        if parent is None:
            parent = lv.screen_active()
    
    # Force layout update to get accurate dimensions
    obj.update_layout()
    
    parent_height = parent.get_height()
    obj_height = obj.get_height()
    y = (parent_height - obj_height) // 2
    obj.set_y(y)


def center_obj(obj, parent=None):
    """
    Center an object both horizontally and vertically within its parent.
    
    Args:
        obj: LVGL object to center
        parent: Parent container. If None, uses obj's parent or active screen.
    """
    center_horizontal(obj, parent)
    center_vertical(obj, parent)


def center_in_screen(obj, screen=None):
    """
    Center an object in the screen (not its parent).
    
    Useful when you want to center relative to screen regardless of
    the object's parent container.
    
    Args:
        obj: LVGL object to center
        screen: Screen to center in. If None, uses active screen.
    """
    if screen is None:
        screen = lv.screen_active()
    
    screen_width, screen_height = get_screen_size(screen)
    obj_width, obj_height = get_obj_size(obj)  # refresh=True by default
    
    x = (screen_width - obj_width) // 2
    y = (screen_height - obj_height) // 2
    obj.set_pos(x, y)


# =============================================================================
# Percentage-Based Positioning
# =============================================================================

def screen_percent_x(screen, percent):
    """
    Calculate X position as percentage of screen width.
    
    Args:
        screen: LVGL screen object (or None for active screen)
        percent: Float from 0.0 to 1.0 (e.g., 0.5 = 50%)
        
    Returns:
        int: X position in pixels
    """
    width, _ = get_screen_size(screen)
    return int(width * percent)


def screen_percent_y(screen, percent):
    """
    Calculate Y position as percentage of screen height.
    
    Args:
        screen: LVGL screen object (or None for active screen)
        percent: Float from 0.0 to 1.0 (e.g., 0.5 = 50%)
        
    Returns:
        int: Y position in pixels
    """
    _, height = get_screen_size(screen)
    return int(height * percent)


def position_at_percent(obj, parent, x_percent, y_percent):
    """
    Position object at percentage coordinates within parent.
    
    Args:
        obj: LVGL object to position
        parent: Parent container
        x_percent: Horizontal position (0.0 = left, 1.0 = right)
        y_percent: Vertical position (0.0 = top, 1.0 = bottom)
    """
    parent_width = parent.get_width()
    parent_height = parent.get_height()
    obj_width, obj_height = get_obj_size(obj)
    
    # Calculate position accounting for object size
    x = int(parent_width * x_percent) - (obj_width // 2)
    y = int(parent_height * y_percent) - (obj_height // 2)
    
    obj.set_pos(x, y)


# =============================================================================
# Offset Positioning (relative to center or edges)
# =============================================================================

def center_with_offset(obj, parent=None, x_offset=0, y_offset=0):
    """
    Center an object with optional offset from center.
    
    Automatically refreshes object layout to get accurate dimensions.
    Use this after setting image sources, label text, etc.
    
    Args:
        obj: LVGL object to position
        parent: Parent container (None = use obj's parent)
        x_offset: Pixels to offset from horizontal center (positive = right)
        y_offset: Pixels to offset from vertical center (positive = down)
    """
    if parent is None:
        parent = obj.get_parent()
        if parent is None:
            parent = lv.screen_active()
    
    parent_width = parent.get_width()
    parent_height = parent.get_height()
    obj_width, obj_height = get_obj_size(obj)  # refresh=True by default
    
    x = (parent_width - obj_width) // 2 + x_offset
    y = (parent_height - obj_height) // 2 + y_offset
    obj.set_pos(x, y)


def from_top(obj, parent, margin):
    """
    Position object at top of parent with margin.
    Centers horizontally.
    
    Args:
        obj: LVGL object
        parent: Parent container
        margin: Pixels from top edge
    """
    center_horizontal(obj, parent)
    obj.set_y(margin)


def from_bottom(obj, parent, margin):
    """
    Position object at bottom of parent with margin.
    Centers horizontally.
    
    Args:
        obj: LVGL object
        parent: Parent container
        margin: Pixels from bottom edge
    """
    parent_height = parent.get_height()
    obj_height = obj.get_height()
    
    center_horizontal(obj, parent)
    obj.set_y(parent_height - obj_height - margin)


def from_left(obj, parent, margin):
    """
    Position object at left of parent with margin.
    Centers vertically.
    
    Args:
        obj: LVGL object
        parent: Parent container
        margin: Pixels from left edge
    """
    center_vertical(obj, parent)
    obj.set_x(margin)


def from_right(obj, parent, margin):
    """
    Position object at right of parent with margin.
    Centers vertically.
    
    Args:
        obj: LVGL object
        parent: Parent container
        margin: Pixels from right edge
    """
    parent_width = parent.get_width()
    obj_width = obj.get_width()
    
    center_vertical(obj, parent)
    obj.set_x(parent_width - obj_width - margin)


# =============================================================================
# Grid Layout Helpers
# =============================================================================

def grid_position(parent, cols, rows, col, row, padding=0):
    """
    Calculate position for a grid cell.
    
    Args:
        parent: Parent container
        cols: Total columns in grid
        rows: Total rows in grid
        col: Column index (0-based)
        row: Row index (0-based)
        padding: Padding between cells
        
    Returns:
        tuple: (x, y, cell_width, cell_height)
    """
    parent_width = parent.get_width()
    parent_height = parent.get_height()
    
    cell_width = (parent_width - padding * (cols + 1)) // cols
    cell_height = (parent_height - padding * (rows + 1)) // rows
    
    x = padding + col * (cell_width + padding)
    y = padding + row * (cell_height + padding)
    
    return x, y, cell_width, cell_height


def place_in_grid(obj, parent, cols, rows, col, row, padding=0):
    """
    Place an object in a grid cell.
    
    Args:
        obj: LVGL object to place
        parent: Parent container
        cols: Total columns
        rows: Total rows
        col: Column index (0-based)
        row: Row index (0-based)
        padding: Padding between cells
    """
    x, y, cell_width, cell_height = grid_position(parent, cols, rows, col, row, padding)
    obj.set_pos(x, y)
    obj.set_size(cell_width, cell_height)


# =============================================================================
# Refresh Helpers
# =============================================================================

def refresh_and_center(obj, parent=None):
    """
    Force LVGL to recalculate object size, then center it.
    
    Note: center_obj() now calls update_layout() internally,
    so this function is mainly for compatibility.
    
    Args:
        obj: LVGL object (typically a label or image)
        parent: Parent to center within
    """
    obj.update_layout()
    center_obj(obj, parent)


def refresh_and_center_horizontal(obj, parent=None):
    """
    Force LVGL to recalculate object size, then center horizontally.
    
    Note: center_horizontal() now calls update_layout() internally,
    so this function is mainly for compatibility.
    
    Args:
        obj: LVGL object
        parent: Parent to center within
    """
    obj.update_layout()
    center_horizontal(obj, parent)
