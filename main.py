from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
import requests
import uuid
from datetime import datetime
import logging
import os
import json
from typing import List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Instagram Clone API - No Firebase Admin")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Firebase Configuration
FIREBASE_CONFIG = {
    "project_id": "instaclone-aura444",
    "database_url": "https://instaclone-aura444-default-rtdb.firebaseio.com"
}

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class TelegramUploadError(Exception):
    pass

class FirebaseError(Exception):
    pass

class FirebaseRESTClient:
    def __init__(self, database_url):
        self.database_url = database_url.rstrip('/')
    
    def set_data(self, path, data):
        """Write data to Firebase using REST API"""
        try:
            url = f"{self.database_url}/{path}.json"
            response = requests.put(url, json=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Firebase write failed: {e}")
            raise FirebaseError(f"Failed to write to Firebase: {e}")
    
    def get_data(self, path):
        """Read data from Firebase using REST API"""
        try:
            url = f"{self.database_url}/{path}.json"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Firebase read failed: {e}")
            raise FirebaseError(f"Failed to read from Firebase: {e}")
    
    def push_data(self, path, data):
        """Push data to a list in Firebase"""
        try:
            url = f"{self.database_url}/{path}.json"
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Firebase push failed: {e}")
            raise FirebaseError(f"Failed to push to Firebase: {e}")
    
    def delete_data(self, path):
        """Delete data from Firebase"""
        try:
            url = f"{self.database_url}/{path}.json"
            response = requests.delete(url, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Firebase delete failed: {e}")
            raise FirebaseError(f"Failed to delete from Firebase: {e}")

# Initialize Firebase REST client
firebase_client = FirebaseRESTClient(FIREBASE_CONFIG["database_url"])

async def verify_user_token(token: str = Form(...)):
    """Basic user verification"""
    if not token or token.strip() == "":
        raise HTTPException(status_code=401, detail="Invalid token")
    return token

@app.post("/upload/")
async def upload_media(
    background_tasks: BackgroundTasks,
    user_id: str = Form(...),
    caption: str = Form(""),
    file: UploadFile = None,
    token: str = Depends(verify_user_token)
):
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Telegram bot token not configured")
    
    try:
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'video/mp4', 'image/webp']
        if file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"File type not allowed. Got {file.content_type}")
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Validate file size (10MB limit)
        if file_size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB")
        
        # Upload to Telegram
        tg_file_id = await upload_to_telegram(file_content, file.filename, file.content_type)
        
        # Generate unique ID for the post
        post_id = str(uuid.uuid4())
        
        # Prepare metadata
        feed_item = {
            "post_id": post_id,
            "user_id": user_id,
            "media_file_id": tg_file_id,
            "filename": file.filename,
            "file_type": file.content_type,
            "caption": caption,
            "timestamp": datetime.utcnow().isoformat(),
            "file_size": file_size,
            "likes": 0,
            "comments": 0,
            "user_profile": f"https://api.dicebear.com/7.x/avataaars/svg?seed={user_id}"
        }
        
        # Store metadata in Firebase using REST API
        await store_in_firebase(user_id, post_id, feed_item)
        
        # Background task for additional processing
        background_tasks.add_task(process_upload_analytics, user_id, post_id)
        
        return {
            "status": "success", 
            "file_id": tg_file_id,
            "post_id": post_id,
            "message": "Media uploaded successfully",
            "user_id": user_id
        }
        
    except TelegramUploadError as e:
        logger.error(f"Telegram upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload to Telegram")
    except FirebaseError as e:
        logger.error(f"Firebase storage failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to store metadata")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/feed/")
async def get_feed(limit: int = 20, offset: int = 0):
    """Retrieve feed posts with pagination"""
    try:
        # Get all posts from timeline
        timeline_data = firebase_client.get_data("timeline") or {}
        
        if not timeline_data:
            return {"posts": [], "has_more": False, "total": 0}
        
        # Convert to list and sort by timestamp
        posts = []
        for post_id, post_data in timeline_data.items():
            if post_data:
                posts.append(post_data)
        
        # Sort by timestamp descending
        posts.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # Apply pagination
        paginated_posts = posts[offset:offset + limit]
        
        # Generate Telegram file URLs for client-side access
        for post in paginated_posts:
            file_id = post.get('media_file_id', '')
            if file_id and TELEGRAM_BOT_TOKEN:
                post['media_url'] = await get_telegram_file_url(file_id)
        
        return {
            "posts": paginated_posts,
            "has_more": len(posts) > offset + limit,
            "total": len(posts)
        }
        
    except Exception as e:
        logger.error(f"Feed retrieval failed: {e}")
        return {"posts": [], "has_more": False, "total": 0, "error": str(e)}

@app.get("/user-posts/{user_id}")
async def get_user_posts(user_id: str, limit: int = 20, offset: int = 0):
    """Get posts for a specific user"""
    try:
        user_posts = firebase_client.get_data(f"feeds/{user_id}") or {}
        
        if not user_posts:
            return {"posts": [], "has_more": False, "total": 0}
        
        posts = list(user_posts.values())
        posts.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        paginated_posts = posts[offset:offset + limit]
        
        for post in paginated_posts:
            file_id = post.get('media_file_id', '')
            if file_id and TELEGRAM_BOT_TOKEN:
                post['media_url'] = await get_telegram_file_url(file_id)
        
        return {
            "posts": paginated_posts,
            "has_more": len(posts) > offset + limit,
            "total": len(posts)
        }
        
    except Exception as e:
        logger.error(f"User posts retrieval failed: {e}")
        return {"posts": [], "has_more": False, "total": 0, "error": str(e)}

async def upload_to_telegram(file_content: bytes, filename: str, content_type: str) -> str:
    """Upload media to Telegram and return file_id"""
    try:
        # For images, use sendPhoto API for better quality
        if content_type.startswith('image/'):
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            files = {"photo": (filename, file_content, content_type)}
        else:
            # For documents/videos
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
            files = {"document": (filename, file_content, content_type)}
        
        data = {"chat_id": TELEGRAM_CHAT_ID} if TELEGRAM_CHAT_ID else {}
        
        response = requests.post(url, files=files, data=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        if not result.get("ok"):
            raise TelegramUploadError(f"Telegram API error: {result}")
        
        # Extract file_id from response
        if 'photo' in result["result"]:
            return result["result"]["photo"][-1]["file_id"]
        elif 'document' in result["result"]:
            return result["result"]["document"]["file_id"]
        elif 'video' in result["result"]:
            return result["result"]["video"]["file_id"]
        else:
            raise TelegramUploadError("No file_id found in Telegram response")
                
    except requests.exceptions.RequestException as e:
        raise TelegramUploadError(f"Network error: {e}")

async def get_telegram_file_url(file_id: str) -> str:
    """Get direct URL for Telegram file"""
    try:
        if not TELEGRAM_BOT_TOKEN:
            return ""
            
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
        response = requests.post(url, data={"file_id": file_id})
        result = response.json()
        
        if result.get("ok"):
            file_path = result["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_id}"
    except:
        return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_id}"

async def store_in_firebase(user_id: str, post_id: str, feed_item: dict):
    """Store post metadata in Firebase using REST API"""
    try:
        # Store under user's feed
        firebase_client.set_data(f"feeds/{user_id}/{post_id}", feed_item)
        
        # Also store in global timeline for easier querying
        firebase_client.set_data(f"timeline/{post_id}", feed_item)
        
        logger.info(f"✅ Stored post {post_id} for user {user_id} in Firebase")
        
    except Exception as e:
        logger.error(f"Firebase storage error: {e}")
        raise FirebaseError(f"Firebase operation failed: {e}")

async def process_upload_analytics(user_id: str, post_id: str):
    """Background task for analytics processing"""
    try:
        user_data = firebase_client.get_data(f"users/{user_id}") or {}
        
        upload_count = user_data.get('upload_count', 0) + 1
        user_update = {
            'upload_count': upload_count,
            'last_upload': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
            'username': f"user_{user_id}",
            'profile_picture': f"https://api.dicebear.com/7.x/avataaars/svg?seed={user_id}"
        }
        
        firebase_client.set_data(f"users/{user_id}", user_update)
        
        logger.info(f"📊 Analytics updated for user {user_id}, post {post_id}")
        
    except Exception as e:
        logger.error(f"Analytics processing failed: {e}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test Firebase connection
        test_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "project": FIREBASE_CONFIG["project_id"],
            "status": "connected"
        }
        firebase_client.set_data("health_check", test_data)
        
        # Test read back
        retrieved_data = firebase_client.get_data("health_check")
        
        return {
            "status": "healthy", 
            "timestamp": datetime.utcnow().isoformat(),
            "firebase": "connected",
            "telegram": "configured" if TELEGRAM_BOT_TOKEN else "not_configured",
            "project": FIREBASE_CONFIG["project_id"]
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "firebase": "disconnected",
            "telegram": "configured" if TELEGRAM_BOT_TOKEN else "not_configured",
            "error": str(e)
        }

@app.get("/test-firebase")
async def test_firebase():
    """Test Firebase connection"""
    try:
        test_data = {
            "test_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Test from FastAPI REST",
            "project": FIREBASE_CONFIG["project_id"]
        }
        
        firebase_client.set_data("test_connection", test_data)
        
        # Read back the data
        retrieved_data = firebase_client.get_data("test_connection")
        
        return {
            "status": "success",
            "written": test_data,
            "read": retrieved_data,
            "message": f"Firebase REST connection working for project: {FIREBASE_CONFIG['project_id']}",
            "database_url": FIREBASE_CONFIG["database_url"]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Firebase connection failed: {e}",
            "project": FIREBASE_CONFIG["project_id"]
        }

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Instagram Clone API with Telegram Storage (REST Version)",
        "version": "1.0",
        "project": FIREBASE_CONFIG["project_id"],
        "firebase_method": "REST_API",
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN),
        "endpoints": {
            "health": "/health",
            "test_firebase": "/test-firebase",
            "upload": "/upload/",
            "feed": "/feed/",
            "user_posts": "/user-posts/{user_id}"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
