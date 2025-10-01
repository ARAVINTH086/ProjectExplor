import os
import secrets
from cryptography.fernet import Fernet
import requests
from datetime import datetime
import json

# ==========================
# CONFIGURATION
# ==========================
BOT_TOKENS = ["7689288290:AAFIFTu8IX52UqeAuvdJxMjzzy8Prc1SE4Q", "7401204367:AAFgWwlZuIlVjcNuThHPI1t9OZexSwil6JM"]
CHANNEL_USERNAME = "-1002924854294"  # Telegram channel
FERNET_KEY = Fernet.generate_key()  # For testing, generate new key each run
fernet = Fernet(FERNET_KEY)

# Mock Firestore (dictionary for testing)
firestore_db = {}
audit_logs = {}

# ==========================
# Utility Functions
# ==========================
def generate_short_token():
    return secrets.token_urlsafe(6)

def encrypt_file_id(file_id: str) -> str:
    return fernet.encrypt(file_id.encode()).decode()

def decrypt_file_id(encrypted_file_id: str) -> str:
    return fernet.decrypt(encrypted_file_id.encode()).decode()

# ==========================
# Telegram Upload
# ==========================
def upload_file_to_telegram(file_path: str, caption: str):
    for bot_token in BOT_TOKENS:
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        with open(file_path, "rb") as file:
            files = {"photo": file}
            data = {"chat_id": CHANNEL_USERNAME, "caption": caption}
            resp = requests.post(url, files=files, data=data).json()
            if resp.get("ok"):
                photo_obj = resp["result"]["photo"][-1]  # best quality
                print("\nUploaded to Telegram:")
                print(json.dumps(resp, indent=2))
                return photo_obj["file_id"], photo_obj["file_unique_id"]
    raise Exception("All bots failed to upload")

# ==========================
# Upload Simulation
# ==========================
def test_upload(file_path: str, caption: str, uid: str):
    file_id, file_unique_id = upload_file_to_telegram(file_path, caption)

    # Encrypt file_unique_id
    encrypted_id = encrypt_file_id(file_unique_id)

    # Generate short token
    short_token = generate_short_token()

    # Store metadata in mock Firestore
    firestore_db[short_token] = {
        "encrypted_file_id": encrypted_id,
        "uid": uid,
        "caption": caption,
        "uploaded_at": datetime.utcnow().isoformat()
    }

    # Log audit
    audit_logs[short_token] = {
        "action": "upload",
        "uid": uid,
        "timestamp": datetime.utcnow().isoformat()
    }

    print("\nStored Metadata in Firestore (simulated):")
    print(json.dumps(firestore_db[short_token], indent=2))
    print("\nAudit Log:")
    print(json.dumps(audit_logs[short_token], indent=2))

    return short_token

# ==========================
# Download Simulation
# ==========================
def test_download(short_token: str, uid: str):
    if short_token not in firestore_db:
        print("Invalid short token")
        return

    data = firestore_db[short_token]
    if data["uid"] != uid:
        print("Unauthorized access")
        return

    file_unique_id = decrypt_file_id(data["encrypted_file_id"])
    print(f"\nDecrypted file_unique_id: {file_unique_id}")

    # Download file using first working bot
    for bot_token in BOT_TOKENS:
        get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile"
        resp = requests.post(get_file_url, data={"file_id": file_unique_id}).json()
        if resp.get("ok"):
            file_path = resp["result"]["file_path"]
            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
            file_resp = requests.get(download_url)
            if file_resp.status_code == 200:
                local_file = f"downloaded_{short_token}.jpg"
                with open(local_file, "wb") as f:
                    f.write(file_resp.content)
                print(f"\nDownloaded file saved as: {local_file}")
                return local_file
    print("Download failed")

# ==========================
# MAIN TEST
# ==========================
if __name__ == "__main__":
    uid = "TEST_USER_1"
    local_file = "x1.jpeg"  # Change to your local file path
    caption = "User Status 🚀"

    print("=== UPLOAD TEST ===")
    token = test_upload(local_file, caption, uid)

    print("\n=== DOWNLOAD TEST ===")
    test_download(token, uid)
