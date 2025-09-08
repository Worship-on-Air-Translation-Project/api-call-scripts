import os, asyncio, json
from typing import List, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import aiohttp

app = FastAPI()

# ========= Config =========
HOST_PUBLISH_TOKEN = os.getenv("HOST_PUBLISH_TOKEN", "")  # set this before running
DEFAULT_SRC = os.getenv("DEFAULT_SRC_LANG", "en")
DEFAULT_DST = os.getenv("DEFAULT_DST_LANG", "ko")
# Use either AZURE_* or plain names — set whichever you prefer
TRANSLATOR_KEY      = os.getenv("AZURE_TRANSLATOR_KEY") or os.getenv("TRANSLATOR_KEY", "")
TRANSLATOR_REGION   = os.getenv("AZURE_TRANSLATOR_REGION") or os.getenv("TRANSLATOR_REGION", "")
# For global endpoint use: https://api.cognitive.microsofttranslator.com
# For regional endpoint use: https://<your-region>.api.cognitive.microsofttranslator.com
TRANSLATOR_ENDPOINT = os.getenv("AZURE_TRANSLATOR_ENDPOINT") or os.getenv("TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com")

# ========= Simple SSE Hub =========
subscribers: List[asyncio.Queue] = []

async def broadcast(payload: Dict[str, Any]):
    dead = []
    for q in subscribers:
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for q in dead:
        try: subscribers.remove(q)
        except ValueError: pass

@app.get("/")
async def viewer():
    return FileResponse("index.html")

@app.get("/host")
async def host_page():
    here = os.path.dirname(os.path.abspath(__file__))
    return FileResponse(os.path.join(here, "host.html"))

@app.get("/stream")
async def stream():
    # Server-Sent Events
    async def event_gen():
        q: asyncio.Queue = asyncio.Queue()
        subscribers.append(q)
        try:
            # send a hello so the client shows “connected”
            yield "event: hello\ndata: {}\n\n"
            while True:
                item = await q.get()
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            # client disconnected
            pass
        finally:
            try: subscribers.remove(q)
            except ValueError: pass

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)

async def translate_text(text: str, src: str, dst: str) -> str:
    """
    Azure Translator (Text Translation v3) over REST.
    Returns translated text, or "" on error.
    """
    if not TRANSLATOR_KEY or not TRANSLATOR_REGION:
        # Fail-open so the viewer still shows STT if Translator isn’t configured yet.
        return text

    url = TRANSLATOR_ENDPOINT.rstrip("/") + "/translate"
    params = {"api-version": "3.0", "from": src, "to": dst}
    headers = {
        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
        "Content-Type": "application/json"
    }
    body = [{"Text": text}]

    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, params=params, headers=headers, json=body) as resp:
                if resp.status != 200:
                    detail = await resp.text()
                    print("Translator error:", resp.status, detail)
                    return ""
                data = await resp.json()
                return data[0]["translations"][0]["text"]
    except Exception as e:
        print("Translator exception:", e)
        return ""


@app.post("/publish")
async def publish(req: Request):
    # Simple bearer gate so only host can publish
    if not HOST_PUBLISH_TOKEN:
        raise HTTPException(status_code=500, detail="Server missing HOST_PUBLISH_TOKEN")
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token>")
    if auth.split(" ", 1)[1].strip() != HOST_PUBLISH_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid publish token")

    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "reason": "empty text"}

    src = (body.get("from") or DEFAULT_SRC).strip()
    dst = (body.get("to")   or DEFAULT_DST).strip()

    try:
        tr = await translate_text(text, src, dst)
    except Exception as e:
        tr = ""
        print("Translate error:", e)

    payload = {"transcript": text, "translation": tr}
    await broadcast(payload)
    return {"ok": True}
