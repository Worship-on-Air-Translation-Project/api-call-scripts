import os
import json
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"
STATIC_DIR = BASE_DIR / "static"

load_dotenv()

# Azure keys
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
TRANSLATOR_KEY = os.getenv("TRANSLATOR_KEY")
TRANSLATOR_REGION = os.getenv("TRANSLATOR_REGION")
TRANSLATOR_ENDPOINT = os.getenv("TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com")

app = FastAPI()

if STATIC_DIR.exists() and STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(str(INDEX_PATH))

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Broadcast manager for all connected clients
class ConnectionManager:
    def __init__(self):
        self.active_clients = set()
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_clients.add(ws)
    def disconnect(self, ws: WebSocket):
        self.active_clients.discard(ws)
    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active_clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

@app.post("/speech/token", include_in_schema=False)
async def speech_token():
    assert SPEECH_KEY and SPEECH_REGION, "Missing SPEECH_KEY or SPEECH_REGION"
    import aiohttp
    url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.text()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive
    except Exception:
        manager.disconnect(ws)

async def translate_text(text: str, lang_from: str = "en", lang_to: str = "ko") -> str:
    if not (TRANSLATOR_KEY and TRANSLATOR_REGION):
        return text
    import aiohttp
    url = f"{TRANSLATOR_ENDPOINT}/translate"
    params = {"api-version": "3.0", "to": lang_to}
    if lang_from: params["from"] = lang_from
    headers = {
        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    payload = [{"Text": text}]
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data[0]["translations"][0]["text"]

@app.post("/publish", include_in_schema=False)
async def publish(payload: dict):
    text = (payload.get("text") or "").strip()
    lang_from = payload.get("from", "en")
    lang_to = payload.get("to", "ko")
    if not text:
        return {"error": "empty text"}
    translated = await translate_text(text, lang_from, lang_to)
    message = {"transcript": text, "translation": translated}
    await manager.broadcast(message)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn, os
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
