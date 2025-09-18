import os
import uuid
import logging
from pathlib import Path
from typing import Set, Optional, Dict, Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

# ------------ Logging ------------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("translator_app")

# ------------ Setup ------------
# Load a local .env for local dev; on Azure, values come from App Settings.
load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"

def getenv_any(*names: str, default: str = "") -> str:
    """Return the first set environment variable among names."""
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default

# Accept both naming schemes to avoid config mismatches
TRANSLATOR_ENDPOINT = getenv_any(
    "AZURE_TRANSLATOR_ENDPOINT", "TRANSLATOR_ENDPOINT",
    default="https://api.cognitive.microsofttranslator.com",
)
TRANSLATOR_KEY = getenv_any("AZURE_TRANSLATOR_KEY", "TRANSLATOR_KEY", default="")
TRANSLATOR_REGION = getenv_any("AZURE_TRANSLATOR_REGION", "TRANSLATOR_REGION", default="")

app = FastAPI(title="Worship On Air - Translator")

# CORS (wide-open for now; restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------ Helpers ------------
def config_status() -> Dict[str, Any]:
    """For internal checks and the /debug/env endpoint."""
    return {
        "endpoint": TRANSLATOR_ENDPOINT,
        "AZURE_TRANSLATOR_KEY_set": bool(os.getenv("AZURE_TRANSLATOR_KEY")),
        "TRANSLATOR_KEY_set": bool(os.getenv("TRANSLATOR_KEY")),
        "AZURE_TRANSLATOR_REGION_set": bool(os.getenv("AZURE_TRANSLATOR_REGION")),
        "TRANSLATOR_REGION_set": bool(os.getenv("TRANSLATOR_REGION")),
    }

def translate_sync(text: str, from_lang: str, to_lang: str) -> str:
    """
    Blocking call to Azure Translator Text REST API using 'requests'.
    Returns translated text OR a friendly error string. Never raises.
    """
    if not text.strip():
        return ""

    if not TRANSLATOR_KEY or not TRANSLATOR_REGION:
        missing = []
        if not TRANSLATOR_KEY:
            missing.append("key")
        if not TRANSLATOR_REGION:
            missing.append("region")
        log.warning("Translator config missing: %s | %s", missing, config_status())
        return ("Error: Translator service not configured. "
                "Set AZURE_TRANSLATOR_KEY/REGION or TRANSLATOR_KEY/REGION.")

    url = f"{TRANSLATOR_ENDPOINT.rstrip('/')}/translate"
    params = {"api-version": "3.0", "from": from_lang, "to": to_lang}
    headers = {
        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
        "Content-Type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    payload = [{"text": text}]

    try:
        resp = requests.post(url, params=params, headers=headers, json=payload, timeout=15)
        if resp.status_code != 200:
            log.error("Translation failed: status=%s body=%s", resp.status_code, resp.text[:500])
            return f"Translation failed ({resp.status_code})"
        data = resp.json()
        translated: Optional[str] = (
            data[0]["translations"][0]["text"]
            if isinstance(data, list)
            and data
            and isinstance(data[0], dict)
            and data[0].get("translations")
            else ""
        )
        return translated or ""
    except requests.RequestException as e:
        log.exception("Network error calling Translator")
        return f"Translation failed: {type(e).__name__}"

# ------------ Routes ------------
@app.get("/")
async def get_index():
    """Serve the SPA index with no-cache headers to avoid stale pages."""
    if not INDEX_PATH.exists():
        return JSONResponse(
            {"error": "index.html not found at application root."},
            status_code=404,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return FileResponse(
        INDEX_PATH,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/healthz")
async def healthz():
    return JSONResponse({"ok": True})

@app.get("/debug/env")
async def debug_env():
    """Debug ONLY: verify which env vars are actually present (remove in prod)."""
    return config_status()

# ---- Translation API (Text REST, no server mic) ----
@app.post("/api/translate")
async def translate_text(request: dict):
    """
    Translate plain text using Azure Translator Text REST API.
    Expects: {"text": "...", "from": "en", "to": "ko"}
    """
    text = (request or {}).get("text", "") or ""
    from_lang = (request or {}).get("from", "en")
    to_lang = (request or {}).get("to", "ko")

    translated = await run_in_threadpool(translate_sync, text, from_lang, to_lang)
    return {"translation": translated}

# ---- WebSocket Broadcasting ----
# Keep a set of all connected clients in this process.
clients: Set[WebSocket] = set()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            # Admin sends JSON: {"transcript": "...", "translation": "..."}
            data = await websocket.receive_text()
            # Broadcast to all *other* clients
            dead: Set[WebSocket] = set()
            for client in list(clients):
                if client is websocket:
                    continue
                try:
                    await client.send_text(data)
                except Exception:
                    dead.add(client)
            for d in dead:
                clients.discard(d)
    except WebSocketDisconnect:
        clients.discard(websocket)
    except Exception:
        clients.discard(websocket)

# Optional: allow running locally with `python translator_app.py`
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    log.info("Starting dev server on 0.0.0.0:%s", port)
    uvicorn.run("translator_app:app", host="0.0.0.0", port=port, reload=True)