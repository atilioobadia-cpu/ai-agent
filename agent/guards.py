import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RISKY_TOOLS = {"run_command", "write_file"}

_DENY_PATTERNS = [
    ("disk formatting/partitioning", re.compile(r"\bformat(\.com)?\b|\bdiskpart\b")),
    ("system power control", re.compile(r"\bshutdown\b|\brestart-computer\b|\blogoff\b")),
    ("recursive/forced deletion", re.compile(
        r"remove-item\b[^|;]*-(recurse|force)|\brd\b\s+/s|\brmdir\b\s+/s|"
        r"\bdel\b\s+/(f|s|q)|\berase\b\s+/(f|s|q)|rm\s+-rf?\b")),
    ("registry system hive modification", re.compile(r"hklm:|hkey_local_machine")),
    ("execution policy change", re.compile(r"set-executionpolicy")),
    ("dynamic code invocation", re.compile(r"\biex\b|invoke-expression|invoke-command|scriptblock")),
    ("user/group account management", re.compile(r"net\s+(user|localgroup)\b")),
    ("firewall/network stack changes", re.compile(r"netsh\s+(advfirewall|interface|winsock)")),
    ("shadow copy / backup destruction", re.compile(r"vssadmin|wbadmin\s+delete")),
    ("boot configuration changes", re.compile(r"bcdedit")),
    ("scheduled task persistence", re.compile(r"schtasks|register-scheduledtask")),
    ("download-and-execute chains", re.compile(r"downloadstring|downloadfile|net\.webclient|iwr.*\|\s*iex")),
]


def allowed_roots():
    raw = os.environ.get("ALLOWED_PATHS", "")
    roots = [Path(p.strip().strip('"')).expanduser() for p in raw.split(";") if p.strip()]
    return roots or [PROJECT_ROOT]


def path_allowed(path):
    try:
        resolved = Path(str(path)).expanduser().resolve()
    except Exception:
        return False
    for root in allowed_roots():
        try:
            root_resolved = root.resolve()
        except Exception:
            continue
        if resolved == root_resolved or root_resolved in resolved.parents:
            return True
    return False


def denied_command_reason(command):
    lowered = str(command).lower()
    for name, pattern in _DENY_PATTERNS:
        if pattern.search(lowered):
            return name
    return None


def shell_enabled():
    return os.environ.get("ALLOW_SHELL", "true").lower() in ("1", "true", "yes")


def check_tool(name, arguments_json):
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return False, "invalid arguments JSON"
    if name == "run_command":
        if not shell_enabled():
            return False, "shell execution is disabled (ALLOW_SHELL)"
        reason = denied_command_reason(args.get("command", ""))
        if reason:
            return False, f"blocked dangerous pattern ({reason})"
    if name in ("list_files", "read_file", "write_file"):
        target = args.get("path", ".")
        if not path_allowed(target):
            roots = "; ".join(str(r) for r in allowed_roots())
            return False, f"path outside allowed roots ({roots})"
    return True, ""


def is_risky(name):
    return name in RISKY_TOOLS
