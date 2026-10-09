from flask import Flask
import threading, os
import telebot
from collections import Counter

# === Render Flask ===
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot V24 SMART is LIVE ✅"

TOKEN = os.environ.get("BOT_TOKEN", "ضع توكنك هنا")
bot = telebot.TeleBot(TOKEN)

history = []

# قطاعات الروليت الاوربية الحقيقية
SECTORS = {
    "voisins": [22,18,29,7,28,12,35,3,26,0,32,15],
    "tiers": [27,13,36,11,30,8,23,10,5,24,16,33],
    "orphelins": [1,20,14,31,9,6,17,34]
}

def get_sector(num):
    for name, nums in SECTORS.items():
        if num in nums:
            return name
    return "unknown"

def get_gap_dict(hist):
    gap = {}
    for n in range(37):
        try:
            last = len(hist) - 1 - hist[::-1].index(n)
            gap[n] = len(hist) - 1 - last
        except:
            gap[n] = 999
    return gap

# === V24 SMART ===
def get_top5_v24(hist, gap_dict):
    last_20 = hist[-20:]
    last_7 = hist[-7:]
    last_5 = hist[-5:]

    # 1. معرفة القطاع الحار باخر 7
    sector_counts = Counter([get_sector(x) for x in last_7])
    hot_sector = sector_counts.most_common(1)[0][0] if sector_counts else None

    scores = {}
    for i, num in enumerate(last_20):
        weight = 1 + (i / 20) * 1.5
        if num in last_5:
            weight *= 2.5 # وزن اللحظة
        if get_sector(num) == hot_sector:
            weight *= 1.7 # بونص القطاع الحار

        scores[num] = scores.get(num, 0) + weight

    # 2. فلتر ذكي متغير
    avg_gap = sum([g for g in gap_dict.values() if g < 100]) / 20
    limit = 15 if avg_gap > 18 else 24

    filtered = {n:s for n,s in scores.items() if gap_dict.get(n,0) <= limit}
    top5 = sorted(filtered, key=lambda x: filtered[x], reverse=True)[:5]
    return top5, hot_sector, limit

@bot.message_handler(func=lambda m: True)
def handler(message):
    try:
        num = int(message.text.strip())
        if not 0 <= num <= 36: return
        history.append(num)
        if len(history) > 150: history.pop(0)

        if len(history) < 20:
            bot.reply_to(message, f"✅ {num}\nباقي {20-len(history)} لفات حتى يبدأ V24")
            return

        gap_dict = get_gap_dict(history)
        top5, hot_sector, limit = get_top5_v24(history, gap_dict)

        # حساب الجيران الحية فقط للارقام الي Gap<10
        neighbors = []
        for n in top5:
            if gap_dict.get(n,0) < 10:
                neighbors.append(f"{n} (جيران: {n-1},{n+1})")

        txt = f"""🎯 **V24 SMART** - {num}

🔥 القطاع الحار: {hot_sector} ({limit} فلتر)
⭐ الاساسي: {top5}
📊 Gap: {[gap_dict[x] for x in top5]}
👥 جيران حية (Gap<10): {', '.join(neighbors) if neighbors else 'لا يوجد'}

{'✅ دخول' if len(top5)>=5 else '❌ انتظار'}"""
        bot.reply_to(message, txt)
    except Exception as e:
        print(e)

def run_bot():
    bot.infinity_polling()

threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
