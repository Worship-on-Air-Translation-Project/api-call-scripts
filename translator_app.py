import os
import uuid
import logging
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Env ----------
load_dotenv()

AZURE_TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY", "")
AZURE_TRANSLATOR_REGION = os.getenv("AZURE_TRANSLATOR_REGION", "")
AZURE_TRANSLATOR_ENDPOINT = os.getenv(
    "AZURE_TRANSLATOR_ENDPOINT",
    "https://api.cognitive.microsofttranslator.com",
).rstrip("/")

# ---------- App ----------
app = FastAPI(title="Azure Translation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # tighten to your domain(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"

@app.get("/")
def serve_index():
    if not INDEX_PATH.exists():
        return JSONResponse({"error": "index.html not found at application root."}, status_code=500)
    # no-cache to avoid stale role-selection page
    return FileResponse(
        str(INDEX_PATH),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

class TranslationRequest(BaseModel):
    text: str
    from_lang: str = "en"
    to_lang: str = "ko"

class TranslationResponse(BaseModel):
    translation: str
    original: str

@app.post("/api/translate", response_model=TranslationResponse)
def translate_text(request: TranslationRequest):
    """
    Translate text using Azure Translator Text REST API.
    Uses env vars: AZURE_TRANSLATOR_KEY, AZURE_TRANSLATOR_REGION, AZURE_TRANSLATOR_ENDPOINT (optional).
    """
    logger.info("Translate: '%s...' (%s -> %s)", request.text[:50], request.from_lang, request.to_lang)

    # Validate configuration up front with friendly errors
    if not AZURE_TRANSLATOR_KEY:
        raise HTTPException(status_code=500, detail="Translator service not configured (AZURE_TRANSLATOR_KEY).")
    if not AZURE_TRANSLATOR_REGION:
        raise HTTPException(status_code=500, detail="Translator service not configured (AZURE_TRANSLATOR_REGION).")

    url = f"{AZURE_TRANSLATOR_ENDPOINT}/translate"
    params = {"api-version": "3.0", "from": request.from_lang, "to": request.to_lang}
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_TRANSLATOR_REGION,
        "Content-Type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    body = [{"text": request.text}]

    try:
        resp = requests.post(url, params=params, headers=headers, json=body, timeout=30)
        logger.info("Translator status=%s", resp.status_code)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Translation API error: {resp.text}")

        data = resp.json()
        translated = (
            data[0]["translations"][0]["text"]
            if isinstance(data, list) and data and data[0].get("translations")
            else ""
        )
        return TranslationResponse(translation=translated, original=request.text)

    except requests.RequestException as e:
        logger.exception("Network error calling Translator")
        raise HTTPException(status_code=500, detail=f"Network error: {e}")

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/debug/env")
def debug_env():
    # Safe debug (does not leak secrets)
    return {
        "endpoint": AZURE_TRANSLATOR_ENDPOINT,
        "key_set": bool(AZURE_TRANSLATOR_KEY),
        "region_set": bool(AZURE_TRANSLATOR_REGION),
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")