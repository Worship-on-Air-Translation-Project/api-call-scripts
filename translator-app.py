import requests, uuid, json
import time, os
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk

# Load environment variables (API keys and regions)
load_dotenv()
translator_key = os.getenv("TRANSLATOR_KEY")
translator_region = os.getenv("TRANSLATOR_REGION")
speech_key = os.getenv("SPEECH_KEY")
speech_region = os.getenv("SPEECH_REGION")

# Translation API setup
translator_url = "https://api.cognitive.microsofttranslator.com/translate"
translator_params = {
    'api-version': '3.0',
    'from': 'en',
    'to': ['ko']  # You can add more languages here
}

# Helper function to build request headers
def get_translator_headers():
    return {
        'Ocp-Apim-Subscription-Key': translator_key,
        'Ocp-Apim-Subscription-Region': translator_region,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }

# Single translation request for full sentence
def translate_text(full_sentence):
    if not full_sentence.strip():
        return None  # Avoid sending empty requests
    body = [{'text': full_sentence}]

    # API call
    response = requests.post(
        translator_url,
        params=translator_params,
        headers=get_translator_headers(),
        json=body
    )
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Translation API Error {response.status_code}: {response.text}")
        return None

# Set up Azure Speech Recognizer for full-utterance recognition
speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
speech_config.speech_recognition_language = "en-US"
speech_config.output_format = speechsdk.OutputFormat.Detailed  # Optional: detailed result with confidence
recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config)

print("Speak a full sentence. Press Ctrl+C to stop.\n")

try:
    while True:
        print("Listening...")
        result = recognizer.recognize_once()

        # Process only if valid speech was recognized
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            spoken_text = result.text.strip()
            if spoken_text: # If text is not empty
                print(f"Recognized: {spoken_text}")
                translation_result = translate_text(spoken_text)
                if translation_result:
                    for t in translation_result[0]["translations"]:
                        print(f"[{t['to']}]: {t['text']}")
                print()
            else:
                print("Empty result.\n")

        # Speech recognizer didn't match any spoken input to valid speech
        elif result.reason == speechsdk.ResultReason.NoMatch:
            print("No recognizable speech.\n")

        # Recognition Process cancelled
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Canceled: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                print(f"Details: {cancellation_details.error_details}")
            break
        time.sleep(0.3)  # Slight delay to prevent fast-looping

except KeyboardInterrupt:
    print("\nTranslation session ended by user.")