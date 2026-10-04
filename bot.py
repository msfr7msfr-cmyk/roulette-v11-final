import os
from collections import Counter
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
web = Flask(__name__)
data = {}

# ارقام الروليت وجيرانها
NEIGHBORS = {
    0: [26, 32], 32: [0, 26], 15: [32, 19], 19: [15, 4], 4: [19, 21],
    21: [4, 2], 2: [21, 25], 25: [2, 17], 17: [25, 34], 34: [17, 6],
    6: [34, 27], 27: [6, 13], 13: [27, 36], 36: [13, 11], 11: [36, 30],
    30: [11, 8], 8: [30, 23], 23: [8, 10], 10: [23, 5], 5: [10, 24],
    24: [5, 16], 16: [24, 33], 33: [16, 1], 1: [33, 20], 20: [1, 14],
    14: [20, 31], 31: [14, 9], 9: [31, 22], 22: [9, 18], 18: [22, 29],
    29: [18, 7], 7: [29, 28], 28: [7, 12], 12: [28, 35], 35: [12, 3], 3: [35, 26], 26: [3, 0]
}

@web.route('/')
def home():
    return "Bot V11 Final Running ✅"

def get_list(cid):
    if cid not in data:
        data[cid] = []
    return data[cid]

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_list(update.effective_chat.id).clear()
    await update.message.reply_text("✅ بوت الروليت V11 جاهز\nدز الأرقام (0-36)\nاكتب مسح للمسح")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cid = update.effective_chat.id
    lst = get_list(cid)

    if text == "مسح":
        lst.clear()
        await update.message.reply_text("🗑️ تم مسح كل الأرقام")
        return
    if text.startswith("/"):
        return

    nums = []
    for p in text.replace(",", " ").split():
        try:
            n = int(float(p))
            if 0 <= n <= 36:
                nums.append(n)
        except:
            pass

    if not nums:
        return

    lst.extend(nums)

    # تحليل بسيط
    last = lst[-1]
    c = Counter(lst)
    hot = c.most_common(3)

    neigh = NEIGHBORS.get(last, [])

    msg = f"✅ تم: {nums}\n"
    msg += f"📊 العدد الكلي: {len(lst)}\n"
    msg += f"🎯 آخر رقم: {last}\n"
    msg += f"👥 جيرانه: {neigh}\n"
    msg += f"🔥 الأكثر تكرار: {hot}\n"
    msg += f"\nدز رقم ثاني للتحليل"

    await update.message.reply_text(msg)

def run_web():
    web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    run_bot()
