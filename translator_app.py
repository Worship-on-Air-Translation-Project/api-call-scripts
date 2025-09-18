import os
from pathlib import Path
from typing import Set

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

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

# ------------ Routes ------------
@app.get("/")
async def get_index():
    """Serve the SPA index with no-cache headers to avoid stale pages."""
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
    """Simple health check endpoint."""
    return JSONResponse({"ok": True})


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

    if not text.strip():
        return {"translation": ""}

    # Validate configuration; return friendly JSON (avoid 500s).
    if not TRANSLATOR_KEY or not TRANSLATOR_REGION:
        return {
            "translation": "Error: Translator service not configured. "
                           "Set AZURE_TRANSLATOR_KEY and AZURE_TRANSLATOR_REGION."
        }

    url = f"{TRANSLATOR_ENDPOINT.rstrip('/')}/translate"
    params = {"api-version": "3.0", "from": from_lang, "to": to_lang}
    headers = {
        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    payload = [{"text": text}]

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(url, params=params, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return {"translation": f"Translation failed ({resp.status})"}
                data = await resp.json()
        translated = (
            data[0]["translations"][0]["text"]
            if data and isinstance(data, list)
            and data[0].get("translations")
            else ""
        )
        return {"translation": translated}
    except Exception as e:
        # Avoid 500s—surface a readable error string to the client.
        return {"translation": f"Translation failed: {type(e).__name__}"}


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
    uvicorn.run("translator_app:app", host="0.0.0.0", port=8000, reload=True)