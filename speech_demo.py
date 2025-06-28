from dotenv import load_dotenv
import os
import azure.cognitiveservices.speech as speechsdk

# Load variables from .env file
load_dotenv()

speech_key = os.getenv("SPEECH_KEY")
service_region = os.getenv("SPEECH_REGION")

if not speech_key or not service_region:
    raise ValueError("Missing SPEECH_KEY or SPEECH_REGION in .env file")

# Set up config and audio input
speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
audio_config = speechsdk.audio.AudioConfig(filename="speech_sample.wav")

# Initialize recognizer
speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
print("recognizer initialized")

# Recognize speech
result = speech_recognizer.recognize_once()
print("speech recognized")

# Output result
if result.reason == speechsdk.ResultReason.RecognizedSpeech:
    print("Recognized speech:", result.text)
else:
    print("Speech recognition failed:", result.reason)
