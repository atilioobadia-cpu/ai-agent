import json

from dotenv import load_dotenv

load_dotenv()

from agent.guards import check_tool

tests = [
    ("recursive deletion", "run_command", {"command": "Remove-Item -Recurse -Force C:\\Users\\atili\\ai-agent\\venv"}, False),
    ("safe command", "run_command", {"command": "Get-ChildItem C:\\Users\\atili\\ai-agent"}, True),
    ("system file read", "read_file", {"path": "C:\\Windows\\System32\\config\\SAM"}, False),
    ("allowed write", "write_file", {"path": "C:\\Users\\atili\\Desktop\\note.txt", "content": "x"}, True),
    ("shutdown", "run_command", {"command": "shutdown /s /t 0"}, False),
    ("outside scope", "list_files", {"path": "C:\\"}, False),
]

all_passed = True
for label, name, args, expected in tests:
    allowed, reason = check_tool(name, json.dumps(args))
    verdict = "PASS" if allowed == expected else "FAIL"
    if allowed != expected:
        all_passed = False
    print(f"[{verdict}] {label}: allowed={allowed} reason={reason}")

print("ALL GUARD TESTS PASSED" if all_passed else "SOME GUARD TESTS FAILED")
