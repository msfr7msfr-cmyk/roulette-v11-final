import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ما يطفي البوت Render سيرفر وهمي حتى ---
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Roulette Bot V11 is Live!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# --- توكن البوت ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in Render Environment!")

# --- منطق الروليت V11 ---
# هنا تگدر تضيف الكود القديم مالك اذا عندك
# هذا مثال بسيط شغال

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎰 بوت الروليت V11 شغال! دزلي الأرقام...")

async def handle_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # هنا تحط منطق التحليل مالتك القديم
    await update.message.reply_text(f"استلمت: {text}\nجاري التحليل...")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_numbers))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
