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
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(h):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(h, f)

class OldBot:
    def __init__(self):
        self.history = load_history()
        self.current_prediction = [0, 10, 16, 33]
        self.try_count = 0

    def reset(self):
        self.history = []
        save_history([])
        self.current_prediction = [0, 10, 16, 33]
        self.try_count = 0

    def deceleration_check(self):
        # 4. DecelerationPhysics - يشتغل بعد 50 رقم
        if len(self.history) < 50:
            return ""
        window = self.history[-100:]
        expected = len(window) / 37.0 # المتوقع لكل رقم
        total_actual = sum(window.count(n) for n in self.current_prediction)
        expected_total = expected * len(self.current_prediction)
        ratio = total_actual / expected_total if expected_total > 0 else 0
        # اذا التوقع ضعيف اقل من 1.5 ضعف المتوقع
        if ratio < 1.5:
            return f"\n⚠️ التباطؤ ضعيف - انتظر | القوة: {ratio:.2f}x | تكرار التوقع في اخر {len(window)}: {total_actual} من {expected_total:.1f} متوقع"
        return f"\n📊 قوة التوقع: {ratio:.2f}x | تكرار: {total_actual}"

    def handle_number(self, num):
        self.history.append(num)
        save_history(self.history)
        self.try_count += 1
        decel = self.deceleration_check()
        if num in self.current_prediction:
            self.try_count = 0
            return f"✅ فوز! {num} من {self.current_prediction} | المجموع: {len(self.history)} رقم{decel}"
        if self.try_count >= 10:
            self.current_prediction = [4, 10, 16, 33] if self.current_prediction == [0, 10, 16, 33] else [0, 10, 16, 33]
            self.try_count = 0
            return f"❌ 10 خسارات ابدلهم كلهم ♻️\nتوقع جديد: {self.current_prediction}{decel}"
        return f"{self.try_count}/10 | {self.current_prediction} مو من {num} ❌\nباقي: {self.current_prediction} | المجموع: {len(self.history)}{decel}"

bot = OldBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot.reset()
    await update.message.reply_text("بوتك القديم جاهز - مع الأداة الجديدة ✅\nارسل مجموعة ارقام او رقم رقم")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "مسح":
        bot.reset()
        await update.message.reply_text("🗑️ مسح تم - بدأنا من جديد")
        return
    nums = [int(x) for x in re.findall(r'\d+', text) if 0 <= int(x) <= 36]
    if not nums:
        await update.message.reply_text("ارسل رقم 0-36 او لصق قائمة ارقام")
        return
    if len(nums) == 1:
        result = bot.handle_number(nums[0])
        await update.message.reply_text(result)
    else:
        for n in nums:
            result = bot.handle_number(n)
        await update.message.reply_text(f"✅ تم تسجيل {len(nums)} رقم\nالمجموع الكلي: {len(bot.history)} رقم\nآخر نتيجة: {result}")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()

if __name__ == "__main__":
    main()
