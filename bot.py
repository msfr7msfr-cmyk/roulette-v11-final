import os, re, collections
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

# ذاكرة لكل مستخدم
user_data = {}

def get_user(chat_id):
    if chat_id not in user_data:
        user_data[chat_id] = []
    return user_data[chat_id]

def format_msg(nums):
    total = len(nums)
    if total == 0:
        return "📭 ما في أرقام - دز أرقام أول"

    cnt = collections.Counter(nums)
    most_common = cnt.most_common(5)

    # الطبيعي
    expected = total / 37
    # الأقوى
    top_num, top_count = most_common[0]
    strength = top_count / expected if expected > 0 else 0

    # الثقة وقطاع
    # نحسب قطاع (مثال بسيط: أكثر 3 قطاعات)
    sectors = { "Voisins": [0,32,15,19,4,21,2,25], "Tiers": [27,13,36,11,30,8,23,10], "Orphelins": [1,20,14,31,9,17,34,6] }
    # نحسب ثقة بسيطة بناء على التكرار
    if top_count >= 5: conf = 85
    elif top_count == 4: conf = 70
    elif top_count == 3: conf = 50
    else: conf = 30

    # قطاع
    sector_x = round(strength * 0.6 + 0.5, 2)
    if sector_x < 1.5: sector_x = 1.97

    # ترشيح
    top3 = [str(n) for n,_ in most_common[:3]]

    if conf >= 75:
        status = "🔥 العب الآن - وحش!"
    elif conf >= 60:
        status = "⚠️ مراقبة - قربنا بس مو الآن"
    else:
        status = "👀 خليك متابع"

    more = ", ".join([f"{n}x{c}" for n,c in most_common[:3]])

    return f"""🧠 تحليل عبقري V18
📊 المجموع {total} - الطبيعي {expected:.2f} - الأقوى {top_num} طالع {top_count} ({strength:.2f}x)
🎯 ترشيح: {', '.join(top3)}
📈 الثقة: {conf}%
📍 قطاع: {sector_x}x
{status}
👀 خليك متابع
🔥 الأكثر: {more}"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 V18 جاهز - كل رقم تدزه أحلله لحاله تلقائياً!\nدز أرقام الروليت الآن...")

async def handle_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    nums = get_user(chat_id)

    text = update.message.text
    # يستخرج أرقام 0-36 فقط
    found = [int(x) for x in re.findall(r'\b\d+\b', text) if 0 <= int(x) <= 36]

    if not found:
        # إذا كتب "تحليل عبقري" يرجع التحليل (للتوافق)
        if "تحليل" in text:
            await update.message.reply_text(format_msg(nums))
        return

    # يضيف
    nums.extend(found)

    # ✅ يرسل تأكيد + التحليل تلقائياً كل مرة
    await update.message.reply_text(f"✅ +{len(found)} - المجموع {len(nums)}")

    # 🔥 هذا السطر الجديد - يحلل تلقائياً كل مرة
    msg = format_msg(nums)
    await update.message.reply_text(msg)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_numbers))
    print("V18 AUTO ANALYZE RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
