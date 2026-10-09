from flask import Flask, request
import os
import requests
from collections import defaultdict

app = Flask(__name__)
TOKEN = os.environ.get("BOT_TOKEN")

VOISINS = {22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25}
TIERS = {27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9}

def get_sector(n):
    if n in VOISINS:
        return "Voisins"
    if n in TIERS:
        return "Tiers"
    return "Orphelins"

history_data = defaultdict(list)
pred_data = defaultdict(list)
pred_fails = defaultdict(int) # جديد: عداد الفشل

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def make_prediction(nums, exclude=None):
    gaps = {i: 999 for i in range(37)}
    for idx, val in enumerate(reversed(nums)):
        if gaps[val] == 999:
            gaps[val] = idx
    sorted_gaps = sorted(gaps.items(), key=lambda x: x[1], reverse=True)
    all_sorted = [x[0] for x in sorted_gaps]

    if exclude:
        # فكرتك: اذا 20 خسارة نجيب 5 غيرهم
        pred = [n for n in all_sorted if n not in exclude][:5]
    else:
        pred = all_sorted[:5]

    return pred, gaps

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
        send_message(chat_id, "دزلي 25 رقم على الاقل")
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
            pred, gaps = make_prediction(history_data[chat_id])
            pred_data[chat_id] = pred
            pred_fails[chat_id] = 0
            res += f"اخر: {new_num}\nتوقع جديد: {pred}\n"
            send_message(chat_id, res)
            return "ok"
        else:
            fails += 1
            res = f"❌ خسارة اجه {new_num} مو من {last_pred} | {fails}/20\n"

            if fails >= 20:
                res += f"♻️ صار 20 خسارة بدون ربح راح اغير {last_pred}\n"
                pred, gaps = make_prediction(history_data[chat_id], exclude=last_pred)
                pred_data[chat_id] = pred
                pred_fails[chat_id] = 0
                res += f"اخر: {new_num}\nتوقع جديد: {pred}\n"
            else:
                # يبقى نفس التوقع
                pred_fails[chat_id] = fails
                pred = last_pred
                res += f"اخر: {new_num}\nنفس التوقع باقي: {pred}\n"

            send_message(chat_id, res)
            return "ok"

    if len(nums) >= 25:
        history_data[chat_id] = nums
        pred, gaps = make_prediction(nums)
        pred_data[chat_id] = pred
        pred_fails[chat_id] = 0
        msg = f"حفظت {len(nums)} رقم\nاخر: {nums[-1]}\nتوقع: {pred}\nهسه دز رقم رقم"
        send_message(chat_id, msg)
        return "ok"

    send_message(chat_id, "دزلي 25 رقم على الاقل")
    return "ok"

@app.route("/", methods=["GET"])
def index():
    return "Bot is running"

if __name__ == "__main__":
    app.run()
