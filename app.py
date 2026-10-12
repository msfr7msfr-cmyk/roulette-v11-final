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
    # لازم 50 رقم على الأقل حتى نحلل
    if len(history) < 50:
        return None, 0, "نحتاج 50 رقم على الأقل للتحليل"

    last = history[-200:]
    n = len(last)
    counts = Counter(last)

    # لكل رقم نحسب Z-Score: هل تكراره أعلى من المتوقع بشكل حقيقي؟
    # المتوقع = n / 37
    expected = n / 37
    # الانحراف المعياري للتوزيع الثنائي
    scores = []
    for num, c in counts.items():
        if c < 3: continue
        # z = (actual - expected) / sqrt(expected * (1 - 1/37))
        std = math.sqrt(expected * (36/37))
        z = (c - expected) / std if std > 0 else 0
        scores.append((num, c, z))

    scores.sort(key=lambda x: x[2], reverse=True)
    # نأخذ فقط الأرقام القوية جداً
    strong = [s for s in scores if s[2] >= 1.8]

    if len(strong) < 4:
        return None, 0, f"لا توجد إشارة قوية - أقوى Z = {scores[0][2]:.2f} فقط"

    top4 = [s[0] for s in strong[:4]]
    avg_z = sum(s[2] for s in strong[:4]) / 4
    return top4, avg_z, "إشارة قوية"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت الذكي شغال ✅ ارسل رقم 0-36")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_pred, try_count
    text = update.message.text.strip()
    if text in ["مسح", "clear"]:
        global history
        history = []
        current_pred = None
        try_count = 0
        save_history(history)
        await update.message.reply_text("تم المسح ✅")
        return

    parts = re.findall(r'\d+', text)
    if not parts: return

    for part in parts:
        num = int(part)
        if not (0 <= num <= 36): continue

        # إذا ماعندنا توقع ثابت، نحاول نطلع واحد جديد ذكي
        if current_pred is None:
            pred, z, reason = get_smart_pred()
            if pred is None:
                history.append(num)
                save_history(history)
                await update.message.reply_text(f"⏳ {num} تم تسجيله | {reason} | المجموع: {len(history)}")
                continue
            current_pred = pred
            try_count = 0

        history.append(num)
        save_history(history)

        if num in current_pred:
            await update.message.reply_text(f"✅ {num} من {current_pred}\n🎯 فوز - تم تثبيت التوقع الجديد للجولة القادمة")
            current_pred = None
            try_count = 0
        else:
            try_count += 1
            msg = f"❌ {num} مو من {current_pred} | {try_count}/10\nباقي: {current_pred} | المجموع: {len(history)}"
            if try_count >= WIN_LIMIT:
                msg += f"\n🔄 10 خسائر - التوقع ضعيف، راح نعيد التحليل من جديد"
                current_pred = None
                try_count = 0
            await update.message.reply_text(msg)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
