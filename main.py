from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import requests
import firebase_admin
from firebase_admin import db, credentials
import uuid
from datetime import datetime
import logging
import os
import json
from typing import List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Instagram Clone API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Firebase Configuration from your service account
FIREBASE_CONFIG = {
    "project_id": "instaclone-aura444",
    "database_url": "https://instaclone-aura444-default-rtdb.firebaseio.com"
}

def initialize_firebase():
    """Initialize Firebase with environment variables"""
    try:
        if firebase_admin._DEFAULT_APP_NAME in firebase_admin._apps:
            logger.info("✅ Firebase already initialized")
            return True
            
        # Get credentials from environment variables
        service_account_info = {
            "type": "service_account",
            "project_id": os.getenv("FIREBASE_PROJECT_ID", FIREBASE_CONFIG["project_id"]),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n'),
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL")
        }
        
        # Validate required fields
        if not service_account_info["private_key"]:
            logger.error("❌ Firebase private key not found in environment variables")
            return False
            
        cred = credentials.Certificate(service_account_info)
        
        # Initialize Firebase
        firebase_admin.initialize_app(cred, {
            "databaseURL": os.getenv("FIREBASE_DATABASE_URL", FIREBASE_CONFIG["database_url"]),
        })
        
        logger.info("✅ Firebase initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Firebase initialization failed: {e}")
        return False

# Initialize Firebase
firebase_initialized = initialize_firebase()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class TelegramUploadError(Exception):
    pass

class FirebaseError(Exception):
    pass

def get_db_reference(path: str):
    """Get Firebase database reference with initialization check"""
    if not firebase_initialized:
        raise FirebaseError("Firebase not initialized")
    return db.reference(path)

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
        
        # Store metadata in Firebase
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
        ref = get_db_reference("/timeline")
        timeline_data = ref.order_by_child("timestamp").limit_to_last(limit + offset).get()
        
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
        ref = get_db_reference(f"/feeds/{user_id}")
        user_posts = ref.order_by_child("timestamp").limit_to_last(limit + offset).get()
        
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
    """Store post metadata in Firebase"""
    try:
        # Store under user's feed
        user_ref = get_db_reference(f"/feeds/{user_id}/{post_id}")
        user_ref.set(feed_item)
        
        # Also store in global timeline for easier querying
        timeline_ref = get_db_reference(f"/timeline/{post_id}")
        timeline_ref.set(feed_item)
        
        logger.info(f"✅ Stored post {post_id} for user {user_id} in Firebase")
        
    except Exception as e:
        logger.error(f"Firebase storage error: {e}")
        raise FirebaseError(f"Firebase operation failed: {e}")

async def process_upload_analytics(user_id: str, post_id: str):
    """Background task for analytics processing"""
    try:
        user_ref = get_db_reference(f"/users/{user_id}")
        user_data = user_ref.get() or {}
        
        upload_count = user_data.get('upload_count', 0) + 1
        user_ref.update({
            'upload_count': upload_count,
            'last_upload': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
            'username': f"user_{user_id}",
            'profile_picture': f"https://api.dicebear.com/7.x/avataaars/svg?seed={user_id}"
        })
        
        logger.info(f"📊 Analytics updated for user {user_id}, post {post_id}")
        
    except Exception as e:
        logger.error(f"Analytics processing failed: {e}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        if not firebase_initialized:
            return {
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "firebase": "not_initialized",
                "telegram": "configured" if TELEGRAM_BOT_TOKEN else "not_configured"
            }
            
        # Test Firebase connection
        ref = get_db_reference("/health_check")
        test_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "project": FIREBASE_CONFIG["project_id"],
            "status": "connected"
        }
        ref.set(test_data)
        
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
        if not firebase_initialized:
            return {
                "status": "error",
                "message": "Firebase not initialized. Check environment variables."
            }
            
        test_data = {
            "test_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Test from FastAPI",
            "project": FIREBASE_CONFIG["project_id"]
        }
        
        ref = get_db_reference("/test_connection")
        ref.set(test_data)
        
        # Read back the data
        retrieved_data = ref.get()
        
        return {
            "status": "success",
            "written": test_data,
            "read": retrieved_data,
            "message": f"Firebase connection working for project: {FIREBASE_CONFIG['project_id']}",
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
        "message": "Instagram Clone API with Telegram Storage",
        "version": "1.0",
        "project": FIREBASE_CONFIG["project_id"],
        "firebase_initialized": firebase_initialized,
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
