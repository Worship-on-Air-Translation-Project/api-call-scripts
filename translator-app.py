import azure.cognitiveservices.speech as speechsdk
import time
import os
from dotenv import load_dotenv

#  Load environment variables
load_dotenv()
speech_key = os.getenv("SPEECH_KEY")
speech_region = os.getenv("SPEECH_REGION")

# Set up speech translation config
translation_config = speechsdk.translation.SpeechTranslationConfig(
    subscription=speech_key,
    region=speech_region
)

# Define input language and target translation language
translation_config.speech_recognition_language = "en-US"
translation_config.add_target_language("ko")  # You can add more if needed

# Set up recognizer using default microphone
audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
translator = speechsdk.translation.TranslationRecognizer(
    translation_config=translation_config,
    audio_config=audio_config
)

print("Speak a sentence in English. Press Ctrl+C to stop.\n")

# Main recognition loop
try:
    while True:
        print("Listening...")

        # Recognize one full utterance
        result = translator.recognize_once() # API call

        # Handle result
        if result.reason == speechsdk.ResultReason.TranslatedSpeech:
            print(f"Recognized: {result.text}")
            print(f"Translated [ko]: {result.translations['ko']}")
            print()

        # No valid speech detected from input
        elif result.reason == speechsdk.ResultReason.NoMatch:
            print("No recognizable speech.\n")

        # Recognition cancelled due to interruption
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Canceled: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                print(f"Error details: {cancellation_details.error_details}")
            break

        time.sleep(0.3)

except KeyboardInterrupt:
    print("\nTranslation session ended by user.")