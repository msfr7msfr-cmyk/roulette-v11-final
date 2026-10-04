import os, re, threading, cv2, pytesseract
from collections import deque
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V13 Live - Fixed Clear + Image Reader"

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

def main_markup():
    m = ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("تحليل مفصل", "مسح")
    return m

def analyze_and_reply(chat_id):
    if len(history) < 5:
        bot.send_message(chat_id, f"عندك {len(history)} ارقام بس، دز اكثر", reply_markup=main_markup())
        return
    last = history[-1]
    red = sum(1 for x in history if x in RED_NUMS)
    black = sum(1 for x in history if x not in RED_NUMS and x!=0)
    zero = sum(1 for x in history if x==0)
    txt = f"تحليل V13 - {len(history)} رقم\n\nاخر 5: {list(history)[-5:]}\nاخر: {last} ({get_color(last)})\n\nالوان:\nاحمر: {red}\nاسود: {black}\nصفر: {zero}\n\nالاكثر تكرارا: {max(set(history), key=list(history).count)}\n\nالتوقع القادم: تابع النمط"
    bot.send_message(chat_id, txt, reply_markup=main_markup())

def extract_from_image(path):
    try:
        img = cv2.imread(path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789 '
        text = pytesseract.image_to_string(thresh, config=config)
        nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', text) if 0 <= int(n) <= 36]
        return nums
    except: return []

@bot.message_handler(content_types=['photo'])
def photo_h(m):
    try:
        bot.reply_to(m, "⏳ V13 يقرا الصورة...")
        file_info = bot.get_file(m.photo[-1].file_id)
        data = bot.download_file(file_info.file_path)
        p = f"/tmp/{m.photo[-1].file_id}.jpg"
        with open(p,'wb') as f: f.write(data)
        nums = extract_from_image(p)
        if nums:
            history.extend(nums)
            bot.send_message(m.chat.id, f"✅ استلمت {len(nums)} رقم - اخر رقم {nums[-1]} {get_color(nums[-1])}\nV13 - {len(history)} رقم", reply_markup=main_markup())
            analyze_and_reply(m.chat.id)
        else:
            bot.send_message(m.chat.id, "❌ ما قدرت اقرا الصورة، دز ارقام كتابة", reply_markup=main_markup())
    except Exception as e:
        bot.send_message(m.chat.id, f"خطأ: {e}")

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    bot.send_message(m.chat.id, "✅ V13 بدأ من جديد - تم المسح\nدز ارقام أو صورة فيها 150 رقم", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🗑️ تم المسح بنجاح\nدز ارقام جديدة", reply_markup=main_markup())

@bot.message_handler(func=lambda m: "مفصل" in m.text if m.text else False)
def detail_h(m):
    analyze_and_reply(m.chat.id)

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text: return
    if "مسح" in m.text or "مفصل" in m.text or m.text.startswith('/'): return
    nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0 <= int(n) <= 36]
    if nums:
        history.extend(nums)
        bot.send_message(m.chat.id, f"✅ استلمت {len(nums)} رقم - اخر رقم {nums[-1]} {get_color(nums[-1])}\nV13 - {len(history)} رقم", reply_markup=main_markup())
        if len(nums) >= 3:
            analyze_and_reply(m.chat.id)
    else:
        bot.send_message(m.chat.id, "دز ارقام من 0-36 أو صورة", reply_markup=main_markup())

threading.Thread(target=run_flask, daemon=True).start()
bot.infinity_polling()
