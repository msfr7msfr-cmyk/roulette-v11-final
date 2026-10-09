from flask import Flask, request
import os
import re
import requests
from collections import Counter

app = Flask(__name__)
TOKEN = os.environ.get("BOT_TOKEN")

VOISINS = {22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25}
TIERS = {27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9}

def get_sector(n):
    if n in VOISINS:
        return "Voisins"
    elif n in TIERS:
        return "Tiers"
    else:
        return "Orphelins"

def send_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"send error {e}")

def analyze_v25(history):
    if len(history) < 25:
        return None
    last = history[-1]
    last2 = history[-2]

    gaps = {}
    for num in range(37):
        try:
            last_pos = len(history) - 1 - history[::-1].index(num)
            gaps[num] = len(history) - 1 - last_pos
        except:
            gaps[num] = 999

    c20 = Counter(history[-20:])

    trans = Counter()
    for i in range(len(history)-1):
        if history[i] == last:
            nxt = history[i+1]
            if nxt!= last and nxt!= last2:
                trans[nxt] += 1

    sector_counts = Counter([get_sector(x) for x in history[-20:]])
    hot_sector = sector_counts.most_common(1)[0][0] if sector_counts else "Voisins"

    scores = {}
    details = {}
    for num in range(37):
        if num == last or num == last2:
            continue
        score = 0
        reason = []
        gap = gaps[num]
        if 3 <= gap <= 8:
            score += 18
            reason.append(f"Due Gap={gap}")
        elif 9 <= gap <= 15:
            score += 12
            reason.append(f"Gap={gap}")

        history_without_last5 = history[:-5]
        c_hot = Counter(history_without_last5[-20:])
        if c_hot[num] >= 2:
            score += c_hot[num] * 4
            reason.append(f"حار x{c_hot[num]}")

        if trans[num] > 0:
            score += trans[num] * 10
            reason.append(f"ورا {last} {trans[num]}x")

        if get_sector(num) == hot_sector and gap > 2:
            score += 7

        if score > 0:
            scores[num] = score
            details[num] = " + ".join(reason)

    top5 = [n for n,s in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]]
    return top5, hot_sector, gaps, trans, details, last

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or 'message' not in data:
        return 'ok'
    chat_id = data['message']['chat']['id']
    text = data['message'].get('text','')

    nums = [int(x) for x in re.findall(r'\b(?:[0-2]?[0-9]|3[0-6])\b', text)]
    nums = [n for n in nums if 0 <= n <= 36]

    if len(nums) < 10:
        send_msg(chat_id, "دزلي 25 رقم على الاقل")
        return 'ok'

    res = analyze_v25(nums)
    if res is None:
        send_msg(chat_id, "انتظر 25 رقم على الاقل")
        return 'ok'

    top5, hot_sector, gaps, trans, details, last = res
    msg = f"🧠 V25 الذكي جدا - مو عشوائي\n\n📍 اخر: {last} (محروق)\n🔥 قطاع حار: {hot_sector}\n🚫 ممنوع: {nums[-2]}, {nums[-1]}\n\n🎯 توقع ذكي (بدون تكرار):\n{top5}\n\n"
    for n in top5:
        msg += f"• {n} Gap:{gaps[n]} | {details.get(n,'')}\n"
    msg += f"\n♻️ ورا {last} يجي: {trans.most_common(3)}\nثابت 4 لفات"

    send_msg(chat_id, msg)
    return 'ok'

@app.route('/')
def home():
    return "V25 SMART LIVE - FIXED"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
