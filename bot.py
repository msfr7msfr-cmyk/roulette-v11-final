import os, re, collections
from flask import Flask
import threading
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
user_data = {}

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V18 AUTO RUNNING"

def get_user(cid):
    if cid not in user_data: user_data[cid] = []
    return user_data[cid]

def format_msg(nums):
    total = len(nums)
    if total == 0: return "📭 دز أرقام"
    cnt = collections.Counter(nums)
    most = cnt.most_common(5)
    expected = total/37
    top_num, top_count = most[0]
    strength = top_count/expected if expected else 0
    conf = 85 if top_count>=5 else 70 if top_count==4 else 50 if top_count==3 else 30
    sector_x = 1.97
    top3 = [str(n) for n,_ in most[:3]]
    status = "🔥 العب الآن" if conf>=75 else "⚠️ مراقبة - قربنا بس مو الآن" if conf>=50 else "👀 خليك متابع"
    more = ", ".join([f"{n}x{c}" for n,c in most[:3]])
    return f"🧠 تحليل عبقري V18\n📊 المجموع {total} - الطبيعي {expected:.2f} - الأقوى {top_num} طالع {top_count} ({strength:.2f}x)\n🎯 ترشيح: {', '.join(top3)}\n📈 الثقة: {conf}%\n📍 قطاع: {sector_x}x\n{status}\n👀 خليك متابع\n🔥 الأكثر: {more}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["تحليل عبقري 🧠", "مسح 🗑️"]]
    markup = ReplyKeyboardMarkup(kb, resize_keyboard=True)
    await update.message.reply_text("🧠 V18 جاهز - كل رقم تدزه أحلله لحاله!", reply_markup=markup)

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    nums = get_user(cid)
    text = update.message.text or ""
    if "مسح" in text:
        nums.clear()
        await update.message.reply_text("🗑️ تم المسح")
        return
    if "تحليل" in text:
        await update.message.reply_text(format_msg(nums))
        return
    found = [int(x) for x in re.findall(r'\b\d+\b', text) if 0 <= int(x) <= 36]
    if not found: return
    nums.extend(found)
    await update.message.reply_text(f"✅ +{len(found)} - المجموع {len(nums)}")
    await update.message.reply_text(format_msg(nums))

def run_bot():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)
