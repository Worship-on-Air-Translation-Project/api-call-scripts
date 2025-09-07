import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

app = FastAPI(title="Azure Translation API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the HTML file
BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"

@app.get("/")
def serve_index():
    return FileResponse(str(INDEX_PATH))

class TranslationRequest(BaseModel):
    text: str
    from_lang: str = "en"
    to_lang: str = "ko"

class TranslationResponse(BaseModel):
    translation: str
    original: str

@app.post("/api/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    """
    Translate text using Azure Translator API
    """
    try:
        # Azure Translator configuration
        translator_key = os.getenv("TRANSLATOR_KEY")
        translator_region = os.getenv("TRANSLATOR_REGION")
        
        if not translator_key:
            raise HTTPException(status_code=500, detail="Translator API key not configured")
        
        # Azure Translator endpoint
        endpoint = "https://api.cognitive.microsofttranslator.com"
        path = "/translate"
        constructed_url = endpoint + path
        
        params = {
            'api-version': '3.0',
            'from': request.from_lang,
            'to': request.to_lang
        }
        
        headers = {
            'Ocp-Apim-Subscription-Key': translator_key,
            'Ocp-Apim-Subscription-Region': translator_region,
            'Content-type': 'application/json',
            'X-ClientTraceId': str(uuid.uuid4())
        }
        
        body = [{
            'text': request.text
        }]
        
        # Make the translation request
        response = requests.post(constructed_url, params=params, headers=headers, json=body)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Translation API error")
        
        result = response.json()
        
        if result and len(result) > 0 and 'translations' in result[0]:
            translated_text = result[0]['translations'][0]['text']
            return TranslationResponse(
                translation=translated_text,
                original=request.text
            )
        else:
            raise HTTPException(status_code=500, detail="Unexpected translation response format")
            
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation error: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)