import json
import os
import time

from .guards import is_risky
from .providers import chat
from .tools import TOOL_SCHEMAS, execute_tool

_BASE_PROMPT = (
    "You are a task automation agent running on the user's Windows machine. "
    "Complete tasks by calling tools step by step until the goal is achieved. "
    "Inspect before you modify: use list_files/read_file first when relevant. "
    "Risky actions (shell commands, writing files) are shown to the user for "
    "explicit approval before they run; if the user denies an action, do not "
    "retry the same action - explain and ask how to proceed instead. "
    "Before acting on a multi-step task, briefly state your plan in one or two "
    "short sentences, then execute it tool by tool. "
    "Explain clearly what you did in your final answer. "
    "If a request is unclear or dangerous, ask a clarifying question."
)

_language = os.environ.get("AGENT_LANGUAGE", "english").strip().lower()
if _language in ("auto", "mirror", ""):
    _language_rule = (
        "LANGUAGE RULE (highest priority): Reply in the same language the user "
        "writes in; if unsure which language that is, reply in English. Whatever "
        "language you use, write it clearly with correct grammar and spelling."
    )
elif _language.startswith("swa"):
    _language_rule = (
        "LANGUAGE RULE (highest priority): Write every reply in clear, "
        "grammatically correct Swahili."
    )
else:
    _language_rule = (
        "LANGUAGE RULE (highest priority): Write every reply in English, even if "
        "the user writes in another language. Use clear, grammatically correct "
        "English only."
    )

SYSTEM_PROMPT = _language_rule + " " + _BASE_PROMPT

MAX_STEPS = 8
HISTORY_LIMIT = 10


def start(message, history=None):
    history = history or []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-HISTORY_LIMIT:])
    messages.append({"role": "user", "content": message})
    return {
        "messages": messages,
        "feed": [],
        "usage": {"input": 0, "output": 0},
        "model_rounds": 0,
    }


def _parse_args(arguments_json):
    try:
        return json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return {"_raw": arguments_json}


def _accumulate_usage(state, response):
    state["usage"]["input"] += response.usage.get("input", 0)
    state["usage"]["output"] += response.usage.get("output", 0)


def _execute_and_record(state, call):
    t0 = time.perf_counter()
    output = execute_tool(call["name"], call.get("arguments") or "{}")
    duration_ms = int((time.perf_counter() - t0) * 1000)
    state["feed"].append(
        {
            "type": "tool",
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
    _accumulate_usage(state, response)
    if not response.tool_calls:
        return {"type": "done", "reply": response.content or "(the model returned an empty reply)"}
    if response.content and response.content.strip():
        state["feed"].append({"type": "note", "text": response.content.strip()})
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
            blocked_output = f"BLOCKED: {reason}"
            state["feed"].append(
                {
                    "type": "tool",
                    "tool": call["name"],
                    "args": _parse_args(call.get("arguments") or "{}"),
                    "duration_ms": 0,
                    "output": blocked_output,
                    "ok": False,
                }
            )
            state["messages"].append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": f"{blocked_output}. Choose a different approach.",
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
        state["feed"].append(
            {
                "type": "tool",
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
    steps = [entry for entry in state["feed"] if entry["type"] == "tool"]
    return event["reply"], steps
