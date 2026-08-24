import json

from dotenv import load_dotenv

load_dotenv()

from agent.loop import run_agent
from agent.providers import chat
from agent.tools import TOOL_SCHEMAS, execute_tool

print("--- test 1: raw LLM connection ---")
response = chat([{"role": "user", "content": "Reply with exactly: connection ok"}], [])
print("reply:", response.content)

print("\n--- test 2: tool calling ---")
messages = [
    {"role": "user", "content": "Use the list_files tool on the path '.' and tell me what you see."}
]
first = chat(messages, TOOL_SCHEMAS)
print("tool calls requested:", json.dumps(first.tool_calls, indent=2))
if first.tool_calls:
    messages.append({"role": "assistant", "content": "", "tool_calls": first.tool_calls})
    for call in first.tool_calls:
        result = execute_tool(call["name"], call.get("arguments") or "{}")
        print(f"\n[{call['name']}] ->\n{result[:400]}")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": result,
            }
        )
    final = chat(messages, TOOL_SCHEMAS)
    print("\nfinal answer:", final.content)
else:
    print("model did NOT call a tool (just replied):", first.content)

print("\n--- test 3: full agent ---")
answer, steps = run_agent("How many Python (.py) files are in the current folder?")
print("steps taken:", [s["tool"] for s in steps])
print("answer:", answer)
