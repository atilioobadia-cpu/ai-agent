import json
import subprocess
from pathlib import Path

import httpx

from .guards import denied_command_reason, path_allowed, shell_enabled

MAX_OUTPUT_CHARS = 3000


def _run_shell(command, timeout=30):
    if not shell_enabled():
        return "ERROR: shell execution is disabled (ALLOW_SHELL)"
    blocked = denied_command_reason(command)
    if blocked:
        return f"ERROR: command rejected by safety policy ({blocked})"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(timeout),
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return f"exit code: {proc.returncode}\n{output}"


def _list_files(path="."):
    if not path_allowed(path):
        return "ERROR: path outside allowed roots"
    p = Path(path)
    if not p.exists():
        return f"ERROR: path does not exist: {path}"
    lines = []
    for item in sorted(p.iterdir())[:200]:
        if item.is_dir():
            lines.append(f"[dir]  {item.name}")
        else:
            lines.append(f"[file] {item.name} ({item.stat().st_size} bytes)")
    return "\n".join(lines) or "(empty directory)"


def _read_file(path):
    if not path_allowed(path):
        return "ERROR: path outside allowed roots"
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _write_file(path, content=""):
    if not path_allowed(path):
        return "ERROR: path outside allowed roots"
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {p}"


def _fetch_url(url):
    response = httpx.get(
        url,
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (ai-agent tutorial)"},
    )
    response.raise_for_status()
    ctype = response.headers.get("content-type", "")
    if "html" in ctype or ctype.startswith("text/"):
        return response.text
    return f"(non-text content, type={ctype}, size={len(response.content)} bytes)"


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a PowerShell command on the local Windows machine. "
                "Destructive commands are permanently blocked; other commands "
                "require the user's approval in the UI before they execute."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell command to execute."},
                    "timeout": {"type": "integer", "description": "Seconds before the command is killed.", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and folders in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path.", "default": "."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full text content of a file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a text file with the given content. "
                "Requires user approval in the UI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "content": {"type": "string", "description": "Text to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Download a URL and return its text/HTML content.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Full http(s) URL."}},
                "required": ["url"],
            },
        },
    },
]

_EXECUTORS = {
    "run_command": _run_shell,
    "list_files": _list_files,
    "read_file": _read_file,
    "write_file": _write_file,
    "fetch_url": _fetch_url,
}


def execute_tool(name, arguments_json):
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return f"ERROR: invalid arguments JSON ({exc})"
    executor = _EXECUTORS.get(name)
    if executor is None:
        return f"ERROR: unknown tool '{name}'"
    try:
        result = str(executor(**args))
    except TypeError as exc:
        return f"ERROR: bad parameters ({exc})"
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"
    return result[:MAX_OUTPUT_CHARS]
