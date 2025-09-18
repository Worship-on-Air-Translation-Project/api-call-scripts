import os
from pathlib import Path
from typing import Set, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request  # <-- added Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

# ------------ Setup ------------
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"

TRANSLATOR_ENDPOINT = os.getenv(
    "AZURE_TRANSLATOR_ENDPOINT",
    "https://api.cognitive.microsofttranslator.com",
)
TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY", "")
TRANSLATOR_REGION = os.getenv("AZURE_TRANSLATOR_REGION", "")

app = FastAPI()

# CORS (keep permissive for now; tighten if you add a custom domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # set to your domain(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------ Helpers ------------
def translate_sync(text: str, from_lang: str, to_lang: str) -> str:
    if not text.strip():
        return ""

    if not TRANSLATOR_KEY or not TRANSLATOR_REGION:
        return ("Error: Translator service not configured. "
                "Set AZURE_TRANSLATOR_KEY and AZURE_TRANSLATOR_REGION.")

    url = f"{TRANSLATOR_ENDPOINT.rstrip('/')}/translate"
    params = {"api-version": "3.0", "from": from_lang, "to": to_lang}
    headers = {
        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    payload = [{"text": text}]
    try:
        resp = requests.post(url, params=params, headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
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
        return f"Translation failed: {type(e).__name__}"

# ------------ Routes ------------
@app.get("/")
async def get_index():
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

# ---- Translation API (Text REST) ----
@app.post("/api/translate")
async def translate_text(req: Request):  # <-- changed signature
    """
    Accept JSON, form-encoded, or raw text bodies:
    - { "text": "...", "from": "en", "to": "ko" }
    - text=...&from=en&to=ko
    - plain text body (text only)
    """
    text = ""
    from_lang = "en"
    to_lang = "ko"

    # Try JSON first
    try:
        body = await req.json()
        if isinstance(body, dict):
            text = (body.get("text") or "").strip()
            from_lang = body.get("from", from_lang)
            to_lang = body.get("to", to_lang)
        elif isinstance(body, list) and body and isinstance(body[0], dict):
            # tolerate [{ text, from, to }]
            first = body[0]
            text = (first.get("text") or "").strip()
            from_lang = first.get("from", from_lang)
            to_lang = first.get("to", to_lang)
    except Exception:
        # Not JSON – try form
        try:
            form = await req.form()
            text = (form.get("text") or "").strip()
            from_lang = form.get("from", from_lang)
            to_lang = form.get("to", to_lang)
        except Exception:
            # Not form – use raw text
            raw = await req.body()
            text = raw.decode("utf-8", errors="ignore").strip()

    translated = await run_in_threadpool(translate_sync, text or "", from_lang, to_lang)
    return {"translation": translated}

# ---- WebSocket Broadcasting ----
clients: Set[WebSocket] = set()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
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

# Optional: run locally
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("translator_app:app", host="0.0.0.0", port=8000, reload=True)