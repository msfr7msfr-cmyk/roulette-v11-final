import os, json, re, threading
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask

TOKEN = os.getenv("BOT_TOKEN")
HISTORY_FILE = "history.json"

app_web = Flask(__name__)
@app_web.route('/')
def home():
    return "Bot is Alive!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(h):
    with open(HISTORY_FILE, "w") as f:
        json.dump(h, f)

history = load_history()
fixed_preds = [[0, 10, 16, 33], [4, 10, 16, 33]]
fixed_index = 0
try_count = 0
WIN_LIMIT = 10

def get_dynamic():
    last = history[-100:]
    order = []
    seen = {}
    for n in last:
        seen[n] = seen.get(n, 0) + 1
        if seen[n] == 2 and n not in order:
            order.append(n)
    return order[-4:]

def get_active_pred():
    dyn = get_dynamic()
    if len(dyn) == 4:
        return dyn, "ديناميكي"
    return fixed_preds[fixed_index], "ثابت"

def deceleration(pred):
    if len(history) < 20:
        return 0, 0
    last = history[-100:]
    actual = sum(1 for n in last if n in pred)
    expected = len(last) * len(pred) / 37
    return (actual / expected if expected > 0 else 0), actual

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت شغال ✅ ارسل رقم 0-36")

async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global history, try_count, fixed_index
    history = []
    try_count = 0
    fixed_index = 0
    save_history(history)
    await update.message.reply_text("تم مسح السجل ✅ ابدأ من جديد")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global try_count, fixed_index
    text = update.message.text.strip()

    # أمر المسح
    if text == "مسح" or text == "/مسح" or text.lower() == "clear":
        await clear_history(update, context)
        return

    parts = re.findall(r'\d+', text)
    if not parts:
        return

    # اذا قائمة طويلة - نعالج بدون ازعاج برسائل كثيرة
    is_bulk = len(parts) > 5
    last_msg = ""

    for part in parts:
        num = int(part)
        if not (0 <= num <= 36):
            continue
        history.append(num)
        save_history(history)

        active_pred, mode = get_active_pred()
        strength, actual = deceleration(active_pred)

        msg = ""
        if num in active_pred:
            msg += f"✅ {num} من {active_pred}\n"
            try_count = 0
        else:
            try_count += 1
            msg += f"❌ {num} مو من {active_pred} | {try_count}/10\n"
            msg += f"باقي: {active_pred} | المجموع: {len(history)}\n"
            if try_count >= WIN_LIMIT:
                fixed_index = 1 - fixed_index
                try_count = 0
                msg += f"🔄 تبديل الثابت إلى {fixed_preds[fixed_index]}\n"

        if strength >= 1.5:
            msg += f"✅ التباطؤ قوي - العب | القوة: {strength:.2f}x | تكرار التوقع في اخر 100: {actual} من {len(history[-100:])*len(active_pred)/37:.1f} متوقع"
        elif strength > 0:
            msg += f"⚠️ التباطؤ ضعيف - انتظر | القوة: {strength:.2f}x | تكرار التوقع في اخر 100: {actual} من {len(history[-100:])*len(active_pred)/37:.1f} متوقع"

        if mode == "ديناميكي":
            msg += f"\n🔄 التوقع الديناميكي: {active_pred}"

        last_msg = msg
        if not is_bulk:
            await update.message.reply_text(msg)

    if is_bulk:
        await update.message.reply_text(f"تمت معالجة {len(parts)} رقم ✅\n{last_msg}")

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("مسح", clear_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
