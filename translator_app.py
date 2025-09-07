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

app = FastAPI(title="Worship On Air - Pastor-Congregation Translation")

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

# WebSocket Connection Manager with role support
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_info: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket, user_id: str, username: str = None):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        
        # Determine role based on username
        role = 'pastor' if username and username.lower() == 'joshua' else 'congregation'
        
        self.user_info[user_id] = {
            "username": username or f"User-{user_id[:8]}",
            "role": role,
            "connected_at": datetime.now().isoformat(),
            "status": "connected"
        }
        
        # Notify all users about new connection
        await self.broadcast_user_update()
        logger.info(f"{role.title()} '{username}' ({user_id}) connected. Total: {len(self.active_connections)}")

    async def disconnect(self, user_id: str):
        user_info = self.user_info.get(user_id, {})
        username = user_info.get('username', 'Unknown')
        role = user_info.get('role', 'unknown')
        
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_info:
            del self.user_info[user_id]
        
        # Notify remaining users about disconnection
        await self.broadcast_user_update()
        logger.info(f"{role.title()} '{username}' disconnected. Total: {len(self.active_connections)}")

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
        pastor_count = sum(1 for info in self.user_info.values() if info.get('role') == 'pastor')
        congregation_count = sum(1 for info in self.user_info.values() if info.get('role') == 'congregation')
        
        message = {
            "type": "user_update",
            "total_users": len(self.user_info),
            "pastor_count": pastor_count,
            "congregation_count": congregation_count,
            "pastor_online": pastor_count > 0
        }
        
        await self.broadcast(message)

    def get_connection_count(self) -> int:
        return len(self.active_connections)

    def get_pastor_count(self) -> int:
        return sum(1 for info in self.user_info.values() if info.get('role') == 'pastor')

    def is_pastor(self, user_id: str) -> bool:
        user_info = self.user_info.get(user_id, {})
        return user_info.get('role') == 'pastor'

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

# Translation endpoint
@app.post("/api/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    """
    Translate text using Azure Translator API
    """
    logger.info(f"Translation request: {request.text[:50]}...")
    
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
                detail=f"Unexpected translation response format"
            )
            
    except requests.RequestException as e:
        logger.error(f"Network error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Translation error: {str(e)}")

# Broadcast endpoint with pastor validation
@app.post("/api/broadcast-translation")
async def broadcast_translation(request: BroadcastTranslationRequest):
    """
    Broadcast translation to all connected clients (Pastor only)
    """
    try:
        # Validate that only pastor can broadcast
        if not manager.is_pastor(request.user_id):
            logger.warning(f"Non-pastor user {request.username} attempted to broadcast")
            raise HTTPException(status_code=403, detail="Only the pastor can broadcast translations")
        
        message = {
            "type": "translation",
            "text": request.text,
            "translation": request.translation,
            "user_id": request.user_id,
            "username": request.username,
            "timestamp": datetime.now().isoformat(),
            "from_lang": request.from_lang,
            "to_lang": request.to_lang
        }
        
        # Broadcast to all connected clients
        await manager.broadcast(message)
        
        logger.info(f"Pastor {request.username} broadcasted: {request.text[:50]}...")
        
        return {"status": "broadcasted", "message": "Translation shared with congregation"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Broadcast error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Broadcast error: {str(e)}")

# WebSocket endpoint
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, username: str = None):
    await manager.connect(websocket, user_id, username)
    
    try:
        # Get user role
        user_info = manager.user_info.get(user_id, {})
        role = user_info.get('role', 'congregation')
        
        # Send welcome message with role information
        welcome_message = {
            "type": "welcome",
            "message": f"Connected as {role}",
            "user_id": user_id,
            "role": role,
            "username": username,
            "total_users": manager.get_connection_count(),
            "pastor_count": manager.get_pastor_count()
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
    pastor_count = manager.get_pastor_count()
    congregation_count = manager.get_connection_count() - pastor_count
    
    return {
        "status": "healthy",
        "active_connections": manager.get_connection_count(),
        "pastor_count": pastor_count,
        "congregation_count": congregation_count,
        "pastor_online": pastor_count > 0
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")