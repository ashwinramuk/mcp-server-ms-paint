import google.generativeai as genai
import asyncio
import json
import os
from dotenv import load_dotenv
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

# Configure your Gemini API key
load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

async def main():
    # Set up connection to the MCP server using stdio transport
    server_params = StdioServerParameters(command="uv", args=["run", "app.py"])
    model = genai.GenerativeModel('gemini-2.5-flash')

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("AI Paint Client - Type 'exit' to quit.")
            while True:
                user_command = input("\nEnter your drawing command: ")
                if user_command.lower() == 'exit':
                    break

                prompt = f"""
                Extract a list of actions from the following command. Each action should be a JSON object with 'tool_name' and 'args'.
                \n\nIf the command is to open paint, the tool name is 'open_paint' and there are no arguments.
                \n\nIf the command is to draw a rectangle, the tool name is 'draw_rectangle' and arguments should be 'x1', 'y1', 'x2', 'y2'.
                \nAssume a canvas size of 1920x1080. If x1, y1, x2, y2 are not provided, use x1=650, y1=398, x2=1109, y2=690 as defaults.
                \n\nIf the command is to add text, the tool name is 'add_text_in_paint' and the argument is 'text'.
                \n\nOutput a JSON object with an 'actions' key, whose value is a list of action objects in the order they should be executed.
                \nUser command: {user_command}\n"""

                try:
                    response = model.generate_content(prompt)
                    gemini_output = response.text.strip()
                    if gemini_output.startswith('```json') and gemini_output.endswith('```'):
                        gemini_output = gemini_output[len('```json'):-len('```')].strip()
                    print("Gemini's Raw Output (after stripping markdown):", gemini_output)
                    try:
                        actions_obj = json.loads(gemini_output)
                        actions = actions_obj.get("actions", [])
                        if not isinstance(actions, list):
                            print("Error: 'actions' is not a list.")
                            continue
                        for idx, action in enumerate(actions):
                            tool_name = action.get("tool_name")
                            args = action.get("args", {})
                            print(f"\nExecuting action {idx+1}: {tool_name} with args {args}")
                            if tool_name == "open_paint":
                                print("Calling open_paint...")
                                result = await session.call_tool("open_paint", {})
                                print(f"Paint server response: {result.content[0].text if result.content else result}")
                            elif tool_name == "draw_rectangle":
                                x1 = args.get("x1", 650)
                                y1 = args.get("y1", 398)
                                x2 = args.get("x2", 1109)
                                y2 = args.get("y2", 690)
                                print(f"Calling draw_rectangle with x1={x1}, y1={y1}, x2={x2}, y2={y2}")
                                result = await session.call_tool("draw_rectangle", {"x1": x1, "y1": y1, "x2": x2, "y2": y2})
                                print(f"Paint server response: {result.content[0].text if result.content else result}")
                            elif tool_name == "add_text_in_paint":
                                text_content = args.get("text", "Default Text")
                                print(f"Calling add_text_in_paint with text='{text_content}'")
                                result = await session.call_tool("add_text_in_paint", {"text": text_content})
                                print(f"Paint server response: {result.content[0].text if result.content else result}")
                            else:
                                print(f"Error: Unknown tool_name '{tool_name}' received from Gemini.")
                    except json.JSONDecodeError:
                        print("Error: Gemini did not return a valid JSON object. Please try again with a clearer command.")
                        print("Gemini's output was:", gemini_output)
                except Exception as e:
                    print(f"An error occurred with Gemini API: {e}")

if __name__ == '__main__':
    asyncio.run(main())