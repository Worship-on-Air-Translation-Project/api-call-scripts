import azure.cognitiveservices.speech as speechsdk
import os
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import uvicorn

# Load env vars
load_dotenv()
speech_key = os.getenv("SPEECH_KEY")
speech_region = os.getenv("SPEECH_REGION")

app = FastAPI()

# Allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve index.html directly
@app.get("/")
async def get_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

# WebSocket route
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
    uvicorn.run(app, host="0.0.0.0", port=8000)