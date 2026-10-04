import os, re, threading, cv2, pytesseract
from collections import deque
from flask import Flask
import telebot

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V12 Live - Image Reader"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get("BOT_TOKEN","")
bot = telebot.TeleBot(BOT_TOKEN)
history = deque(maxlen=200)
RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

def get_color(n):
    if n==0: return "اخضر"
    return "احمر" if n in RED_NUMS else "اسود"

def extract_from_image(path):
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789 '
    text = pytesseract.image_to_string(thresh, config=config)
    nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', text) if 0 <= int(n) <= 36]
    return nums

@bot.message_handler(content_types=['photo'])
def photo_h(m):
    try:
        bot.reply_to(m, "⏳ V12 يقرا الصورة...")
        file_info = bot.get_file(m.photo[-1].file_id)
        data = bot.download_file(file_info.file_path)
        with open("temp.jpg","wb") as f: f.write(data)
        nums = extract_from_image("temp.jpg")
        if len(nums)<3:
            bot.reply_to(m, f"❌ ما قريت زين، لكيت {len(nums)} فقط")
            return
        history.extend(nums)
        bot.reply_to(m, f"✅ قريت {len(nums)} رقم!\nاخر 10: {list(history)[-10:]}\nتحليل V12 - {len(history)} رقم")
    except Exception as e:
        bot.reply_to(m, f"خطأ: {e}")

@bot.message_handler(func=lambda m: True)
def text_h(m):
    nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0 <= int(n) <= 36]
    if not nums: return
    history.extend(nums)
    bot.reply_to(m, f"✅ استلمت {len(nums)} رقم - اخر رقم {nums[-1]} {get_color(nums[-1])}\nV12 - {len(history)} رقم")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot V12 Starting...")
    bot.infinity_polling()
