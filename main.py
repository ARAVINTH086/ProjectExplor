from fastapi import FastAPI, UploadFile, Form
import requests
import firebase_admin
from firebase_admin import db

app = FastAPI()

# initialize Firebase
firebase_admin.initialize_app(options={
    "databaseURL": "https://instaclone-aura444-default-rtdb.firebaseio.com/"
})

TELEGRAM_BOT_TOKEN = "7689288290:AAFIFTu8IX52UqeAuvdJxMjzzy8Prc1SE4Q"

@app.post("/upload/")
async def upload_media(user_id: str = Form(...), caption: str = Form(...), file: UploadFile = None):
    if not file:
        return {"error": "No file"}

    # 1. Upload to Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    files = {"document": (file.filename, await file.read())}
    resp = requests.post(url, files=files)
    tg_file_id = resp.json()["result"]["document"]["file_id"]

    # 2. Store metadata in Firebase Realtime DB
    ref = db.reference(f"/feeds/{user_id}")
    feed_item = {
        "media_file_id": tg_file_id,
        "unique_id": str(file.filename + "_" + str(user_id)),
        "caption": caption
    }
    ref.push(feed_item)

    return {"status": "success", "file_id": tg_file_id}


