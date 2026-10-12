from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8246479435:AAHLZ15QJ45TuEtzdI-IHkaiH9pBMkdlLdA"

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]

class DecelerationPhysics:
    def __init__(self, mu=0.08, g=9.81, r=0.4):
        self.alpha = mu * g / r
    def calc_score(self, number, history):
        if len(history) < 50:
            return 0.0
        recent = history[-100:]
        count = sum(1 for x in recent if x == number)
        expected = len(recent) / 37.0
        if expected == 0:
            return 0.0
        return count / expected
    def is_approved(self, candidates, history):
        approved = 0
        for n in candidates:
            if self.calc_score(n, history) >= 1.5:
                approved += 1
        return approved >= 3

class OldBot:
    def __init__(self):
        self.history = []
        self.physics = DecelerationPhysics()
        self.current_prediction = [0, 10, 16, 33]
        self.try_count = 0
    def reset(self):
        self.history = []
        self.current_prediction = [0, 10, 16, 33]
        self.try_count = 0
    def handle_number(self, num):
        self.history.append(num)
        self.try_count += 1
        if num in self.current_prediction:
            self.try_count = 0
            return f"✅ فوز! {num} من {self.current_prediction}"
        if self.try_count >= 10:
            if self.current_prediction == [0, 10, 16, 33]:
                self.current_prediction = [4, 10, 16, 33]
            else:
                self.current_prediction = [0, 10, 16, 33]
            self.try_count = 0
            return f"❌ 10 خسارات ابدلهم كلهم ♻️\nتوقع جديد: {self.current_prediction}"
        if len(self.history) >= 50:
            if not self.physics.is_approved(self.current_prediction, self.history):
                return f"{self.try_count}/10 | {self.current_prediction} مو من {num} ❌\nباقي: {self.current_prediction}\n⚠️ الأداة الجديدة: التباطؤ ضعيف - انتظر"
        return f"{self.try_count}/10 | {self.current_prediction} مو من {num} ❌\nباقي: {self.current_prediction}"

bot = OldBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot.reset()
    await update.message.reply_text("بوتك القديم جاهز - مع الأداة الجديدة ✅\nارسل رقم")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot.reset()
    await update.message.reply_text("🗑️ مسح تم")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "مسح":
        await clear(update, context)
        return
    try:
        num = int(text)
        if 0 <= num <= 36:
            result = bot.handle_number(num)
            await update.message.reply_text(result)
        else:
            await update.message.reply_text("ارسل رقم 0-36")
    except:
        await update.message.reply_text("ارسل رقم فقط")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()

if __name__ == "__main__":
    main()
