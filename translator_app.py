import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pathlib import Path
from typing import List
import azure.cognitiveservices.speech as speechsdk

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get_index():
    return FileResponse(INDEX_PATH)


# ---- Translation API ----
@app.post("/api/translate")
async def translate_text(request: dict):
    text = request.get("text", "")
    from_lang = request.get("from", "en")
    to_lang = request.get("to", "ko")

    # Azure Translator setup
    speech_key = os.getenv("AZURE_SPEECH_KEY")
    service_region = os.getenv("AZURE_SERVICE_REGION")

    if not speech_key or not service_region:
        return {"translation": "Error: Azure credentials not set."}

    # Translator speech config
    translation_config = speechsdk.translation.SpeechTranslationConfig(
        subscription=speech_key, region=service_region
    )
    translation_config.speech_recognition_language = from_lang
    translation_config.add_target_language(to_lang)

    # Use text translation
    translator = speechsdk.translation.TranslationRecognizer(translation_config=translation_config)

    result = translator.recognize_once_async().get()
    if result.reason == speechsdk.ResultReason.TranslatedSpeech:
        translations = result.translations
        return {"translation": translations.get(to_lang, "Translation failed")}
    else:
        return {"translation": "Translation failed"}


# ---- WebSocket Broadcasting ----
clients: List[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Broadcast to all clients (including other clients)
            for client in clients:
                if client != websocket:
                    await client.send_text(data)
    except WebSocketDisconnect:
        clients.remove(websocket)