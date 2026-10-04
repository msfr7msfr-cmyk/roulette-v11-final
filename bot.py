import os
import re
import logging
from collections import Counter, deque
from flask import Flask
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "V11 Live - Bot is Running"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
logging.basicConfig(level=logging.INFO)

RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMS = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}
history = deque(maxlen=50)

def get_color(n):
    if n == 0:
        return "أخضر"
    if n in RED_NUMS:
        return "أحمر"
    return "أسود"

def parse_number(text):
    m = re.search(r'\b([0-3]?[0-9]|36)\b', text)
    if m:
        try:
            num = int(m.group(1))
            if 0 <= num <= 36:
                return num
        except:
            pass
    return None

def analyze():
    if not history:
        return "ما عندي أرقام بعد، دزلي أول رقم"
    last = list(history)
    counter = Counter(last)
    total = len(last)
    reds = sum(1 for x in last if x in RED_NUMS)
    blacks = sum(1 for x in last if x in BLACK_NUMS)
    zeros = sum(1 for x in last if x == 0)
    most_common = counter.most_common(3)
    if reds > blacks + 2:
        suggest = "⚫ أسود (تشبع أحمر)"
    elif blacks > reds + 2:
        suggest = "🔴 أحمر (تشبع أسود)"
    else:
        suggest = "⚪ تابع النمط - لا تراهن بقوة"
    evens = sum(1 for x in last if x !=0 and x %2==0)
    odds = sum(1 for x in last if x %2==1)
    msg = f"""
🎰 **تحليل V11 - {total} أرقام**

**آخر 5:** {' - '.join(map(str, list(last)[-5:]))}

📊 **ألوان:**
🔴 أحمر: {reds} ({reds/total*100:.0f}%)
⚫ أسود: {blacks} ({blacks/total*100:.0f}%)
🟢 صفر: {zeros}

🔥 **الأكثر تكراراً:** {', '.join(f"{n}({c}x)" for n,c in most_common)}

💡 **التوقع القادم:** {suggest}
"""
    return msg

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ تفعيل التحليل الفوري", callback_data="enable")],
        [InlineKeyboardButton("📊 تحليل الآن", callback_data="analyze")],
        [InlineKeyboardButton("📋 القناة الحالية", callback_data="current"), InlineKeyboardButton("🗑️ مسح السجل", callback_data="clear")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎰 **بوت الروليت V11 شغال!**\n\nدزلي الأرقام بهالشكل:\n`رقم 23 أحمر`\nأو بس `23`\n\nالبوت راح يحلل فورياً.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["مسح", "/clear", "clear"]:
        history.clear()
        await update.message.reply_text("🗑️ تم مسح السجل")
        return
    num = parse_number(text)
    if num is not None:
        history.append(num)
        color = get_color(num)
        await update.message.reply_text(f"✅ استلمت: **رقم {num} {color}**\nجاري التحليل...", parse_mode="Markdown")
        analysis = analyze()
        keyboard = [[InlineKeyboardButton("📊 تحليل مفصل", callback_data="analyze")], [InlineKeyboardButton("🗑️ مسح", callback_data="clear")]]
        await update.message.reply_text(analysis, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        if len(text) < 10:
            await update.message.reply_text(f"دزلي رقم مثل `23`")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "enable":
        await query.message.reply_text("✅ تم تفعيل التحليل الفوري!")
    elif query.data == "analyze":
        await query.message.reply_text(analyze(), parse_mode="Markdown")
    elif query.data == "clear":
        history.clear()
        await query.message.reply_text("🗑️ تم مسح السجل")
    elif query.data == "current":
        if history:
            await query.message.reply_text(f"📋 السجل الحالي ({len(history)} رقم):\n{list(history)}")
        else:
            await query.message.reply_text("السجل فارغ")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot V11 Starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
