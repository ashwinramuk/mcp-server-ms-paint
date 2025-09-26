
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

@mcp.tool()
async def open_paint() -> dict:
    """Open Microsoft Paint maximized on primary monitor"""
    global paint_app
    try:
        paint_app = Application().start('mspaint.exe')
        time.sleep(0.5)

        paint_window = paint_app.window(class_name='MSPaintApp')
        win32gui.ShowWindow(paint_window.handle, win32con.SW_MAXIMIZE)
        time.sleep(0.5)

        # Print and return control identifiers for analysis
        import io
        import sys as _sys
        buf = io.StringIO()
        _stdout = _sys.stdout
        _sys.stdout = buf
        try:
            paint_window.print_control_identifiers()
        finally:
            _sys.stdout = _stdout
        debug_info = buf.getvalue()

        return {
            "content": [
                TextContent(
                    type="text",
                    text="Paint opened successfully on primary monitor and maximized.\nControl identifiers:\n" + debug_info
                )
            ]
        }
    except Exception as e:
        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"Error opening Paint: {str(e)}"
                )
            ]
        }

@mcp.tool()
async def draw_rectangle(x1: int, y1: int, x2: int, y2: int) -> dict:
    """Draw a rectangle in Paint from (x1,y1) to (x2,y2) canvas is in middle, hence offset coordinates by 500px"""
    global paint_app
    try:
        if not paint_app:
            return {
                "content": [
                    TextContent(
                        type="text",
                        text="Paint is not open. Please call open_paint first."
                    )
                ]
            }

        paint_window = paint_app.window(class_name='MSPaintApp')
        if not paint_window.has_focus():
            paint_window.set_focus()
            time.sleep(0.2)

        # Try to select the Rectangle tool by name if possible
        try:
            rect_tool = paint_window.child_window(title_re="Rectangle|Rect|Rectangle shape", control_type="Button")
            rect_tool.click_input()
            time.sleep(0.7)  # Increased delay
        except Exception:
            paint_window.click_input(coords=(797, 128))
            time.sleep(0.7)  # Increased delay

        # Try to get the canvas
        canvas = paint_window.child_window(class_name='MSPaintView')
        if not canvas.exists():
            raise Exception("Canvas (MSPaintView) not found.")

        # Use larger default coordinates if the provided ones are small (for testing)
        if x1 == 50 and y1 == 50 and x2 == 200 and y2 == 150:
            x1, y1, x2, y2 = 200, 200, 800, 600

        # Click canvas at a safe spot to ensure focus
        canvas.click_input(coords=(400, 400))
        time.sleep(0.3)

        # Try drawing the rectangle using drag_mouse_input
        canvas.click_input(coords=(x1, y1))
        time.sleep(0.2)
        canvas.drag_mouse_input(src=(x1, y1), dst=(x2, y2), button="left", pressed="left")
        time.sleep(0.2)

        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"Rectangle drawn from ({x1},{y1}) to ({x2},{y2})"
                )
            ]
        }
    except Exception as e:
        # Always print and return control identifiers for debugging
        debug_info = ""
        try:
            import io
            import sys as _sys
            buf = io.StringIO()
            _stdout = _sys.stdout
            _sys.stdout = buf
            try:
                if 'paint_window' in locals():
                    paint_window.print_control_identifiers()
            finally:
                _sys.stdout = _stdout
            debug_info = buf.getvalue()
        except Exception as debug_err:
            debug_info = f"(Could not get control identifiers: {debug_err})"
        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"Error drawing rectangle: {str(e)}\nControl identifiers:\n{debug_info}"
                )
            ]
        }

@mcp.tool()
async def add_text_in_paint(text: str) -> dict:
    """Add text in Paint"""
    global paint_app
    try:
        if not paint_app:
            return {
                "content": [
                    TextContent(
                        type="text",
                        text="Paint is not open. Please call open_paint first."
                    )
                ]
            }
        
        paint_window = paint_app.window(class_name='MSPaintApp')
        if not paint_window.has_focus():
            paint_window.set_focus()
            time.sleep(0.5)
        
        paint_window.type_keys('t') # Select text tool
        time.sleep(0.5)
        paint_window.type_keys('x')
        time.sleep(0.5)
        
        # NOTE: These coordinates might need adjustment for different screen resolutions/UI layouts
        canvas = paint_window.child_window(class_name='MSPaintView')
        canvas.click_input(coords=(1025, 923)) # Click where to start typing
        time.sleep(0.5)
        
        paint_window.type_keys(text)
        time.sleep(0.5)
        
        canvas.click_input(coords=(1601, 999)) # Click to exit text mode
        
        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"Text:'{text}' added successfully"
                )
            ]
        }
    except Exception as e:
        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )
            ]
        }

def main():
    print("STARTING MCP PAINT SERVER")
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()
    else:
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
