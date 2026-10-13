import os, json, re, threading, math
from collections import Counter
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask

TOKEN = os.getenv("BOT_TOKEN")
HISTORY_FILE = "history.json"

app_web = Flask(__name__)
@app_web.route('/')
def home(): return "Bot is Alive!"
def run_web():
    app_web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f: return json.load(f)
        except: return []
    return []
def save_history(h):
    with open(HISTORY_FILE, "w") as f: json.dump(h, f)

history = load_history()
current_pred = None
try_count = 0
WIN_LIMIT = 10

def get_smart_pred():
    if len(history) < 20:
        return None, 0, f"نحتاج 20 رقم - عندك {len(history)}"
    last = history[-200:]
    n = len(last)
    counts = Counter(last)
    expected = n / 37
    scores = []
    for num, c in counts.items():
        if c < 1: continue
        std = math.sqrt(expected * (36/37))
        z = (c - expected) / std if std > 0 else 0
        scores.append((num, c, z))
    scores.sort(key=lambda x: x[2], reverse=True)
    top4 = [s[0] for s in scores[:4]]
    avg_z = sum(s[2] for s in scores[:4]) / 4
    max_z = scores[0][2]
    best_num = scores[0][0]
    # هنا نقول قوية قبل لا يطيح الرقم - من السجل القديم فقط
    if max_z >= 2.0 or avg_z >= 1.8:
        level = f"🔥 العب الان - الاشارة قوية جدا | أقوى رقم {best_num} Z={max_z:.2f}"
    elif max_z >= 1.5:
        level = f"✅ اشارة قوية | أقوى رقم {best_num} Z={max_z:.2f}"
    else:
        level = f"اشارة ضعيفة - أقوى Z={max_z:.2f}"
    return top4, avg_z, level

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت شغال ✅")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_pred, try_count, history
    text = update.message.text.strip()
    if text in ["مسح", "clear"]:
        history = []
        current_pred = None
        try_count = 0
        save_history(history)
        await update.message.reply_text("تم المسح ✅")
        return
    parts = re.findall(r'\d+', text)
    if not parts: return
    nums = [int(p) for p in parts if 0 <= int(p) <= 36]
    if not nums: return

    # أهم خطوة: إذا مافي توقع، نحسبه من السجل القديم قبل ما نسجل الرقم الجديد
    if current_pred is None:
        pred, z, reason = get_smart_pred()
        if pred is not None:
            current_pred = pred
            try_count = 0
            # نرسل التوقع قبل ما نسجل الرقم الجديد
            await update.message.reply_text(f"{reason}\n🎯 العب على: {current_pred}")
            # لا نسجل الرقم الحين، ننتظر الرقم الجاي حتى نشوف هل فاز او لا
            # بس نسجله بالسجل حتى لا يضيع
            history.extend(nums)
            save_history(history)
            return

    # إذا عندنا توقع جاهز، نشيك على الأرقام الجديدة هل فازت او لا
    result_msg = ""
    for num in nums:
        history.append(num)
        if num in current_pred:
            result_msg = f"✅ {num} فاز من {current_pred}"
            current_pred = None
            try_count = 0
            break
        else:
            try_count += 1
            result_msg = f"❌ {num} مو من {current_pred} | {try_count}/10"
            if try_count >= WIN_LIMIT:
                result_msg += " - تصفير"
                current_pred = None
                try_count = 0
                break
    save_history(history)

    if current_pred is None:
        pred, z, reason = get_smart_pred()
        if pred is not None:
            current_pred = pred
            try_count = 0
            await update.message.reply_text(f"{result_msg} | المجموع: {len(history)}\n{reason}\n🎯 التوقع الجديد العب عليه: {current_pred}")
        else:
            await update.message.reply_text(f"{result_msg} | المجموع: {len(history)}\n{reason}")
    else:
        await update.message.reply_text(f"{result_msg} | المجموع: {len(history)}\n📌 التوقع الحالي العب عليه: {current_pred}")

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
