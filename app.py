from flask import Flask
import threading
import os
import telebot
from collections import Counter

# === 1. حل مشكلة Render (سيرفر وهمي) ===
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot V23 is LIVE ✅"

# === 2. كود البوت مالتك ===
TOKEN = os.environ.get("BOT_TOKEN", "حط التوكن هنا اذا ما عندك ENV")
bot = telebot.TeleBot(TOKEN)

history = [] # تخزن الارقام هنا

def get_gap_dict(history):
    gap = {}
    for num in range(37):
        try:
            last_index = len(history) - 1 - history[::-1].index(num)
            gap[num] = len(history) - 1 - last_index
        except ValueError:
            gap[num] = 999
    return gap

# === 3. V23 الجديد الي طلبته ===
def get_top5_v23(history, gap_dict):
    last_20 = history[-20:]
    last_5 = history[-5:]
    scores = {}
    for i, num in enumerate(last_20):
        weight = 1 + (i / 20)
        if num in last_5:
            weight *= 2
        scores[num] = scores.get(num, 0) + weight

    filtered_scores = {}
    for num, score in scores.items():
        if gap_dict.get(num, 0) <= 18: # فلتر البارد
            filtered_scores[num] = score

    top5 = sorted(filtered_scores, key=lambda x: filtered_scores[x], reverse=True)[:5]
    return top5

@bot.message_handler(func=lambda m: True)
def handle_numbers(message):
    try:
        num = int(message.text.strip())
        if 0 <= num <= 36:
            history.append(num)
            if len(history) > 100:
                history.pop(0)

            if len(history) < 20:
                bot.reply_to(message, f"تم {num} - انتظر {20-len(history)} لفات بعد")
                return

            gap_dict = get_gap_dict(history)
            top5 = get_top5_v23(history, gap_dict)

            # فلتر القطاع للدخول فقط
            last_20 = history[-20:]
            # هنا تحسب القطاعات Voisins/Tiers/Orphelins
            # مثال بسيط: اذا اكثر من 10 من نفس القطاع -> دخول
            sector_count = Counter(last_20).most_common(1)[0][1] # تبسيط، انت عندك حساب القطاعات الاصلي
            status = "دخول ✅" if sector_count >= 4 else "انتظار ❌"

            reply = f"V23 - {status}\nالاساسي (Top5): {top5}\nGap: {[gap_dict[n] for n in top5]}"
            bot.reply_to(message, reply)
    except:
        pass

# === 4. تشغيل البوت مع الفلاسك ===
def run_bot():
    bot.infinity_polling()

# هذا السطر مهم لـ gunicorn على Render
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
