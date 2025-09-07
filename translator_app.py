import os
import requests
import uuid
import logging
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Set
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = FastAPI(title="Azure Translation API with Real-time Sharing")

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

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_info: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket, user_id: str, username: str = None):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_info[user_id] = {
            "username": username or f"User-{user_id[:8]}",
            "connected_at": datetime.now().isoformat(),
            "status": "connected"
        }
        
        # Notify all users about new connection
        await self.broadcast_user_update()
        logger.info(f"User {user_id} connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_info:
            del self.user_info[user_id]
        
        # Notify remaining users about disconnection
        await self.broadcast_user_update()
        logger.info(f"User {user_id} disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
                await self.disconnect(user_id)

    async def broadcast(self, message: dict, exclude_user: str = None):
        disconnected_users = []
        
        for user_id, connection in self.active_connections.items():
            if exclude_user and user_id == exclude_user:
                continue
                
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")
                disconnected_users.append(user_id)
        
        # Clean up disconnected users
        for user_id in disconnected_users:
            await self.disconnect(user_id)

    async def broadcast_user_update(self):
        user_list = [
            {"id": user_id, **info} 
            for user_id, info in self.user_info.items()
        ]
        
        message = {
            "type": "user_update",
            "users": user_list,
            "total_users": len(user_list)
        }
        
        await self.broadcast(message)

    def get_connection_count(self) -> int:
        return len(self.active_connections)

# Global connection manager
manager = ConnectionManager()

# Pydantic models
class TranslationRequest(BaseModel):
    text: str
    from_lang: str = "en"
    to_lang: str = "ko"

class TranslationResponse(BaseModel):
    translation: str
    original: str

class BroadcastTranslationRequest(BaseModel):
    text: str
    translation: str
    user_id: str
    username: str = None
    from_lang: str = "en"
    to_lang: str = "ko"

# Translation endpoint (existing)
@app.post("/api/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    """
    Translate text using Azure Translator API
    """
    logger.info(f"Translation request: {request.text[:50]}... from {request.from_lang} to {request.to_lang}")
    
    try:
        # Validate environment variables
        translator_key = os.getenv("TRANSLATOR_KEY")
        translator_region = os.getenv("TRANSLATOR_REGION")
        
        if not translator_key:
            logger.error("TRANSLATOR_KEY environment variable not set")
            raise HTTPException(status_code=500, detail="Translator API key not configured")
        
        if not translator_region:
            logger.error("TRANSLATOR_REGION environment variable not set")
            raise HTTPException(status_code=500, detail="Translator region not configured")
        
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
        response = requests.post(
            constructed_url, 
            params=params, 
            headers=headers, 
            json=body,
            timeout=30
        )
        
        if response.status_code != 200:
            error_text = response.text
            logger.error(f"Translation API error: {response.status_code} - {error_text}")
            raise HTTPException(
                status_code=response.status_code, 
                detail=f"Translation API error: {error_text}"
            )
        
        result = response.json()
        
        if result and len(result) > 0 and 'translations' in result[0]:
            translated_text = result[0]['translations'][0]['text']
            return TranslationResponse(
                translation=translated_text,
                original=request.text
            )
        else:
            logger.error(f"Unexpected translation response format: {result}")
            raise HTTPException(
                status_code=500, 
                detail=f"Unexpected translation response format: {result}"
            )
            
    except requests.RequestException as e:
        logger.error(f"Network error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Translation error: {str(e)}")

# New endpoint for broadcasting translations
@app.post("/api/broadcast-translation")
async def broadcast_translation(request: BroadcastTranslationRequest):
    """
    Broadcast translation to all connected WebSocket clients
    """
    try:
        message = {
            "type": "translation",
            "text": request.text,
            "translation": request.translation,
            "user_id": request.user_id,
            "username": request.username or f"User-{request.user_id[:8]}",
            "timestamp": datetime.now().isoformat(),
            "from_lang": request.from_lang,
            "to_lang": request.to_lang
        }
        
        # Broadcast to all connected clients
        await manager.broadcast(message)
        
        logger.info(f"Broadcasted translation from {request.username}: {request.text[:50]}...")
        
        return {"status": "broadcasted", "message": "Translation shared with all users"}
        
    except Exception as e:
        logger.error(f"Broadcast error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Broadcast error: {str(e)}")

# WebSocket endpoint
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, username: str = None):
    await manager.connect(websocket, user_id, username)
    
    try:
        # Send welcome message
        welcome_message = {
            "type": "welcome",
            "message": "Connected to live translation",
            "user_id": user_id,
            "total_users": manager.get_connection_count()
        }
        await manager.send_personal_message(welcome_message, user_id)
        
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                
                # Handle different message types
                if message.get("type") == "ping":
                    await manager.send_personal_message({"type": "pong"}, user_id)
                elif message.get("type") == "status_update":
                    # Update user status
                    if user_id in manager.user_info:
                        manager.user_info[user_id]["status"] = message.get("status", "connected")
                        await manager.broadcast_user_update()
                        
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received from {user_id}: {data}")
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
    finally:
        await manager.disconnect(user_id)

# Status endpoints
@app.get("/api/status")
def get_status():
    return {
        "status": "healthy",
        "active_connections": manager.get_connection_count(),
        "users": list(manager.user_info.keys())
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Debug endpoint
@app.get("/debug/env")
def check_env():
    """Debug endpoint to check environment variables (remove in production)"""
    return {
        "translator_key_set": bool(os.getenv("TRANSLATOR_KEY")),
        "translator_region_set": bool(os.getenv("TRANSLATOR_REGION")),
        "translator_region": os.getenv("TRANSLATOR_REGION")
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")