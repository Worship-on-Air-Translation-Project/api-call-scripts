import azure.cognitiveservices.speech as speechsdk
import os
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import aiohttp
import json

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"
STATIC_DIR = BASE_DIR / "static"

load_dotenv()
speech_key = os.getenv("SPEECH_KEY")
speech_region = os.getenv("SPEECH_REGION")
translator_key = os.getenv("TRANSLATOR_KEY")
translator_region = os.getenv("TRANSLATOR_REGION")
translator_endpoint = os.getenv("TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com")

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
    allow_origins=["*"],  # Change to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket broadcaster ---
class ConnectionManager:
    def __init__(self):
        self.active = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, message: str):
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_stream(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive / dummy read
    except:
        manager.disconnect(ws)

# --- Azure Speech token for browser ---
@app.post("/speech/token", response_class=PlainTextResponse, include_in_schema=False)
async def speech_token():
    if not (speech_key and speech_region):
        return PlainTextResponse("Missing SPEECH_KEY/REGION", status_code=500)
    url = f"https://{speech_region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = {"Ocp-Apim-Subscription-Key": speech_key}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers) as r:
            r.raise_for_status()
            return await r.text()

# --- Translation endpoint ---
async def translate_text(text: str, lang_from: str, lang_to: str) -> str:
    if not (translator_key and translator_region):
        return text  # echo if keys missing
    url = f"{translator_endpoint}/translate"
    params = {"api-version": "3.0", "to": lang_to}
    if lang_from: params["from"] = lang_from
    headers = {
        "Ocp-Apim-Subscription-Key": translator_key,
        "Ocp-Apim-Subscription-Region": translator_region,
        "Content-Type": "application/json"
    }
    payload = [{"Text": text}]
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params, headers=headers, json=payload) as r:
            r.raise_for_status()
            data = await r.json()
            return data[0]["translations"][0]["text"]

@app.post("/publish", include_in_schema=False)
async def publish(payload: dict):
    text = (payload.get("text") or "").strip()
    lang_from = payload.get("from", "en")
    lang_to = payload.get("to", "ko")
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=400)
    translated = await translate_text(text, lang_from, lang_to)
    message = json.dumps({"transcript": text, "translation": translated})
    await manager.broadcast(message)
    return {"ok": True}

# --- Legacy WebSocket translation using Azure SDK (optional, keeps original functionality) ---
@app.websocket("/ws/translate")
async def translate_ws(websocket: WebSocket):
    await websocket.accept()
    translation_config = speechsdk.translation.SpeechTranslationConfig(subscription=speech_key, region=speech_region)
    translation_config.speech_recognition_language = "en-US"
    translation_config.add_target_language("ko")

    stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    recognizer = speechsdk.translation.TranslationRecognizer(translation_config=translation_config, audio_config=audio_config)

    loop = asyncio.get_event_loop()
    results_queue = asyncio.Queue()

    def handle_result(evt: speechsdk.translation.TranslationRecognitionEventArgs):
        if evt.result.reason == speechsdk.ResultReason.TranslatedSpeech:
            payload = {"transcript": evt.result.text, "translation": evt.result.translations.get("ko", "")}
            asyncio.run_coroutine_threadsafe(results_queue.put(payload), loop)

    recognizer.recognized.connect(handle_result)
    recognizer.start_continuous_recognition_async()

    try:
        while True:
            msg = await websocket.receive_bytes()
            stream.write(msg)
            while not results_queue.empty():
                payload = await results_queue.get()
                await websocket.send_json(payload)
    except Exception as e:
        await websocket.send_text(f"[Error] {str(e)}")
    finally:
        recognizer.stop_continuous_recognition_async()
        stream.close()
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)