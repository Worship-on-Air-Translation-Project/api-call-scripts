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

    # Create a push stream for audio
    stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    recognizer = speechsdk.translation.TranslationRecognizer(
        translation_config=translation_config,
        audio_config=audio_config
    )

    loop = asyncio.get_event_loop()
    results_queue = asyncio.Queue()

    # Event handler for recognition results
    def handle_result(evt: speechsdk.translation.TranslationRecognitionEventArgs):
        if evt.result.reason == speechsdk.ResultReason.TranslatedSpeech:
            payload = {
                "transcript": evt.result.text,
                "translation": evt.result.translations.get("ko", "")
            }
            asyncio.run_coroutine_threadsafe(results_queue.put(payload), loop)

    recognizer.recognized.connect(handle_result)

    # Start continuous recognition
    recognizer.start_continuous_recognition_async()

    try:
        while True:
            # Receive mic chunk from browser
            msg = await websocket.receive_bytes()
            stream.write(msg)

            # Check if there are translation results ready
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
    import os, uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)