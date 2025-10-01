import requests


import requests
import json

# === CONFIGURATION ===
BOT_A_TOKEN = "7401204367:AAFgWwlZuIlVjcNuThHPI1t9OZexSwil6JM"  # Bot that uploads
BOT_B_TOKEN =  "7689288290:AAFIFTu8IX52UqeAuvdJxMjzzy8Prc1SE4Q"# Bot that downloads  
CHANNEL_ID = "-1002924854294"     # Your channel ID
FILE_PATH = "x1.jpeg"    # Local file to upload

# === UPLOAD FUNCTION (BOT A) ===
def bot_a_upload():
    api_url = f"https://api.telegram.org/bot{BOT_A_TOKEN}/sendPhoto"

    try:
        with open(FILE_PATH, "rb") as file:
            files = {"photo": file}
            data = {"chat_id": CHANNEL_ID, "caption": "User Status 🚀"}

            response = requests.post(api_url, files=files, data=data)
            result = response.json()
            print("🔍 Bot A Response:", json.dumps(result, indent=2))

            if result.get("ok"):
                photo_obj = result["result"]["photo"][-1]  # best quality photo
                file_id = photo_obj["file_id"]
                file_unique_id = photo_obj["file_unique_id"]
                message_id = result["result"]["message_id"]

                print("✅ Uploaded by Bot A")
                print(f"🆔 file_id: {file_id}")
                print(f"🔑 file_unique_id: {file_unique_id}")
                print(f"📨 message_id: {message_id}")

                return {
                    "file_id": file_id,
                    "file_unique_id": file_unique_id,
                    "message_id": message_id
                }
            else:
                print(f"❌ Upload failed: {result.get('description')}")
                return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

# === BOT B: GET FILE BY UNIQUE ID ===
def bot_b_get_by_unique_id(file_unique_id):
    """
    WARNING: This demonstrates the concept, but Telegram doesn't directly
    support fetching by file_unique_id across different bots.
    """
    print(f"\n🤖 Bot B attempting to find file with unique_id: {file_unique_id}")
    
    # Get recent updates to find the file
    updates_url = f"https://api.telegram.org/bot{BOT_B_TOKEN}/getUpdates"
    response = requests.get(updates_url)
    result = response.json()
    
    if result.get("ok"):
        for update in result["result"]:
            if "channel_post" in update:
                post = update["channel_post"]
                if "photo" in post:
                    for photo in post["photo"]:
                        if photo.get("file_unique_id") == file_unique_id:
                            print("🎉 Bot B found matching file!")
                            print(f"📋 file_id (Bot B): {photo['file_id']}")
                            return photo["file_id"]
        
        print("❌ Bot B couldn't find file with that unique_id")
    else:
        print(f"❌ Bot B failed to get updates: {result.get('description')}")
    
    return None

# === BOT B: DOWNLOAD FILE ===
def bot_b_download_file(file_id):
    """Bot B downloads the file using file_id"""
    print(f"\n📥 Bot B downloading file_id: {file_id}")
    
    # Step 1: Get file path
    get_file_url = f"https://api.telegram.org/bot{BOT_B_TOKEN}/getFile"
    response = requests.post(get_file_url, data={"file_id": file_id})
    result = response.json()
    
    if result.get("ok"):
        file_path = result["result"]["file_path"]
        print(f"📁 File path: {file_path}")
        
        # Step 2: Download the file
        download_url = f"https://api.telegram.org/file/bot{BOT_B_TOKEN}/{file_path}"
        download_response = requests.get(download_url)
        
        if download_response.status_code == 200:
            # Save the downloaded file
            downloaded_path = "downloaded_by_bot_b.jpg"
            with open(downloaded_path, "wb") as f:
                f.write(download_response.content)
            
            print(f"✅ Bot B download successful! Saved as: {downloaded_path}")
            return downloaded_path
        else:
            print(f"❌ Download failed: {download_response.status_code}")
    else:
        print(f"❌ Could not get file path: {result.get('description')}")
    
    return None

# === BOT B: GET FROM CHANNEL (MORE RELIABLE) ===
def bot_b_get_from_channel(message_id=None):
    """Bot B gets the file directly from the channel"""
    print(f"\n🤖 Bot B searching channel for files...")
    
    # If we have message_id, we can get specific message
    if message_id:
        message_url = f"https://api.telegram.org/bot{BOT_B_TOKEN}/getChatMessage"
        response = requests.post(message_url, data={
            "chat_id": CHANNEL_ID,
            "message_id": message_id
        })
        result = response.json()
        
        if result.get("ok") and "photo" in result["result"]:
            photo = result["result"]["photo"][-1]
            return photo["file_id"]
    
    # Otherwise, get recent messages
    updates_url = f"https://api.telegram.org/bot{BOT_B_TOKEN}/getUpdates"
    response = requests.get(updates_url)
    result = response.json()
    
    if result.get("ok") and result["result"]:
        # Find the most recent photo in the channel
        for update in reversed(result["result"]):  # Start from newest
            if "channel_post" in update and "photo" in update["channel_post"]:
                photo = update["channel_post"]["photo"][-1]
                print(f"📸 Found recent photo with unique_id: {photo['file_unique_id']}")
                return photo["file_id"]
    
    print("❌ Bot B found no photos in channel")
    return None

# === MAIN EXECUTION ===
if __name__ == "__main__":
    print("🚀 Starting Two-Bot File Transfer Test")
    print("=" * 50)
    
    # Step 1: Bot A uploads file
    upload_result = bot_a_upload()
    
    if upload_result:
        print("\n" + "=" * 50)
        print("🔄 Now testing Bot B retrieval")
        print("=" * 50)
        
        # Step 2: Bot B tries different methods to get the file
        
        # Method 1: Try using unique_id (may not work across bots)
        bot_b_file_id = bot_b_get_by_unique_id(upload_result["file_unique_id"])
        
        # Method 2: If Method 1 fails, get from channel directly
        if not bot_b_file_id:
            print("\n🔄 Falling back to channel search...")
            bot_b_file_id = bot_b_get_from_channel(upload_result["message_id"])
        
        # Step 3: If we found a file_id, download it
        if bot_b_file_id:
            bot_b_download_file(bot_b_file_id)
            print("\n🎉 Two-bot transfer completed successfully!")
        else:
            print("\n❌ Bot B could not retrieve the file")
    else:
        print("\n❌ Bot A upload failed")