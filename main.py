import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent.loop import advance, decide, start

app = FastAPI(title="AI Agent")


def _approvals_required():
    return os.environ.get("REQUIRE_APPROVAL", "true").lower() not in ("false", "0", "no")


class ChatRequest(BaseModel):
    message: str | None = None
    history: list = []
    resume: dict | None = None


class SettingsRequest(BaseModel):
    require_approval: bool


@app.get("/")
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/provider")
def provider_info():
    provider = os.environ.get("PROVIDER", "cloudflare").lower()
    if provider == "anthropic":
        model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    else:
        model = os.environ.get("CF_MODEL", "@cf/zai-org/glm-4.7-flash")
    allowed = os.environ.get(
        "ALLOWED_PATHS",
        str(Path(__file__).parent),
    )
    first_root = [p.strip() for p in allowed.split(";") if p.strip()]
    return {
        "provider": provider,
        "model": model,
        "home": str(Path.home()),
        "approvals_required": _approvals_required(),
        "workspace": first_root[0] if first_root else str(Path(__file__).parent),
        "allowed_paths": allowed,
    }


@app.post("/api/settings")
def update_settings(request: SettingsRequest):
    os.environ["REQUIRE_APPROVAL"] = "true" if request.require_approval else "false"
    return {"approvals_required": _approvals_required()}


@app.post("/api/chat")
def chat_endpoint(request: ChatRequest):
    try:
        if request.resume is not None:
            state = request.resume.get("state") or {}
            call = request.resume.get("tool_call") or {}
            approved = bool(request.resume.get("approved"))
            if not state or not call:
                return {"status": "error", "reply": "Malformed resume payload.", "error": True}
            event = decide(state, approved)
        elif request.message and request.message.strip():
            state = start(request.message.strip(), request.history)
            event = advance(state)
        else:
            return {"status": "error", "reply": "Empty message.", "error": True}

        rounds = 0
        while event["type"] == "approval_required" and not _approvals_required() and rounds < 20:
            event = decide(state, approved=True)
            rounds += 1

        if event["type"] == "approval_required":
            return {
                "status": "approval_required",
                "tool_call": event["tool_call"],
                "events": state.get("feed", []),
                "usage": state.get("usage", {}),
                "state": state,
            }
        return {
            "status": "done",
            "reply": event["reply"],
            "events": state.get("feed", []),
            "usage": state.get("usage", {}),
        }
    except RuntimeError as exc:
        return {"status": "error", "reply": f"Configuration problem: {exc}", "error": True}
    except Exception as exc:
        return {"status": "error", "reply": f"Agent error: {type(exc).__name__}: {exc}", "error": True}
