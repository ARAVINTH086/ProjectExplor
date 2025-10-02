from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks, Depends, File
from fastapi.middleware.cors import CORSMiddleware
import requests
import uuid
from datetime import datetime, timedelta
import logging
import os
import json
import re
import random
from typing import List, Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Instagram Clone - Complete Structure")

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

# Telegram Configuration - Multiple Bots
TELEGRAM_BOT_TOKENS = os.getenv("TELEGRAM_BOT_TOKENS", "").split(",")
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
            return True
        except Exception as e:
            logger.error(f"Firebase write failed: {e}")
            raise FirebaseError(f"Failed to write to Firebase: {e}")
    
    def push_data(self, path, data):
        """Push data to a list in Firebase"""
        try:
            url = f"{self.database_url}/{path}.json"
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            return response.json().get('name')
        except Exception as e:
            logger.error(f"Firebase push failed: {e}")
            raise FirebaseError(f"Failed to push to Firebase: {e}")
    
    def update_data(self, path, data):
        """Update specific fields in Firebase"""
        try:
            url = f"{self.database_url}/{path}.json"
            response = requests.patch(url, json=data, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Firebase update failed: {e}")
            raise FirebaseError(f"Failed to update Firebase: {e}")

# Initialize Firebase REST client
firebase_client = FirebaseRESTClient(FIREBASE_CONFIG["database_url"])

def get_random_bot_token():
    """Get a random bot token from available bots"""
    available_tokens = [token.strip() for token in TELEGRAM_BOT_TOKENS if token.strip()]
    if not available_tokens:
        raise TelegramUploadError("No Telegram bot tokens available")
    return random.choice(available_tokens)

async def verify_user_token(token: str = Form(...)):
    """Basic user verification"""
    if not token or token.strip() == "":
        raise HTTPException(status_code=401, detail="Invalid token")
    return token

# ===== USER MANAGEMENT =====

@app.post("/create-user/")
async def create_user(
    user_id: str = Form(...),
    username: str = Form(...),
    full_name: str = Form(""),
    email: str = Form(""),
    profile_picture: str = Form(""),
    bio: str = Form(""),
    website: str = Form(""),
    is_private: bool = Form(False),
    token: str = Depends(verify_user_token)
):
    """Create or update user profile"""
    try:
        user_data = {
            "user_id": user_id,
            "username": username.lower(),
            "full_name": full_name,
            "email": email,
            
            "profile": {
                "profile_picture": profile_picture or f"https://api.dicebear.com/7.x/avataaars/svg?seed={user_id}",
                "bio": bio,
                "website": website,
                "gender": "",
                "birth_date": ""
            },
            
            "verification": {
                "is_verified": False,
                "is_business": False,
                "business_category": None
            },
            
            "privacy": {
                "is_private": is_private,
                "story_sharing": "everyone",
                "message_receiving": "everyone"
            },
            
            "counts": {
                "posts": 0,
                "followers": 0,
                "following": 0,
                "close_friends": 0
            },
            
            "metadata": {
                "created_at": datetime.utcnow().isoformat(),
                "last_active": datetime.utcnow().isoformat(),
                "last_post_at": None
            }
        }
        
        firebase_client.set_data(f"users/{user_id}", user_data)
        
        return {
            "status": "success",
            "message": "User profile created/updated",
            "user_id": user_id
        }
        
    except Exception as e:
        logger.error(f"User creation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

# ===== POST MANAGEMENT =====

@app.post("/upload-post/")
async def upload_post(
    background_tasks: BackgroundTasks,
    user_id: str = Form(...),
    username: str = Form(...),
    profile_picture: str = Form(...),
    caption: str = Form(""),
    location_name: str = Form(""),
    location_lat: float = Form(None),
    location_lng: float = Form(None),
    alt_text: str = Form(""),
    disable_comments: bool = Form(False),
    files: List[UploadFile] = File(None),  # CHANGED: Single file → List of files
    token: str = Depends(verify_user_token)
):
    """Upload a post with complete Instagram structure - supports multiple files (carousel)"""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > 10:  # Instagram limit is 10 media items
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed per post")
    
    try:
        # Generate IDs and timestamps
        post_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        # Build location data
        location_data = None
        if location_name:
            location_data = {
                "name": location_name,
                "address": location_name,
                "lat": location_lat,
                "lng": location_lng
            }
        
        # Process all files and build media array
        media_array = []
        for order_index, file in enumerate(files):
            # Validate file type for each file
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'video/mp4', 'image/webp']
            if file.content_type not in allowed_types:
                logger.warning(f"Skipping file {file.filename}: Invalid type {file.content_type}")
                continue
            
            # Read file content
            file_content = await file.read()
            file_size = len(file_content)
            
            # Validate file size (10MB limit)
            if file_size > 10 * 1024 * 1024:
                logger.warning(f"Skipping file {file.filename}: File too large")
                continue
            
            # Upload to Telegram using random bot
            upload_result = await upload_to_telegram(file_content, file.filename, file.content_type)
            
            # Create media item
            media_item = {
                "media_id": str(uuid.uuid4()),
                "file_unique_id": upload_result["file_unique_id"],
                "media_type": "image" if file.content_type.startswith('image/') else "video",
                "file_type": file.content_type,
                "file_size": file_size,
                "filename": file.filename,
                "width": 1080,  # Would need image processing to get actual dimensions
                "height": 1350,
                "duration": None,  # Would need video processing
                "thumbnail_url": upload_result.get("thumbnail_url", ""),
                "order_index": order_index
            }
            
            media_array.append(media_item)
        
        if not media_array:
            raise HTTPException(status_code=400, detail="No valid files to upload")
        
        # Complete post data structure
        post_data = {
            "post_id": post_id,
            "user_id": user_id,
            
            "user_info": {
                "username": username,
                "profile_picture": profile_picture,
                "is_verified": False,
                "is_business": False
            },
            
            "media": media_array,  # CHANGED: Now contains multiple media items
            
            "content": {
                "caption": caption,
                "location": location_data,
                "alt_text": alt_text or f"Post by {username}"
            },
            
            "engagement": {
                "like_count": 0,
                "comment_count": 0,
                "view_count": 0,
                "share_count": 0,
                "save_count": 0
            },
            
            "timestamps": {
                "created_at": timestamp,
                "updated_at": timestamp
            },
            
            "settings": {
                "comments_disabled": disable_comments,
                "is_hidden": False,
                "is_sponsored": False,
                "is_pinned": False
            },
            
            "discovery": {
                "hashtags": extract_hashtags(caption),
                "mentions": extract_mentions(caption),
                "product_tags": []
            }
        }
        
        # Store in Firebase
        await store_post_data(post_id, post_data, user_id)
        
        # Background tasks
        background_tasks.add_task(update_user_counts, user_id, "posts", 1)
        background_tasks.add_task(update_hashtags, extract_hashtags(caption), post_id)
        background_tasks.add_task(update_user_last_post, user_id)
        
        return {
            "status": "success", 
            "message": f"Post uploaded successfully with {len(media_array)} media items",
            "post_id": post_id,
            "media_count": len(media_array),
            "timestamp": timestamp
        }
        
    except TelegramUploadError as e:
        logger.error(f"Telegram upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload to Telegram")
    except FirebaseError as e:
        logger.error(f"Firebase storage failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to store post")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ===== STORY MANAGEMENT =====

@app.post("/upload-story/")
async def upload_story(
    user_id: str = Form(...),
    username: str = Form(...),
    profile_picture: str = Form(...),
    text_overlay: str = Form(""),
    close_friends_only: bool = Form(False),
    allow_replies: bool = Form(True),
    file: UploadFile = File(...),  # Stories are typically single media
    token: str = Depends(verify_user_token)
):
    """Upload a story with 24-hour expiration"""
    try:
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'video/mp4']
        if file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail="File type not allowed for stories")
        
        file_content = await file.read()
        
        # Upload to Telegram
        upload_result = await upload_to_telegram(file_content, file.filename, file.content_type)
        
        # Story data with 24-hour expiration
        story_id = str(uuid.uuid4())
        created_at = datetime.utcnow()
        expires_at = (created_at + timedelta(hours=24)).isoformat()
        
        story_data = {
            "story_id": story_id,
            "user_id": user_id,
            
            "user_info": {
                "username": username,
                "profile_picture": profile_picture
            },
            
            "media": {
                "file_unique_id": upload_result["file_unique_id"],
                "media_type": "image" if file.content_type.startswith('image/') else "video",
                "duration": 15,  # Default, would need actual video duration
                "thumbnail_url": upload_result.get("thumbnail_url", "")
            },
            
            "content": {
                "text_overlay": text_overlay,
                "polls": [],
                "questions": [],
                "sliders": [],
                "stickers": []
            },
            
            "timestamps": {
                "created_at": created_at.isoformat(),
                "expires_at": expires_at
            },
            
            "settings": {
                "close_friends_only": close_friends_only,
                "allow_replies": allow_replies,
                "allow_sharing": True,
                "show_activity_status": True
            },
            
            "engagement": {
                "view_count": 0,
                "reply_count": 0,
                "share_count": 0,
                "impression_count": 0
            },
            
            "viewers": []
        }
        
        # Store story
        firebase_client.set_data(f"stories/{user_id}/{story_id}", story_data)
        
        return {
            "status": "success",
            "message": "Story uploaded successfully",
            "story_id": story_id,
            "expires_at": expires_at
        }
        
    except Exception as e:
        logger.error(f"Story upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload story")

# ===== ENGAGEMENT ACTIONS =====

@app.post("/like-post/")
async def like_post(
    user_id: str = Form(...),
    username: str = Form(...),
    profile_picture: str = Form(...),
    post_id: str = Form(...),
    like_type: str = Form("like"),
    token: str = Depends(verify_user_token)
):
    """Like a post"""
    try:
        like_id = str(uuid.uuid4())
        like_data = {
            "like_id": like_id,
            "post_id": post_id,
            "user_id": user_id,
            
            "user_info": {
                "username": username,
                "profile_picture": profile_picture
            },
            
            "timestamp": datetime.utcnow().isoformat(),
            "type": like_type
        }
        
        # Store like
        firebase_client.set_data(f"likes/{post_id}/{like_id}", like_data)
        
        # Increment like count
        firebase_client.update_data(f"posts/{post_id}/engagement", {"like_count": "INCREMENT"})
        
        # Create activity notification
        background_tasks.add_task(create_activity, post_id, user_id, username, "like", post_id)
        
        return {
            "status": "success",
            "message": "Post liked",
            "like_id": like_id
        }
        
    except Exception as e:
        logger.error(f"Like failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to like post")

@app.post("/add-comment/")
async def add_comment(
    user_id: str = Form(...),
    username: str = Form(...),
    profile_picture: str = Form(...),
    post_id: str = Form(...),
    text: str = Form(...),
    parent_comment_id: str = Form(None),
    token: str = Depends(verify_user_token)
):
    """Add a comment to a post"""
    try:
        comment_id = str(uuid.uuid4())
        comment_data = {
            "comment_id": comment_id,
            "post_id": post_id,
            "user_id": user_id,
            
            "user_info": {
                "username": username,
                "profile_picture": profile_picture,
                "is_verified": False
            },
            
            "content": {
                "text": text,
                "mentions": extract_mentions(text)
            },
            
            "timestamps": {
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            },
            
            "engagement": {
                "like_count": 0,
                "reply_count": 0
            },
            
            "metadata": {
                "parent_comment_id": parent_comment_id,
                "is_hidden": False,
                "is_pinned": False
            }
        }
        
        # Store comment
        firebase_client.set_data(f"comments/{post_id}/{comment_id}", comment_data)
        
        # Increment comment count
        firebase_client.update_data(f"posts/{post_id}/engagement", {"comment_count": "INCREMENT"})
        
        # Create activity notification
        background_tasks.add_task(create_activity, post_id, user_id, username, "comment", post_id, text)
        
        return {
            "status": "success",
            "message": "Comment added",
            "comment_id": comment_id
        }
        
    except Exception as e:
        logger.error(f"Comment failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to add comment")

@app.post("/follow-user/")
async def follow_user(
    follower_id: str = Form(...),
    follower_username: str = Form(...),
    following_id: str = Form(...),
    is_close_friend: bool = Form(False),
    token: str = Depends(verify_user_token)
):
    """Follow a user"""
    try:
        follow_id = str(uuid.uuid4())
        follow_data = {
            "follow_id": follow_id,
            "follower_id": follower_id,
            "following_id": following_id,
            
            "follower_info": {
                "username": follower_username,
                "profile_picture": f"https://api.dicebear.com/7.x/avataaars/svg?seed={follower_id}"
            },
            
            "timestamp": datetime.utcnow().isoformat(),
            "status": "active",
            "notifications": True,
            "is_close_friend": is_close_friend
        }
        
        # Store follow relationship
        firebase_client.set_data(f"follows/{follower_id}_{following_id}", follow_data)
        
        # Update user counts
        background_tasks.add_task(update_user_counts, follower_id, "following", 1)
        background_tasks.add_task(update_user_counts, following_id, "followers", 1)
        
        # Create activity notification
        background_tasks.add_task(create_activity, following_id, follower_id, follower_username, "follow", following_id)
        
        return {
            "status": "success",
            "message": "User followed",
            "follow_id": follow_id
        }
        
    except Exception as e:
        logger.error(f"Follow failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to follow user")

# ===== HELPER FUNCTIONS =====

async def upload_to_telegram(file_content: bytes, filename: str, content_type: str) -> Dict[str, Any]:
    """Upload media to Telegram using random bot and return file info"""
    try:
        bot_token = get_random_bot_token()
        
        if content_type.startswith('image/'):
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            files = {"photo": (filename, file_content, content_type)}
        else:
            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            files = {"document": (filename, file_content, content_type)}
        
        data = {"chat_id": TELEGRAM_CHAT_ID} if TELEGRAM_CHAT_ID else {}
        
        response = requests.post(url, files=files, data=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        if not result.get("ok"):
            raise TelegramUploadError(f"Telegram API error: {result}")
        
        # Extract file information
        file_info = {}
        if 'photo' in result["result"]:
            photo = result["result"]["photo"][-1]
            file_info["file_unique_id"] = photo["file_unique_id"]
            file_info["file_id"] = photo["file_id"]
        elif 'document' in result["result"]:
            document = result["result"]["document"]
            file_info["file_unique_id"] = document["file_unique_id"]
            file_info["file_id"] = document["file_id"]
        elif 'video' in result["result"]:
            video = result["result"]["video"]
            file_info["file_unique_id"] = video["file_unique_id"]
            file_info["file_id"] = video["file_id"]
        else:
            raise TelegramUploadError("No file found in Telegram response")
        
        return file_info
                
    except requests.exceptions.RequestException as e:
        raise TelegramUploadError(f"Network error: {e}")

async def store_post_data(post_id: str, post_data: dict, user_id: str):
    """Store post data in multiple locations for efficient querying"""
    try:
        # Store in main posts collection
        firebase_client.set_data(f"posts/{post_id}", post_data)
        
        # Store in user's posts collection
        firebase_client.set_data(f"user_posts/{user_id}/{post_id}", {
            "post_id": post_id,
            "timestamp": post_data["timestamps"]["created_at"]
        })
        
        # Add to global timeline
        firebase_client.push_data("timeline", {
            "post_id": post_id,
            "user_id": user_id,
            "timestamp": post_data["timestamps"]["created_at"],
            "score": 1.0  # For feed ranking
        })
        
        logger.info(f"✅ Post {post_id} stored in Firebase with {len(post_data['media'])} media items")
        
    except Exception as e:
        logger.error(f"Post storage error: {e}")
        raise FirebaseError(f"Failed to store post: {e}")

async def update_user_counts(user_id: str, count_type: str, delta: int):
    """Update user engagement counts"""
    try:
        firebase_client.update_data(f"users/{user_id}/counts", {count_type: "INCREMENT"})
    except Exception as e:
        logger.error(f"User count update failed: {e}")

async def update_user_last_post(user_id: str):
    """Update user's last post timestamp"""
    try:
        firebase_client.update_data(f"users/{user_id}/metadata", {
            "last_post_at": datetime.utcnow().isoformat(),
            "last_active": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"User last post update failed: {e}")

async def update_hashtags(hashtags: List[str], post_id: str):
    """Update hashtag collections"""
    try:
        for hashtag in hashtags:
            hashtag_lower = hashtag.lower()
            hashtag_data = {
                "hashtag": hashtag_lower,
                "metadata": {
                    "post_count": "INCREMENT",
                    "last_used": datetime.utcnow().isoformat(),
                    "is_featured": False,
                    "is_banned": False
                }
            }
            firebase_client.set_data(f"hashtags/{hashtag_lower}", hashtag_data)
            
    except Exception as e:
        logger.error(f"Hashtag update failed: {e}")

async def create_activity(target_user_id: str, actor_user_id: str, actor_username: str, 
                         activity_type: str, target_id: str, text: str = None):
    """Create activity notification"""
    try:
        activity_id = str(uuid.uuid4())
        activity_data = {
            "activity_id": activity_id,
            "user_id": target_user_id,  # Who should receive the notification
            "type": activity_type,
            
            "actor_id": actor_user_id,
            "actor_info": {
                "username": actor_username,
                "profile_picture": f"https://api.dicebear.com/7.x/avataaars/svg?seed={actor_user_id}"
            },
            
            "target": {
                "type": "post" if activity_type in ["like", "comment"] else "user",
                "id": target_id,
                "preview": text or f"{actor_username} {activity_type}d your post"
            },
            
            "timestamp": datetime.utcnow().isoformat(),
            "is_read": False,
            "is_hidden": False
        }
        
        firebase_client.push_data(f"activities/{target_user_id}", activity_data)
        
    except Exception as e:
        logger.error(f"Activity creation failed: {e}")

def extract_hashtags(text: str) -> List[str]:
    """Extract hashtags from text"""
    return re.findall(r'#(\w+)', text)

def extract_mentions(text: str) -> List[str]:
    """Extract mentions from text"""
    return re.findall(r'@(\w+)', text)

# ===== HEALTH & INFO =====

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "service": "Instagram Clone - Complete Structure",
        "timestamp": datetime.utcnow().isoformat(),
        "active_bots": len([t for t in TELEGRAM_BOT_TOKENS if t.strip()])
    }

@app.get("/")
async def root():
    """API information"""
    return {
        "message": "Instagram Clone - Complete Data Structure",
        "version": "1.0",
        "description": "Complete Instagram-like data structure with multi-bot support and carousel posts",
        "endpoints": {
            "user_management": "/create-user/",
            "posts": "/upload-post/ (supports multiple files)",
            "stories": "/upload-story/",
            "engagement": ["/like-post/", "/add-comment/", "/follow-user/"]
        },
        "data_collections": [
            "users", "posts", "stories", "comments", "likes", 
            "follows", "activities", "hashtags", "timeline"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
