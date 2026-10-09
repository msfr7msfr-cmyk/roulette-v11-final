from flask import Flask
import threading, os
import telebot
from collections import Counter

# === 1. سيرفر Render ===
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot V24 FINAL Live ✅"

TOKEN = os.environ.get("BOT_TOKEN", "حط التوكن هنا اذا ما عندك ENV")
bot = telebot.TeleBot(TOKEN)

history = []

SECTORS = {
    "Voisins": [22,18,29,7,28,12,35,3,26,0,32,15],
    "Tiers": [27,13,36,11,30,8,23,10,5,24,16,33],
    "Orphelins": [1,20,14,31,9,6,17,34]
}

def get_sector_name(num):
    for name, nums in SECTORS.items():
        if num in nums:
            return name
    return "Zero"

def get_gap_dict(hist):
    gap = {}
    for n in range(37):
        try:
            last = len(hist) - 1 - hist[::-1].index(n)
            gap[n] = len(hist) - 1 - last
        except:
            gap[n] = 999
    return gap

def get_top5_v24(hist, gap_dict):
    last_20 = hist[-20:]
    last_7 = hist[-7:]
    last_5 = hist[-5:]

    sector_counts = Counter([get_sector_name(x) for x in last_7])
    hot_sector = sector_counts.most_common(1)[0][0] if sector_counts else "Voisins"

    scores = {}
    for i, num in enumerate(last_20):
        weight = 1 + (i / 20) * 1.5
        if num in last_5:
            weight *= 2.5
        if get_sector_name(num) == hot_sector:
            weight *= 1.7
        scores[num] = scores.get(num, 0) + weight

    # فلتر ذكي
    valid_gaps = [g for g in gap_dict.values() if g < 100]
    avg_gap = sum(valid_gaps) / len(valid_gaps) if valid_gaps else 18
    limit = 15 if avg_gap > 18 else 24

    filtered = {n:s for n,s in scores.items() if gap_dict.get(n,0) <= limit}
    top5 = sorted(filtered, key=lambda x: filtered[x], reverse=True)[:5]

    # مع الجيران Gap<10
    top_with_neighbors = []
    for n in top5:
        if gap_dict.get(n,0) < 10:
            top_with_neighbors.append(n)

    return top5, top_with_neighbors, hot_sector, limit, gap_dict

@bot.message_handler(func=lambda m: True)
def handler(message):
    global history
    try:
        text = message.text.strip()
        low = text.lower()

        if low in ["مسح", "م", "clear", "/clear", "مسح السجل"]:
            history = []
            bot.reply_to(message, "✅ تم مسح السجل\nدز ارقام جديدة")
            return

        # يدعم: 30 او 1,34,23 او 1 34 23
        nums = []
        clean = text.replace('،', ',').replace(' ', ',')
        for p in clean.split(','):
            p = p.strip()
            if p == '': continue
            if p.lstrip('-').isdigit():
                n = int(p)
                if 0 <= n <= 36:
                    nums.append(n)

        if not nums:
            return

        for n in nums:
            history.append(n)
        if len(history) > 200:
            history = history[-200:]

        if len(history) < 10:
            bot.reply_to(message, f"✅ {nums}\nباقي {10-len(history)} ارقام")
            return

        top5, with_gap10, hot_sector, limit, gap_dict = get_top5_v24(history, gap_dict=get_gap_dict(history))

        last_num = history[-1]
        sector_last = get_sector_name(last_num)
        count_hot = len([x for x in history[-20:] if get_sector_name(x) == hot_sector])

        # ترتيب الحارة مع عدد التكرار
        hara_text = ", ".join([f"{x}({history[-20:].count(x)}x)" for x in top5])

        response = f"""🧠 V22 المحسن Gap10
📍 اخر: {last_num} | قطاع: {sector_last}({count_hot}/20) | دخول: ✅ (4)

🔥 5 الحارة (وزن زمني):
{hara_text}

💰 الاساسي: {top5}
💰 مع الجيران: {with_gap10} ℹ️ جيران حية فقط (Gap<10)

ثابت 4 لفات | اخر 10: {history[-10:]}"""

        bot.reply_to(message, response)

    except Exception as e:
        print(f"Error handler: {e}")
        bot.reply_to(message, f"⚠️ خطأ: {e}")

def run_bot():
    print("Bot polling started...")
    bot.infinity_polling(skip_pending=True)

# تشغيل البوت بالخلفية لـ gunicorn
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
