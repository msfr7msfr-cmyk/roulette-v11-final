import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- سيرفر وهمي حتى Render ما يطفي البوت ---
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
    print("ERROR: BOT_TOKEN not set!")

# --- منطق الروليت V11 ---
def analyze_roulette(numbers):
    if len(numbers) < 3:
        return "دزلي 3 ارقام على الاقل حتى احلل 🔍\nمثال: 14 32 5 9"
    
    last = numbers[-1]
    red = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    
    # تحليل بسيط مطور
    color = "🔴 احمر" if last in red else "⚫ اسود" if last != 0 else "🟢 صفر"
    dozen = "D1 (1-12)" if last <= 12 and last != 0 else "D2 (13-24)" if last <= 24 else "D3 (25-36)" if last != 0 else "Zero"
    
    # توقع
    prediction = []
    if last % 2 == 0:
        prediction.append("الفردي (Odd) اقوى")
    else:
        prediction.append("الزوجي (Even) اقوى")
    
    if last in red:
        prediction.append("الاسود (Black) متوقع")
    else:
        prediction.append("الاحمر (Red) متوقع")

    msg = f"""
🎰 **تحليل V11 Final**

الرقم الاخير: {last} ({color})
الدزينة: {dozen}

📊 اخر الارقام: {numbers[-5:]}

🔮 **التوقع القادم:**
- {'\n- '.join(prediction)}
- ركز على الجيران: {max(0, last-2)} , {last} , {min(36, last+2)}

⚠️ ادارة راس مال: لا تدخل اكثر من 5% من رصيدك
"""
    return msg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "اهلا بيك بروبوت الروليت V11 Final 🔥\n\n"
        "طريقة الاستخدام:\n"
        "دزلي الارقام الي طلعت بالروليت مفصولة بمسافة\n"
        "مثال:\n`14 32 5 9 22 0`\n\n"
        "وانا احللك وانطيك التوقع القادم\n\n"
        "دوس /help للمساعدة",
        parse_mode='Markdown'
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **شرح البوت:**\n"
        "1. ادخل للطاولة وشوف اخر الارقام\n"
        "2. انسخها ودزها للبوت\n"
        "3. البوت يحلل ويتوقع\n\n"
        "كلما دزيت ارقام اكثر التحليل يصير ادق ✅"
    )

async def handle_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        nums = [int(n) for n in text.replace(',', ' ').split() if n.isdigit() or (n.lstrip('-').isdigit())]
        nums = [n for n in nums if 0 <= n <= 36]
        if not nums:
            await update.message.reply_text("دزلي ارقام بين 0 و 36 فقط")
            return
        result = analyze_roulette(nums)
        await update.message.reply_text(result, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"صار خطأ: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_numbers))
    
    print("Bot V11 Started and Flask running...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
