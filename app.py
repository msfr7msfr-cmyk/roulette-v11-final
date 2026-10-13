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
        if c < 2: continue
        std = math.sqrt(expected * (36/37))
        z = (c - expected) / std if std > 0 else 0
        scores.append((num, c, z))

    if not scores:
        return None, 0, "لا توجد بيانات"

    scores.sort(key=lambda x: x[2], reverse=True)

    if scores[0][2] < 1.5:
        return None, 0, f"لا توجد إشارة - أقوى Z = {scores[0][2]:.2f}"

    top4 = [s[0] for s in scores[:4]]
    avg_z = sum(s[2] for s in scores[:4]) / 4

    # المستوى يعتمد على avg_z نفسه اللي يظهر لك
    if avg_z >= 2.5:
        level = "🔥🔥 العب الان - الاشارة قوية جدا جدا"
    elif avg_z >= 2.2:
        level = "🔥 العب الان - الاشارة قوية جدا"
    elif avg_z >= 1.8:
        level = "✅ اشارة قوية"
    else:
        level = "اشارة ضعيفة"

    return top4, avg_z, level

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت الذكي شغال ✅\nارسل ارقامك دفعة واحدة او رقم رقم")

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

    nums = []
    for part in parts:
        n = int(part)
        if 0 <= n <= 36:
            nums.append(n)
    if not nums: return

    last_result = ""
    last_level = ""

    for num in nums:
        if current_pred is None:
            pred, z, reason = get_smart_pred()
            if pred is None:
                history.append(num)
                continue
            current_pred = pred
            last_level = reason
            try_count = 0

        history.append(num)

        if num in current_pred:
            last_result = f"✅ {num} فاز من {current_pred}"
            current_pred = None
            try_count = 0
        else:
            try_count += 1
            last_result = f"❌ {num} مو من {current_pred} | {try_count}/10"
            if try_count >= WIN_LIMIT:
                last_result += " - تم تصفير التوقع"
                current_pred = None
                try_count = 0

    save_history(history)

    if len(nums) == 1:
        if current_pred is None:
            pred, z, reason = get_smart_pred()
            if pred is not None:
                current_pred = pred
                try_count = 0
                await update.message.reply_text(f"✅ {nums[0]} تم تسجيله\n{reason}\n🎯 التوقع الجديد: {current_pred} | Z = {z:.2f} | المجموع: {len(history)}")
            else:
                await update.message.reply_text(f"⏳ {nums[0]} تم تسجيله | {reason} | المجموع: {len(history)}")
        else:
            await update.message.reply_text(f"{last_result} | المجموع: {len(history)}\n📌 التوقع: {current_pred}\n{last_level}")
        return

    if current_pred is None:
        pred, z, reason = get_smart_pred()
        if pred is not None:
            current_pred = pred
            try_count = 0
            await update.message.reply_text(
                f"تم تسجيل {len(nums)} رقم ✅ | المجموع: {len(history)}\n"
                f"{last_result}\n"
                f"{reason}\n"
                f"🎯 التوقع الجديد: {current_pred} | Z = {z:.2f}"
            )
            return

    await update.message.reply_text(
        f"تم تسجيل {len(nums)} رقم ✅ | المجموع: {len(history)}\n"
        f"{last_result}\n"
        f"📌 التوقع الحالي: {current_pred}\n"
        f"{last_level}"
    )

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
