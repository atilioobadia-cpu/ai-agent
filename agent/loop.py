import json
import time

from .guards import is_risky
from .providers import chat
from .tools import TOOL_SCHEMAS, execute_tool

SYSTEM_PROMPT = (
    "You are a task automation agent running on the user's Windows machine. "
    "Complete tasks by calling tools step by step until the goal is achieved. "
    "Inspect before you modify: use list_files/read_file first when relevant. "
    "Risky actions (shell commands, writing files) are shown to the user for "
    "explicit approval before they run; if the user denies an action, do not "
    "retry the same action - explain and ask how to proceed instead. "
    "Explain clearly what you did in your final answer. "
    "If a request is unclear or dangerous, ask a clarifying question."
)

MAX_STEPS = 8
HISTORY_LIMIT = 10


def start(message, history=None):
    history = history or []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-HISTORY_LIMIT:])
    messages.append({"role": "user", "content": message})
    return {"messages": messages, "steps": [], "model_rounds": 0}


def _parse_args(arguments_json):
    try:
        return json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return {"_raw": arguments_json}


def _execute_and_record(state, call):
    t0 = time.perf_counter()
    output = execute_tool(call["name"], call.get("arguments") or "{}")
    duration_ms = int((time.perf_counter() - t0) * 1000)
    state["steps"].append(
        {
            "tool": call["name"],
            "args": _parse_args(call.get("arguments") or "{}"),
            "duration_ms": duration_ms,
            "output": output[:4000],
            "ok": not output.startswith("ERROR") and "DENIED" not in output,
        }
    )
    state["messages"].append(
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": call["name"],
            "content": output,
        }
    )


def advance(state):
    state["model_rounds"] += 1
    if state["model_rounds"] > MAX_STEPS:
        return {"type": "done", "reply": "Stopped: reached the maximum number of tool steps."}
    response = chat(state["messages"], TOOL_SCHEMAS)
    if not response.tool_calls:
        return {"type": "done", "reply": response.content or "(the model returned an empty reply)"}
    state["messages"].append(
        {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": response.tool_calls,
        }
    )
    for call in response.tool_calls:
        allowed, reason = _preflight(call)
        if not allowed:
            state["messages"].append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": f"BLOCKED: {reason}. Choose a different approach.",
                }
            )
            state["steps"].append(
                {
                    "tool": call["name"],
                    "args": _parse_args(call.get("arguments") or "{}"),
                    "duration_ms": 0,
                    "output": f"BLOCKED: {reason}",
                    "ok": False,
                }
            )
            continue
        if is_risky(call["name"]):
            state["pending"] = call
            return {"type": "approval_required", "tool_call": call}
        _execute_and_record(state, call)
    return advance(state)


def _preflight(call):
    from .guards import check_tool

    return check_tool(call["name"], call.get("arguments") or "{}")


def decide(state, approved):
    call = state.pop("pending")
    if approved:
        _execute_and_record(state, call)
    else:
        state["messages"].append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": "DENIED: the user rejected this action. Do not retry it.",
            }
        )
        state["steps"].append(
            {
                "tool": call["name"],
                "args": _parse_args(call.get("arguments") or "{}"),
                "duration_ms": 0,
                "output": "DENIED by user",
                "ok": True,
                "denied": True,
            }
        )
    return advance(state)


def run_agent(message, history=None):
    state = start(message, history)
    event = advance(state)
    while event["type"] == "approval_required":
        event = decide(state, approved=True)
    return event["reply"], state["steps"]
