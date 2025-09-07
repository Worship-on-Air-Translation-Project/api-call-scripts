import azure.cognitiveservices.speech as speechsdk
import os
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

import uvicorn

# --- add near your imports ---
import os, json, aiohttp
from typing import Set
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, JSONResponse

SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
TRANSLATOR_KEY = os.getenv("TRANSLATOR_KEY")
TRANSLATOR_REGION = os.getenv("TRANSLATOR_REGION")
TRANSLATOR_ENDPOINT = os.getenv("TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com")

# --- expose region to client (so index.html doesn’t hard-code it) ---
@app.get("/speech/config", include_in_schema=False)
def speech_cfg():
    return {"region": SPEECH_REGION or ""}

# --- token endpoint for browser Speech SDK (keeps key off the page) ---
@app.post("/speech/token", response_class=PlainTextResponse, include_in_schema=False)
async def speech_token():
    assert SPEECH_KEY and SPEECH_REGION, "Missing SPEECH_KEY/REGION"
    url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}
    async with aiohttp.ClientSession() as s:
        async with s.post(url, headers=headers) as r:
            r.raise_for_status()
            return await r.text()

# --- simple broadcast hub so all viewers see the same stream ---
class ConnectionManager:
    def __init__(self) -> None:
        self.active: Set[WebSocket] = set()
    async def connect(self, ws: WebSocket):
        await ws.accept(); self.active.add(ws)
    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)
    async def broadcast(self, text: str):
        dead = []
        for ws in list(self.active):
            try: await ws.send_text(text)
            except Exception: dead.append(ws)
        for ws in dead: self.disconnect(ws)

manager = ConnectionManager()

@app.websocket("/ws")
async def ws_stream(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # ignore client pings
    except WebSocketDisconnect:
        manager.disconnect(ws)

# --- translate on server, then broadcast ---
async def translate_text(text: str, lang_from: str, lang_to: str) -> str:
    if not (TRANSLATOR_KEY and TRANSLATOR_REGION):
        return text  # fallback: echo if Translator not configured
    url = f"{TRANSLATOR_ENDPOINT}/translate"
    params = {"api-version": "3.0", "to": lang_to}
    if lang_from: params["from"] = lang_from
    headers = {
        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    payload = [{"Text": text}]
    async with aiohttp.ClientSession() as s:
        async with s.post(url, params=params, headers=headers, json=payload) as r:
            r.raise_for_status()
            data = await r.json()
            return data[0]["translations"][0]["text"]

@app.post("/publish", include_in_schema=False)
async def publish(payload: dict):
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=400)
    lang_from = payload.get("from") or "en"
    lang_to   = payload.get("to")   or "ko"
    translated = await translate_text(text, lang_from, lang_to)
    await manager.broadcast(json.dumps({"transcript": text, "translation": translated}))
    return {"ok": True}


# Load env vars
load_dotenv()
speech_key = os.getenv("SPEECH_KEY")
speech_region = os.getenv("SPEECH_REGION")

app = FastAPI()

if STATIC_DIR.exists() and STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(str(INDEX_PATH))

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}

# Allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws/translate")
async def translate_ws(websocket: WebSocket):
    await websocket.accept()

    await websocket.send_text("Listening...")

    try:
        while True:
            result = translator.recognize_once()

            if result.reason == speechsdk.ResultReason.TranslatedSpeech:
                original_text = result.text  # English transcript
                translated_text = result.translations['ko']  # Korean translation

                # Send both back in JSON format so frontend can separate them
                payload = {
                    "transcript": original_text,
                    "translation": translated_text
                }
                await websocket.send_json(payload)

            elif result.reason == speechsdk.ResultReason.NoMatch:
                await websocket.send_text("[No speech detected]")

            elif result.reason == speechsdk.ResultReason.Canceled:
                await websocket.send_text("[Canceled]")
                break

            await asyncio.sleep(0.5)

    except Exception as e:
        await websocket.send_text(f"[Error] {str(e)}")

if __name__ == "__main__":
    import os, uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)