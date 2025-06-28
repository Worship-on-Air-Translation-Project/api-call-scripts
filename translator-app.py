import requests, uuid, json
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# Get key and region from .env
key = os.getenv("TRANSLATOR_KEY")
location = os.getenv("TRANSLATOR_REGION")

# Keep endpoint hardcoded
endpoint = "https://api.cognitive.microsofttranslator.com"

if not key or not location:
    raise ValueError("Missing TRANSLATOR_KEY or TRANSLATOR_REGION in .env file")

# Set path and full URL
path = '/translate'
constructed_url = endpoint + path

# Query parameters
params = {
    'api-version': '3.0',
    'from': 'en',
    'to': ['ko', 'zu']
}

# Request headers
headers = {
    'Ocp-Apim-Subscription-Key': key,
    'Ocp-Apim-Subscription-Region': location,
    'Content-type': 'application/json',
    'X-ClientTraceId': str(uuid.uuid4())
}

# Text to translate
body = [{
    'text': 'I would really like to drive your car around the block a few times!'
}]

# Send request
request = requests.post(constructed_url, params=params, headers=headers, json=body)
response = request.json()

# Print translated output
print(json.dumps(response, sort_keys=True, ensure_ascii=False, indent=4, separators=(',', ': ')))