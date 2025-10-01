from fastapi import FastAPI, UploadFile, File
import requests
import os

app = FastAPI()

BOT_TOKEN = "7689288290:AAFIFTu8IX52UqeAuvdJxMjzzy8Prc1SE4Q"
CHANNEL_ID = "-1002924854294"

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    # Save temporarily
    file_location = file.filename
    with open(file_location, "wb") as f:
        f.write(await file.read())
    
    # Upload to Telegram
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(file_location, "rb") as f:
        r = requests.post(url, files={"document": f}, data={"chat_id": CHANNEL_ID})
    os.remove(file_location)
    
    result = r.json()
    if result.get("ok"):
        file_id = result["result"]["document"]["file_id"]
        file_unique_id = result["result"]["document"]["file_unique_id"]
        return {"file_id": file_id, "file_unique_id": file_unique_id}
    return {"error": result}
