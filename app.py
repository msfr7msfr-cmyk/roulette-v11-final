import os, json, re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
HISTORY_FILE = "history.json"

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
    def handle_number(self, num):
        self.history.append(num)
        save_history(self.history)
        self.try_count += 1
        if num in self.current_prediction:
            self.try_count = 0
            return f"✅ فوز! {num} من {self.current_prediction} | المجموع: {len(self.history)} رقم"
        if self.try_count >= 10:
            self.current_prediction = [4, 10, 16, 33] if self.current_prediction == [0, 10, 16, 33] else [0, 10, 16, 33]
            self.try_count = 0
            return f"❌ 10 خسارات ابدلهم كلهم ♻️\nتوقع جديد: {self.current_prediction}"
        return f"{self.try_count}/10 | {self.current_prediction} مو من {num} ❌\nباقي: {self.current_prediction} | المجموع: {len(self.history)}"

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
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()

if __name__ == "__main__":
    main()
