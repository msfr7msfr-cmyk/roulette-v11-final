import os, random
from collections import Counter
from flask import Flask
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

def analyze(history):
    if len(history) < 5:
        return "ارسل 5 ارقام على الاقل مثل: 32 15 26 5 10"
    last = history[-1]
    counter = Counter(history)
    stuck_nums = [26,32,15]
    for n in stuck_nums:
        if counter[n] >= 3 and history[-3:].count(n) >= 2:
            idx = WHEEL.index(n)
            pred = WHEEL[(idx + 18) % len(WHEEL)]
            return f"⚠️ كشف تثبيت على {n}!\n💡 كسر النمط: العب القطاع المقابل\n🎯 توقع V11: {pred} وجيرانه"
    last_idx = WHEEL.index(last) if last in WHEEL else 0
    recent = history[-20:]
    sector_count = {}
    for num in recent:
        if num in WHEEL:
            sector = WHEEL.index(num) // 9
            sector_count[sector] = sector_count.get(sector, 0) + 1
    cold_sector = min(sector_count, key=sector_count.get) if sector_count else 0
    start = cold_sector * 9
    candidates = WHEEL[start:start+9]
    reds = sum(1 for x in recent if x in RED)
    if reds > len(recent)*0.6:
        candidates = [x for x in candidates if x not in RED or x==0]
    elif reds < len(recent)*0.4:
        candidates = [x for x in candidates if x in RED]
    pick = random.choice(candidates) if candidates else random.choice(WHEEL)
    neighbors = [WHEEL[(WHEEL.index(pick)-1)%37], pick, WHEEL[(WHEEL.index(pick)+1)%37]]
    return f"🔮 تحليل V11 FINAL:\nاخر رقم: {last}\nساخن: {counter.most_common(3)}\n🎯 توقع: {pick}\n📍 العب: {neighbors}\n💰 ادارة مال: 1-2-4"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎰 بوت الروليت V11 جاهز!\nارسل ارقام مثل: 32 15 26 5 10 1")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    nums = []
    for part in text.replace('\n',' ').split():
        if part.isdigit() and 0 <= int(part) <= 36:
            nums.append(int(part))
    if not nums:
        await update.message.reply_text("ارسل ارقام بين 0-36")
        return
    res = analyze(nums)
    await update.message.reply_text(res)

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V11 LIVE"
def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
