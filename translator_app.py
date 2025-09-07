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

    translation_config = speechsdk.translation.SpeechTranslationConfig(
        subscription=speech_key,
        region=speech_region
    )
    translation_config.speech_recognition_language = "en-US"
    translation_config.add_target_language("ko")
    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
    translator = speechsdk.translation.TranslationRecognizer(
        translation_config=translation_config,
        audio_config=audio_config
    )

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