# AI Agent (task automation)

A minimal AI agent you can teach yourself with. Chat in the browser; the LLM
plans and calls real tools on your Windows machine until your task is done.

```
Browser UI <-> FastAPI backend <-> provider (Cloudflare Workers AI free / Anthropic Claude)
                                      |
                                      v
                          tools executed locally by Python
              (PowerShell, file read/write/list, URL fetch)
```

## Setup

```powershell
cd C:\Users\atili\ai-agent
py -m venv venv
.\venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # then edit .env with your credentials
.\venv\Scripts\uvicorn main:app --port 8080
```

Open http://127.0.0.1:8080

Note: on this machine port 8000 is taken by a WSL service, so use 8080.
Add `--reload` while developing to auto-restart on code changes.

## Credentials

### Cloudflare Workers AI (free, default)

1. Free account at https://dash.cloudflare.com
2. Account ID: dashboard home right sidebar (or Workers & Pages overview)
3. API token: profile icon -> My Profile -> API Tokens -> Create Token ->
   Custom token -> permission **Account / Workers AI / Edit**
4. Put both into `.env` (`CF_ACCOUNT_ID`, `CF_API_TOKEN`)

Free tier: 10,000 neurons/day (resets 00:00 UTC). Small models cost fewer.
If replies fail mentioning tools/function calling, switch `CF_MODEL` to one of
the alternatives listed in `.env.example`.

### Anthropic (optional upgrade)

Set `ANTHROPIC_API_KEY` and `PROVIDER=anthropic` in `.env`. Everything else
stays identical.

## Try these tasks

- "What files are in my Downloads folder?"
- "Make a folder called test-notes and write today's date into a file inside it"
- "Fetch example.com and summarize what it is"
- "Count how many .txt files are in this project"

## Safety model (defense in depth)

The agent has several independent safety layers:

1. **Command deny-list** - catastrophic patterns (format, diskpart, shutdown,
   `Remove-Item -Recurse`, registry HKLM writes, execution policy changes,
   download-and-execute chains...) are permanently blocked, even with approval.
2. **Path scoping** - file tools only operate inside `ALLOWED_PATHS`
   (semicolon-separated in `.env`). Enforced both before the LLM call and again
   inside each executor.
3. **Human-in-the-loop approvals** - risky tools (`run_command`, `write_file`)
    pause the agent and show you the exact command/arguments in the UI. Nothing
    executes until you click Approve. Denying tells the model to try another way.
4. **Timeouts** - shell commands are killed after their timeout (default 30s).
5. **Autonomous mode** (experts only) - set `REQUIRE_APPROVAL=false` to let the
   agent act without confirmation. The deny-list and path scope still apply.

Note: this is a hardening layer for a local learning tool, not a true sandbox.
A determined prompt-injection attempt may still produce unwanted-but-approved
actions, so read every approval card. Do not expose this app to the internet.

## Where things live

| File | Purpose |
|---|---|
| `main.py` | FastAPI web server, `/api/chat` + approval resume protocol |
| `agent/loop.py` | Agent state machine: think -> tools -> pause-for-approval -> resume |
| `agent/tools.py` | Tool definitions + local execution |
| `agent/guards.py` | Path scopes, command deny-list, risk classification |
| `agent/providers.py` | Cloudflare + Anthropic adapters behind one interface |
| `static/index.html` | Dashboard UI: tool cards, output viewers, approve/deny |
| `test_connection.py` | End-to-end smoke test (`venv\Scripts\python test_connection.py`) |

## Learning path

1. Read `agent/loop.py` first - it is the heart of every AI agent (~50 lines).
2. Add a new tool in `agent/tools.py` (schema + executor function) and ask the
   agent to use it. Ideas: open an app, take a screenshot, search a folder by
   content, append to a daily log file.
