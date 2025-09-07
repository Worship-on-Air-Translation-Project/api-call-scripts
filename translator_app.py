import os
import json
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk

load_dotenv()
speech_key = os.getenv("SPEECH_KEY")
speech_region = os.getenv("SPEECH_REGION")

app = FastAPI()

# Allow all origins (change in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws/translate")
async def websocket_translate(ws: WebSocket):
    await ws.accept()

    # Setup Azure Speech Translation
    translation_config = speechsdk.translation.SpeechTranslationConfig(
        subscription=speech_key,
        region=speech_region
    )
    translation_config.speech_recognition_language = "en-US"
    translation_config.add_target_language("ko")

    # Using PullAudioInputStream to receive audio from client
    pull_stream = speechsdk.audio.PullAudioInputStream(callback=None)
    audio_config = speechsdk.audio.AudioConfig(stream=pull_stream)
    recognizer = speechsdk.translation.TranslationRecognizer(
        translation_config, audio_config
    )

    await ws.send_text("[Connected] Send audio chunks in base64.")

    try:
        while True:
            msg = await ws.receive_text()
            data = json.loads(msg)

            if data.get("audio_base64"):
                audio_bytes = speechsdk.AudioDataStream.from_bytes(
                    bytes.fromhex(data["audio_base64"])
                )
                # Feed audio bytes to pull_stream here (requires a proper audio callback)
                # This is a simplified illustration

            # Optionally process recognition result (pseudo-code)
            result = recognizer.recognize_once()
            if result.reason == speechsdk.ResultReason.TranslatedSpeech:
                payload = {
                    "transcript": result.text,
                    "translation": result.translations["ko"]
                }
                await ws.send_json(payload)

    except Exception as e:
        await ws.send_text(f"[Error] {str(e)}")