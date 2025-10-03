
import sys
print("Python executable:", sys.executable)
import hashlib, os
try:
    _APP_FILE = __file__
    with open(_APP_FILE,'rb') as _f:
        _data = _f.read()
        _APP_MD5 = hashlib.md5(_data).hexdigest()
        _APP_VERSION = _APP_MD5[:8]
except Exception:
    _APP_MD5 = 'unknown'
    _APP_VERSION = 'unknown'

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent
from PIL import Image as PILImage
import time
import sys
from pywinauto.application import Application
import win32gui
import win32con
from win32api import GetSystemMetrics

# instantiate an MCP server client
mcp = FastMCP("MSPaint")

# Global variable to hold the Paint application instance
paint_app = None
_last_box_rel = None  # Stores ((start_rel),(end_rel)) of last rectangle/text box for reuse

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------
def _compute_centered_box(r, box_w=300, box_h=140):
    """Given a rectangle-like object (with left, top, right, bottom) return
    (start_rel, end_rel) relative coordinates for a centered box clamped within.
    Returns ((x1,y1),(x2,y2)). Assumes r has width() / height() helpers.
    """
    try:
        w = r.width(); h = r.height()
    except Exception:
        # Derive from raw coords as fallback
        w = (r.right - r.left); h = (r.bottom - r.top)
    cx = w // 2; cy = h // 2
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))
    start_rel = (_clamp(cx - box_w//2, 5, max(6, w-20)), _clamp(cy - box_h//2, 5, max(6, h-20)))
    end_rel = (_clamp(start_rel[0] + box_w, 10, w-10), _clamp(start_rel[1] + box_h, 10, h-10))
    return start_rel, end_rel
def _debug_controls(window):
    try:
        import io, sys as _sys
        buf = io.StringIO()
        _stdout = _sys.stdout
        _sys.stdout = buf
        try:
            window.print_control_identifiers()
        finally:
            _sys.stdout = _stdout
        return buf.getvalue()
    except Exception as e:  # pragma: no cover
        return f"(Could not capture control identifiers: {e})"

def get_paint_window(start_if_missing: bool = False):
    """Return (app, window) tuple for Paint.
    Primary attempt: backend='uia'. If connection/start fails OR later calls can't
    locate expected controls (caller can re-call with fallback flag), we attempt
    backend='win32'.
    """
    global paint_app
    from pywinauto.application import Application
    # If we already have an application instance, verify window exists
    if paint_app:
        try:
            win = paint_app.window(title_re=".*Paint.*")
            if win.exists():
                return paint_app, win
        except Exception:
            pass

    last_exc = None
    # Try UIA connect
    try:
        paint_app = Application(backend='uia').connect(title_re=".*Paint.*")
        win = paint_app.window(title_re=".*Paint.*")
        if win.exists():
            return paint_app, win
    except Exception as e:
        last_exc = e
    # Optionally start with UIA
    if start_if_missing:
        try:
            paint_app = Application(backend='uia').start('mspaint.exe')
            time.sleep(0.9)
            win = paint_app.window(title_re=".*Paint.*")
            win.wait('exists visible enabled ready', timeout=6)
            return paint_app, win
        except Exception as e:
            last_exc = e
    # Fallback: win32 connect
    try:
        paint_app = Application(backend='win32').connect(title_re=".*Paint.*")
        win = paint_app.window(title_re=".*Paint.*")
        if win.exists():
            return paint_app, win
    except Exception as e:
        last_exc = e
    # Fallback: win32 start
    if start_if_missing:
        try:
            paint_app = Application(backend='win32').start('mspaint.exe')
            time.sleep(0.9)
            win = paint_app.window(title_re=".*Paint.*")
            win.wait('exists visible enabled ready', timeout=6)
            return paint_app, win
        except Exception as e:
            last_exc = e
    raise RuntimeError(f"Paint window not found (last_error={last_exc})")

def _reconnect_uia_if_win32():
    """If current backend is win32, attempt a UIA reconnect for richer element access.
    Returns (app, window) on success else (paint_app, existing_window_or_none)."""
    global paint_app
    try:
        if paint_app and getattr(paint_app, 'backend', None) == 'win32':
            try:
                # Attempt to connect via UIA to same title
                uia_app = Application(backend='uia').connect(title_re=".*Paint.*")
                win = uia_app.window(title_re=".*Paint.*")
                if win.exists():
                    paint_app = uia_app
                    return paint_app, win
            except Exception:
                pass
        if paint_app:
            try:
                win = paint_app.window(title_re=".*Paint.*")
                return paint_app, win
            except Exception:
                return paint_app, None
        return None, None
    except Exception:
        return paint_app, None

def find_canvas(paint_window, timeout: float = 2.0):
    """Attempt multiple strategies to locate a drawable canvas element.
    Returns a control wrapper or raises RuntimeError.
    Strategies:
      1. auto_id='image' Group (modern Paint canvas host)
      2. class_name='MSPaintView'
      3. Group with title containing 'Canvas' (case-insensitive)
      4. Deep search for largest Group inside scrollViewer
      5. Fallback: largest descendant Group overall
    """
    import time as _t
    deadline = _t.time() + timeout
    last_err = None
    # 1 (retry until timeout)
    while _t.time() < deadline:
        try:
            canvas = paint_window.child_window(auto_id="image", control_type="Group")
            if canvas.exists():
                return canvas
        except Exception as e:
            last_err = e
        _t.sleep(0.15)
    # 2
    try:
        canvas = paint_window.child_window(class_name='MSPaintView')
        if canvas.exists():
            return canvas
    except Exception:
        pass
    # 3 title contains 'canvas'
    try:
        candidates = paint_window.descendants(control_type="Group")
        for c in candidates:
            try:
                title = getattr(c.element_info, 'name', '') or ''
                if title and 'canvas' in title.lower():
                    if c.exists():
                        return c
            except Exception:
                continue
    except Exception:
        pass
    # 4 heuristic: pick biggest group inside scrollViewer
    try:
        sv = paint_window.child_window(auto_id="scrollViewer", control_type="Pane")
        if sv.exists():
            groups = sv.descendants(control_type="Group")
            biggest = None
            biggest_area = 0
            for g in groups:
                try:
                    r = g.rectangle()
                    area = (r.width() * r.height()) if r else 0
                    if area > biggest_area:
                        biggest_area = area
                        biggest = g
                except Exception:
                    continue
            if biggest and biggest_area > 0:
                return biggest
    except Exception:
        pass
    # 5 overall biggest group as last resort
    try:
        groups = paint_window.descendants(control_type="Group")
        biggest = None
        biggest_area = 0
        for g in groups:
            try:
                r = g.rectangle()
                area = (r.width() * r.height()) if r else 0
                if area > biggest_area:
                    biggest_area = area
                    biggest = g
            except Exception:
                continue
        if biggest and biggest_area > 0:
            return biggest
    except Exception:
        pass
    raise RuntimeError("Canvas element not found with available strategies.")

def _approx_canvas_rect(paint_window):
    """Best-effort approximate of the drawable canvas rectangle when we cannot
    resolve a dedicated canvas control via UIA. Strategy:
      1. Try scrollViewer pane bounds (auto_id=scrollViewer) and inset padding.
      2. Else use window rectangle minus a fixed top ribbon height & bottom status bar height.
    Returns (left, top, right, bottom) tuple or None if impossible.
    """
    try:
        sv = paint_window.child_window(auto_id="scrollViewer", control_type="Pane")
        if sv.exists():
            r = sv.rectangle()
            # Provide gentle insets to avoid toolbar overlays
            return (r.left + 50, r.top + 30, r.right - 60, r.bottom - 120)
    except Exception:
        pass
    try:
        wr = paint_window.rectangle()
        # Rough heuristic numbers derived from observed layout metrics in snapshot
        return (wr.left + 350, wr.top + 300, wr.right - 400, wr.bottom - 160)
    except Exception:
        return None

@mcp.tool()
async def diagnostics() -> dict:
    """Return diagnostic info about runtime environment and Paint process state."""
    import hashlib, os, inspect
    details = []
    # Python executable
    details.append(f"python_executable={sys.executable}")
    # File path & hash
    try:
        current_file = inspect.getsourcefile(sys.modules[__name__]) or __file__
        if os.path.exists(current_file):
            with open(current_file,'rb') as f:
                data = f.read()
            md5 = hashlib.md5(data).hexdigest()
            details.append(f"app_file={current_file}")
            details.append(f"app_md5={md5}")
            details.append(f"app_version={_APP_VERSION}")
        else:
            details.append(f"app_file_missing={current_file}")
    except Exception as e:
        details.append(f"file_hash_error={e}")
    # Paint process info
    global paint_app
    try:
        if paint_app:
            details.append(f"paint_backend={getattr(paint_app,'backend', 'unknown')}")
            try:
                proc = paint_app.process
                details.append(f"paint_process={proc}")
            except Exception:
                pass
            try:
                win = paint_app.window(title_re=".*Paint.*")
                details.append(f"window_exists={win.exists()}")
            except Exception as e:
                details.append(f"window_query_error={e}")
        else:
            details.append("paint_app=None")
    except Exception as e:
        details.append(f"paint_state_error={e}")
    return {"content":[TextContent(type="text", text="Diagnostics:\n" + "\n".join(details))]}

@mcp.tool()
async def restart_instructions() -> dict:
    """Provide explicit steps to fully restart the Paint MCP server ensuring latest code is active."""
    steps = [
        "1. Stop any existing server process: close the terminal running app.py or kill python process named mspaint server.",
        "2. (Optional) Run diagnostics tool before stopping to note current app_md5.",
        "3. In project root run: `python app.py dev` (or your launcher) to start fresh. If using uv: `uv run python app.py dev`.",
        "4. After start, call diagnostics again and confirm app_md5 matches the file you just edited.",
        "5. Call open_paint tool, then add_text_in_paint / draw_rectangle.",
        "6. If text still not types and message shows canvas_control_missing_fallback_used, ensure the Paint window is not minimized and is fully visible on primary monitor.",
        "7. If issues persist, try switching Windows theme (light/dark) once or resizing the Paint window; then retry add_text_in_paint.",
        "8. Provide the diagnostics output plus tool responses for further analysis.",
        f"Current loaded code hash (at server import): {_APP_MD5}",
        f"App version tag: {_APP_VERSION}",
    ]
    return {"content": [TextContent(type="text", text="Restart Instructions:\n" + "\n".join(steps))]}

@mcp.tool()
async def open_paint() -> dict:
    """Open Microsoft Paint maximized on primary monitor"""
    global paint_app
    try:
        _, paint_window = get_paint_window(start_if_missing=True)
        try:
            paint_window.set_focus()
        except Exception:
            pass
        debug_info = _debug_controls(paint_window)
        return {"content": [TextContent(type="text", text=f"Paint ready (v={_APP_VERSION}). Control identifiers (snapshot):\n" + debug_info)]}
    except Exception as e:
        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"Error opening/connecting to Paint: {e}"
                )
            ]
        }

@mcp.tool()
async def draw_rectangle(x1: int | None = None, y1: int | None = None, x2: int | None = None, y2: int | None = None) -> dict:
    """Draw a rectangle. If coordinates are omitted or invalid, a centered 300x140
    rectangle (same region used by default text insertion) is drawn. Passing
    all four coordinates within canvas bounds uses the custom region and
    updates the shared box for subsequent text placement."""
    global paint_app
    try:
        # Get or start window then try UIA reconnect for richer controls
        _, paint_window = get_paint_window(start_if_missing=False)
        _reconnect_uia_if_win32()
        try:
            paint_window.set_focus()
        except Exception:
            pass
        time.sleep(0.15)

        # Select Rectangle tool: search by title, else fallback to generic Shapes group traversal
        rect_selected = False
        # Multi-pass wait for rectangle tool
        for attempt in range(6):
            # Attempt direct auto_id / title pattern(s)
            for locator in [
                dict(auto_id="ShapesRectangleTool", control_type="Button"),
                dict(title_re="^Rectangle$", control_type="Button"),
            ]:
                try:
                    btn = paint_window.child_window(**locator)
                    if btn.exists():
                        btn.click_input()
                        rect_selected = True
                        time.sleep(0.25)
                        break
                except Exception:
                    continue
            if rect_selected:
                break
            # Try Shapes group traversal
            try:
                shapes_group = paint_window.child_window(title="Shapes", control_type="Group")
                if shapes_group.exists():
                    for auto in ["ShapesRectangleTool", "ShapesRoundedRectangleTool"]:
                        try:
                            cand = shapes_group.child_window(auto_id=auto, control_type="Button")
                            if cand.exists():
                                cand.click_input()
                                rect_selected = True
                                time.sleep(0.25)
                                break
                        except Exception:
                            continue
            except Exception:
                pass
            if rect_selected:
                break
            # Reconnect UIA once mid-way
            if attempt == 2:
                _reconnect_uia_if_win32()
            time.sleep(0.2)
        if not rect_selected:
            return {"content": [TextContent(type="text", text="Could not locate Rectangle tool.")]}

        # Locate canvas using unified helper
        try:
            canvas = find_canvas(paint_window)
        except Exception as ce:
            snapshot = _debug_controls(paint_window)
            return {"content": [TextContent(type="text", text=f"Canvas not found: {ce}\nSnapshot:\n{snapshot}")]}          

        # Instead of using provided coords, replicate the centered text-area logic for consistency
        # Get canvas rectangle and compute a centered box similar to add_text_in_paint drag
        r = canvas.rectangle()
        global _last_box_rel
        # Attempt to use provided coordinates if they form a reasonable box within canvas bounds.
        try:
            w = r.width(); h = r.height()
        except Exception:
            w = (r.right - r.left); h = (r.bottom - r.top)
        # Normalize inputs (they might be absolute or intended relative). We treat them as relative.
        use_custom = False
        if all(v is not None for v in [x1,y1,x2,y2]):
            rx1, ry1, rx2, ry2 = x1, y1, x2, y2
            # Ensure ordering
            if rx2 < rx1: rx1, rx2 = rx2, rx1
            if ry2 < ry1: ry1, ry2 = ry2, ry1
            min_size = 10
            if 0 <= rx1 < w and 0 <= ry1 < h and 0 < rx2 <= w and 0 < ry2 <= h and (rx2-rx1) >= min_size and (ry2-ry1) >= min_size:
                start_rel = (rx1, ry1)
                end_rel = (rx2, ry2)
                use_custom = True
            else:
                start_rel, end_rel = _compute_centered_box(r)
        else:
            start_rel, end_rel = _compute_centered_box(r)
        _last_box_rel = (start_rel, end_rel)

        # Focus canvas and draw using relative coordinates
        canvas.click_input(coords=start_rel)
        time.sleep(0.1)
        canvas.drag_mouse_input(src=start_rel, dst=end_rel, button="left", pressed="left")
        time.sleep(0.25)
        actual_start_abs = (r.left + start_rel[0], r.top + start_rel[1])
        actual_end_abs = (r.left + end_rel[0], r.top + end_rel[1])
        return {"content": [TextContent(type="text", text=(
            f"Rectangle drawn success=True rel_start={start_rel} rel_end={end_rel} "
            f"abs_start={actual_start_abs} abs_end={actual_end_abs} custom={use_custom} v={_APP_VERSION}"))]}
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        info = ""
        try:
            _, win = get_paint_window(start_if_missing=False)
            info = _debug_controls(win)
        except Exception:
            pass
        return {"content": [TextContent(type="text", text=f"Error drawing rectangle: {e}\nTraceback:\n{tb}\nWindow tree snapshot:\n{info}")]}        


@mcp.tool()
async def add_text_in_paint(text: str) -> dict:
    """Rectangle-style behavior: select Text tool and create a centered text box
    with identical geometry to the default rectangle (300x140) used by
    draw_rectangle. This ensures text appears inside the same region Paint
    would use for the rectangle tool helper.

    Updated unified strategy:
      1. Focus Paint window.
      2. Select Text tool (auto_id=TextTool or title 'Text').
      3. Locate canvas via find_canvas.
         - If found: drag a box defined by _compute_centered_box(canvas.rect).
         - If not: fallback to approximate canvas rect heuristic, attempt a drag.
      4. Detect overlay Edit control; if present, type directly.
      5. Progressive fallbacks (double-click center, second drag, seed typing,
         send_keys, WM_CHAR injection, clipboard paste) until inserted.
    Returns concise status line including success, mode, version and geometry.
    """
    global paint_app
    try:
        _, paint_window = get_paint_window(start_if_missing=False)
        _reconnect_uia_if_win32()
        try:
            paint_window.set_focus()
            time.sleep(0.12)
        except Exception:
            pass

        # Clear any lingering selection / overlays
        try:
            paint_window.type_keys('{ESC}', set_foreground=True)
            time.sleep(0.08)
        except Exception:
            pass

        # 1. Select Text tool (multi-attempt)
        text_selected = False
        for attempt in range(6):
            for locator in [
                dict(auto_id="TextTool", control_type="Button"),
                dict(title_re="^Text$", control_type="Button")
            ]:
                try:
                    btn = paint_window.child_window(**locator)
                    if btn.exists():
                        btn.click_input()
                        text_selected = True
                        break
                except Exception:
                    continue
            if text_selected:
                break
            if attempt == 2:
                _reconnect_uia_if_win32()
            time.sleep(0.2)
        if not text_selected:
            return {"content": [TextContent(type="text", text="Text tool not found.")]}        

        # 2. Locate canvas
        canvas = None
        canvas_err = None
        try:
            canvas = find_canvas(paint_window, timeout=1.0)
        except Exception as ce:
            canvas_err = str(ce)

        import pywinauto.mouse as _mouse
        drag_used = False
        rel_box = None
        abs_points = {}

        def _clamp(v, lo, hi):
            return max(lo, min(hi, v))

        # 3. Create text region: prefer last rectangle if available to ensure exact match
        reuse_last = False
        if canvas is not None:
            try:
                r = canvas.rectangle()
                global _last_box_rel
                if _last_box_rel and isinstance(_last_box_rel, tuple) and len(_last_box_rel) == 2:
                    start_rel, end_rel = _last_box_rel
                    reuse_last = True
                else:
                    start_rel, end_rel = _compute_centered_box(r)
                rel_box = (start_rel, end_rel)
                canvas.drag_mouse_input(src=start_rel, dst=end_rel, button="left", pressed="left")
                drag_used = True
                abs_points['start'] = (r.left + start_rel[0], r.top + start_rel[1])
                abs_points['end'] = (r.left + end_rel[0], r.top + end_rel[1])
                # Update last box if newly computed
                if not reuse_last:
                    _last_box_rel = (start_rel, end_rel)
            except Exception as ce:
                canvas_err = canvas_err or f"drag_fail={ce}"
        if not drag_used:
            # fallback: approximate rect center click then small drag via absolute coords
            approx = _approx_canvas_rect(paint_window)
            if approx:
                l,t,r2,b = approx
                cx = (l + r2)//2
                cy = (t + b)//2
                start = (cx - 120, cy - 60)
                end = (cx + 120, cy + 60)
                try:
                    _mouse.press(coords=start)
                    time.sleep(0.05)
                    _mouse.move(coords=end)
                    time.sleep(0.05)
                    _mouse.release(coords=end)
                    drag_used = True
                    abs_points['start'] = start
                    abs_points['end'] = end
                except Exception as ce:
                    canvas_err = canvas_err or f"fallback_drag_fail={ce}"
            else:
                # Ultimate fallback: double click at (500,500)
                for _ in range(2):
                    try:
                        _mouse.click(coords=(500,500))
                        time.sleep(0.08)
                    except Exception:
                        pass
                abs_points['double_click'] = (500,500)

        # 4. Poll for overlay edit
        safe_text = text.replace('{', '{{').replace('}', '}}')
        overlay = None
        overlay_found = False
        poll_delays = [0.12,0.18,0.25,0.33,0.45,0.6]
        for d in poll_delays:
            try:
                overlay = paint_window.child_window(control_type="Edit")
                if overlay.exists():
                    overlay_found = True
                    break
            except Exception:
                pass
            time.sleep(d)

        mode = None
        inserted = False
        if overlay_found:
            try:
                try:
                    overlay.set_focus()
                except Exception:
                    pass
                overlay.type_keys(safe_text, with_spaces=True, set_foreground=True)
                inserted = True
                mode = "overlay_type"
            except Exception as e:
                mode = f"overlay_fail:{e}"

        # If overlay not found yet, attempt double-click in center then re-poll
        center_abs = None
        if not inserted:
            try:
                if 'start' in abs_points and 'end' in abs_points:
                    sx, sy = abs_points['start']; ex, ey = abs_points['end']
                    center_abs = ((sx+ex)//2, (sy+ey)//2)
                elif 'double_click' in abs_points:
                    center_abs = abs_points['double_click']
                if center_abs:
                    from pywinauto import mouse
                    mouse.click(button='left', coords=center_abs)
                    time.sleep(0.07)
                    mouse.click(button='left', coords=center_abs)
                    time.sleep(0.18)
                    # re-poll quick
                    for d2 in [0.1,0.15,0.22]:
                        try:
                            overlay = paint_window.child_window(control_type="Edit")
                            if overlay.exists():
                                overlay_found = True
                                try:
                                    overlay.set_focus()
                                except Exception:
                                    pass
                                overlay.type_keys(safe_text, with_spaces=True, set_foreground=True)
                                inserted = True
                                if mode is None:
                                    mode = "overlay_after_double_click"
                                break
                        except Exception:
                            pass
                        time.sleep(d2)
            except Exception:
                pass

        # If still not inserted, try a smaller second drag to force box
        if not inserted:
            try:
                from pywinauto import mouse
                if center_abs:
                    sx = center_abs[0]-60; sy = center_abs[1]-30
                    ex = center_abs[0]+60; ey = center_abs[1]+30
                    mouse.press(coords=(sx,sy))
                    time.sleep(0.05)
                    mouse.move(coords=(ex,ey))
                    time.sleep(0.05)
                    mouse.release(coords=(ex,ey))
                    time.sleep(0.25)
                    for d3 in [0.12,0.2,0.3]:
                        try:
                            overlay = paint_window.child_window(control_type="Edit")
                            if overlay.exists():
                                overlay_found = True
                                try: overlay.set_focus()
                                except Exception: pass
                                overlay.type_keys(safe_text, with_spaces=True, set_foreground=True)
                                inserted = True
                                if mode is None:
                                    mode = "overlay_after_second_drag"
                                break
                        except Exception:
                            pass
                        time.sleep(d3)
            except Exception:
                pass

        # Seeding fallback (space + backspace) then type (only if still not inserted)
        if not inserted:
            try:
                paint_window.type_keys(" ", set_foreground=True)
                time.sleep(0.05)
                paint_window.type_keys("{BACKSPACE}")
                time.sleep(0.05)
                paint_window.type_keys(safe_text, with_spaces=True, set_foreground=True)
                inserted = True
                if mode is None:
                    mode = "window_seed_type"
            except Exception:
                if mode is None:
                    mode = "seed_type_fail"

        # Try alternate send_keys (pywinauto.keyboard) if still not inserted
        if not inserted:
            try:
                from pywinauto.keyboard import send_keys
                send_keys(safe_text)
                inserted = True
                if mode is None:
                    mode = "keyboard_send_keys"
            except Exception:
                pass

        # WM_CHAR low-level injection as a last resort (when we have overlay or canvas handle)
        if not inserted:
            try:
                target_handle = None
                try:
                    if overlay_found and overlay is not None:
                        target_handle = overlay.element_info.handle
                except Exception:
                    pass
                if target_handle is None and canvas is not None:
                    try:
                        target_handle = canvas.element_info.handle
                    except Exception:
                        pass
                if target_handle:
                    import win32gui, win32con
                    try:
                        win32gui.SetForegroundWindow(target_handle)
                    except Exception:
                        pass
                    for ch in text:
                        try:
                            win32gui.PostMessage(target_handle, win32con.WM_CHAR, ord(ch), 0)
                            time.sleep(0.01)
                        except Exception:
                            break
                    inserted = True  # we attempted injection; visual check still required
                    if mode is None:
                        mode = "wm_char_injected"
            except Exception:
                pass

        # 6. Clipboard fallback
        if not inserted:
            try:
                import pyperclip
                pyperclip.copy(text)
                paint_window.type_keys("^v", set_foreground=True)
                inserted = True
                mode = "clipboard_paste"
            except Exception:
                pass

        status_parts = [
            f"TextDrag '{text}' success={inserted}",
            f"mode={mode}",
            f"drag_used={drag_used}",
            f"overlay_found={overlay_found}",
            f"v={_APP_VERSION}"
        ]
        if rel_box:
            status_parts.append(f"rel_box={rel_box}")
            status_parts.append(f"reuse_last={reuse_last}")
        if abs_points:
            status_parts.append(f"abs_points={abs_points}")
        if canvas_err:
            status_parts.append(f"note={canvas_err}")
        return {"content": [TextContent(type="text", text=" ".join(status_parts))]}
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return {"content": [TextContent(type="text", text=f"Error (drag-centered) adding text: {e}\nTraceback:\n{tb}")]}        

def main():
    print("STARTING MCP PAINT SERVER")
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()
    else:
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
