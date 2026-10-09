from flask import Flask, request
import os
import requests
from collections import defaultdict, Counter

app = Flask(__name__)
TOKEN = os.environ.get("BOT_TOKEN")

history_data = defaultdict(list)
pred_data = defaultdict(list)
pred_fails = defaultdict(int)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def make_prediction(nums, exclude=None):
    # 1- حساب البارد
    gaps = {i: 999 for i in range(37)}
    for idx, val in enumerate(reversed(nums)):
        if gaps[val] == 999:
            gaps[val] = idx
    sorted_cold = sorted(gaps.items(), key=lambda x: x[1], reverse=True)
    all_cold = [x[0] for x in sorted_cold]

    # 2- حساب الحار (اخر 25 رقم)
    last_25 = nums[-25:] if len(nums) >= 25 else nums
    freq = Counter(last_25)
    hot = [n for n, c in freq.most_common(2)]

    # 3- نبني التوقع 2 هوت + 4 كولد
    pred = []
    for h in hot:
        if h not in pred:
            pred.append(h)

    for c in all_cold:
        if len(pred) >= 6:
            break
        if c not in pred:
            if exclude and c in exclude and len(exclude) == 6:
                # اذا فشل 10 مرات جيب غير المستبعد
                continue
            pred.append(c)

    # اذا استبعدنا وقل العدد كمل من البارد
    if exclude:
        for c in all_cold:
            if len(pred) >= 6:
                break
            if c not in pred:
                pred.append(c)

    return pred[:6], gaps

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data or "text" not in data["message"]:
        return "ok"
    chat_id = data["message"]["chat"]["id"]
    text = data["message"]["text"].strip()

    if text == "/start":
        history_data[chat_id] = []
        pred_data[chat_id] = []
        pred_fails[chat_id] = 0
        send_message(chat_id, "دزلي 25 رقم على الاقل - البوت الجديد 6 ارقام")
        return "ok"

    nums = []
    for x in text.replace(",", " ").split():
        if x.lstrip("-").isdigit():
            v = int(x)
            if 0 <= v <= 36:
                nums.append(v)

    if len(nums) == 0:
        return "ok"

    if len(nums) == 1:
        if len(history_data[chat_id]) < 25:
            send_message(chat_id, "بالبداية دزلي 25 رقم")
            return "ok"

        new_num = nums[0]
        history_data[chat_id].append(new_num)
        last_pred = pred_data[chat_id]
        fails = pred_fails[chat_id]

        if new_num in last_pred:
            res = f"✅ ربح! اجه {new_num} من {last_pred}\n"
            # فكرتك: اذا ربح يغير الـ 6 كلها
            pred, gaps = make_prediction(history_data[chat_id])
            pred_data[chat_id] = pred
            pred_fails[chat_id] = 0
            res += f"♻️ اغير الـ 6 كلها\nتوقع جديد: {pred}\n"
            send_message(chat_id, res)
            return "ok"
        else:
            fails += 1
            res = f"❌ خسارة {new_num} مو من {last_pred} | {fails}/10\n"

            if fails >= 10:
                res += f"♻️ 10 خسارات راح اغير الـ 6 كلها\n"
                pred, gaps = make_prediction(history_data[chat_id], exclude=last_pred)
                pred_data[chat_id] = pred
                pred_fails[chat_id] = 0
                res += f"توقع جديد: {pred}\n"
            else:
                pred_fails[chat_id] = fails
                res += f"باقي: {last_pred}\n"

            send_message(chat_id, res)
            return "ok"

    if len(nums) >= 25:
        history_data[chat_id] = nums
        pred, gaps = make_prediction(nums)
        pred_data[chat_id] = pred
        pred_fails[chat_id] = 0
        msg = f"حفظت {len(nums)} رقم\nاخر: {nums[-1]}\nتوقع (2 هوت+4 كولد): {pred}\nهسه دز رقم رقم"
        send_message(chat_id, msg)
        return "ok"

    send_message(chat_id, "دزلي 25 رقم على الاقل")
    return "ok"

@app.route("/", methods=["GET"])
def index():
    return "Bot is running"

if __name__ == "__main__":
    app.run()
