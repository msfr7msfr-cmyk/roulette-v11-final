from flask import Flask, request
import os
from collections import Counter
from telegram import Bot
import asyncio

app = Flask(__name__)
TOKEN = os.environ.get("BOT_TOKEN")
bot = Bot(token=TOKEN)

# تعريف قطاعات العجلة الحقيقية
VOISINS = {22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25}
TIERS = {27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9}
ORPHELINS = {1,20,14,31,9,17,34,6} # الباقي

def get_sector(n):
    if n in VOISINS:
        return "Voisins"
    elif n in TIERS:
        return "Tiers"
    else:
        return "Orphelins"

def get_wheel_neighbors(n):
    wheel = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
    try:
        idx = wheel.index(n)
        return [wheel[(idx-1)%37], wheel[(idx+1)%37], wheel[(idx-2)%37], wheel[(idx+2)%37]]
    except:
        return []

def analyze_v25(history):
    if len(history) < 25:
        return None, "انتظر 25 رقم على الاقل"

    last = history[-1]
    last2 = history[-2] if len(history) >=2 else None

    # 1. Gap
    gaps = {}
    for num in range(37):
        try:
            last_pos = len(history) - 1 - history[::-1].index(num)
            gaps[num] = len(history) - 1 - last_pos
        except ValueError:
            gaps[num] = 999

    # 2. ترددات
    c50 = Counter(history[-50:])
    c20 = Counter(history[-20:])
    c10 = Counter(history[-10:])

    # 3. Transition: ماذا يأتي بعد last ؟
    trans = Counter()
    for i in range(len(history)-1):
        if history[i] == last:
            nxt = history[i+1]
            if nxt!= last and nxt!= last2: # لا نحصي التكرار
                trans[nxt] += 1

    # 4. قطاع حار باخر 20
    sector_last20 = [get_sector(x) for x in history[-20:]]
    sector_counts = Counter(sector_last20)
    hot_sector = sector_counts.most_common(1)[0][0]

    scores = {}
    details = {}

    for num in range(37):
        # قانون الحرق: ممنوع اخر رقمين
        if num == last or num == last2:
            continue

        score = 0
        reason = []

        # وزن Gap الذكي (3-18 هو المثالي)
        gap = gaps[num]
        if 3 <= gap <= 8:
            score += 18
            reason.append(f"Due قوي Gap={gap}")
        elif 9 <= gap <= 15:
            score += 12
            reason.append(f"Due متوسط Gap={gap}")
        elif 16 <= gap <= 25:
            score += 5

        # وزن تردد بدون اخر 5 لفات (حار بس مو محروق)
        history_without_last5 = history[:-5]
        c_hot = Counter(history_without_last5[-20:])
        if c_hot[num] >= 2:
            score += c_hot[num] * 4
            reason.append(f"حار x{c_hot[num]}")

        # وزن الانتقال - اهم شي
        if trans[num] > 0:
            score += trans[num] * 10
            reason.append(f"يجي ورا {last} ({trans[num]}مرات)")

        # بونص القطاع الحار
        if get_sector(num) == hot_sector and gap > 2:
            score += 7
            reason.append(f"قطاع حار {hot_sector}")

        # بونص جيران رقم حار جدا
        # اذا رقم حار جدا، جيرانه ياخذون بونص
        for hot_num, cnt in c20.most_common(3):
            if num in get_wheel_neighbors(hot_num) and num!= last:
                score += 3

        if score > 0:
            scores[num] = score
            details[num] = " + ".join(reason)

    # رتب وخذ توب 5
    sorted_nums = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top5 = [n for n,s in sorted_nums[:5]]

    return top5, hot_sector, gaps, trans, details, last

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or 'message' not in data:
        return 'ok'

    chat_id = data['message']['chat']['id']
    text = data['message'].get('text','')

    # استخراج ارقام
    import re
    nums = [int(x) for x in re.findall(r'\b(?:[0-2]?[0-9]|3[0-6])\b', text)]
    # فلترة 0-36 فقط واذا نص طويل
    nums = [n for n in nums if 0 <= n <= 36]

    if len(nums) < 10:
        asyncio.run(bot.send_message(chat_id=chat_id, text="دزلي 25 رقم على الاقل، كل قائمة بسطر او مفصولة بفواصل"))
        return 'ok'

    result = analyze_v25(nums)
    if result[0] is None:
        asyncio.run(bot.send_message(chat_id=chat_id, text=result[1]))
        return 'ok'

    top5, hot_sector, gaps, trans, details, last = result

    msg = f"""🧠 V25 الذكي جدا - مو عشوائي

📍 اخر رقم طالع: {last} (محروق ما نلعبه)
🔥 قطاع حار: {hot_sector}
🚫 ممنوع: {nums[-2]}, {nums[-1]}

🎯 توقع ذكي (5 ارقام):
{top5}

📊 ليش هذوله؟
"""
    for n in top5:
        msg += f"• {n} | Gap:{gaps[n]} | {details.get(n,'')}\n"

    msg += f"\n♻️ ورا {last} بالعادة يجي: {trans.most_common(3)}\nثابت 4 لفات فقط"

    asyncio.run(bot.send_message(chat_id=chat_id, text=msg))
    return 'ok'

@app.route('/')
def home():
    return "V25 SMART LIVE"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
