import json
import os

import httpx

CF_BASE = "https://api.cloudflare.com/client/v4/accounts"


class LLMResponse:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing {name} in .env")
    return value


def _cf_messages(messages):
    converted = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            entry = {"role": "assistant", "content": m.get("content") or ""}
            entry["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc.get("arguments") or "{}",
                    },
                }
                for tc in m["tool_calls"]
            ]
            converted.append(entry)
        elif role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id"),
                    "content": str(m.get("content", "")),
                }
            )
        else:
            converted.append({"role": role, "content": m.get("content")})
    return converted


def _cloudflare_chat(messages, tools):
    account_id = _require_env("CF_ACCOUNT_ID")
    token = _require_env("CF_API_TOKEN")
    body = {
        "model": os.environ.get("CF_MODEL", "@cf/meta/llama-3.1-8b-instruct-fp8-fast"),
        "messages": _cf_messages(messages),
        "max_tokens": 700,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    response = httpx.post(
        f"{CF_BASE}/{account_id}/ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=90,
    )
    if response.status_code != 200:
        detail = response.text[:300]
        raise RuntimeError(f"Cloudflare API error {response.status_code}: {detail}")
    message = response.json()["choices"][0]["message"]
    tool_calls = []
    for index, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function", {})
        tool_calls.append(
            {
                "id": call.get("id") or f"call_{index}",
                "name": function.get("name"),
                "arguments": function.get("arguments") or "{}",
            }
        )
    return LLMResponse(message.get("content"), tool_calls)


def _anthropic_chat(messages, tools):
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("the anthropic package is not installed")
    _require_env("ANTHROPIC_API_KEY")
    client = Anthropic()

    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    converted = []
    for m in messages:
        role = m["role"]
        if role == "system":
            continue
        if role == "user":
            converted.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            if m.get("tool_calls"):
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for call in m["tool_calls"]:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call["id"],
                            "name": call["name"],
                            "input": json.loads(call.get("arguments") or "{}"),
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
            else:
                converted.append({"role": "assistant", "content": m.get("content") or ""})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": str(m.get("content", "")),
            }
            previous = converted[-1] if converted else None
            mergeable = (
                previous is not None
                and previous["role"] == "user"
                and isinstance(previous["content"], list)
                and bool(previous["content"])
                and previous["content"][0]["type"] == "tool_result"
            )
            if mergeable:
                previous["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})

    payload = {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        "max_tokens": 1024,
        "messages": converted,
    }
    if system_text:
        payload["system"] = system_text
    if tools:
        payload["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            }
            for t in tools
        ]
    response = client.messages.create(**payload)

    content_parts = []
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            content_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(
                {"id": block.id, "name": block.name, "arguments": json.dumps(block.input)}
            )
    return LLMResponse("\n".join(content_parts) or None, tool_calls)


def chat(messages, tools):
    provider = os.environ.get("PROVIDER", "cloudflare").lower()
    if provider == "anthropic":
        return _anthropic_chat(messages, tools)
    return _cloudflare_chat(messages, tools)
