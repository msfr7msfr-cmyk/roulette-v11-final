from flask import Flask, request
import os
import requests

app = Flask(__name__)
TOKEN = os.environ.get("BOT_TOKEN")

history_data = {}
pred_data = {}
pred_fails = {}

# ترتيب العجلة الاوربية الحقيقي
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]

def get_neighbors(num):
    idx = WHEEL.index(num)
    # جار يمين ويسار
    return [WHEEL[(idx-1)%37], WHEEL[(idx+1)%37]]

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def make_strong_prediction(nums):
    # 1. ناخذ اخر 100 لفة مو 35
    last100 = nums[-100:] if len(nums) >= 100 else nums

    freq = {}
    for n in last100:
        freq[n] = freq.get(n, 0) + 1
    sorted_hot = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    hot_list = [x[0] for x in sorted_hot]

    # 2. رقم تكرر باخر 5 لفات
    last5 = nums[-5:]
    repeat_num = None
    for n in last5:
        if last5.count(n) >= 2:
            repeat_num = n
            break

    pred = []
    # الاول: اكثر رقم حار
    if hot_list:
        pred.append(hot_list[0])
        # الثاني: جاره على العجلة
        for nb in get_neighbors(hot_list[0]):
            if nb not in pred:
                pred.append(nb)
                break
    # الثالث: رقم متكرر اخر 5 لفات
    if repeat_num is not None and repeat_num not in pred:
        pred.append(repeat_num)
    # الرابع: ثاني اكثر رقم حار
    for h in hot_list:
        if h not in pred:
            pred.append(h)
            break

    # اذا بعد اقل من 4 نكمل من الحارة
    for h in hot_list:
        if len(pred) >= 4: break
        if h not in pred:
            pred.append(h)

    return pred[:4]

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
        send_message(chat_id, "البوت القوي 4 ارقام\nدزلي 100 رقم على الاقل")
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
        if chat_id not in history_data or len(history_data[chat_id]) < 100:
            send_message(chat_id, "بالبداية دزلي 100 رقم")
            return "ok"
        new_num = nums[0]
        history_data[chat_id].append(new_num)
        last_pred = pred_data.get(chat_id, [])
        fails = pred_fails.get(chat_id, 0)
        if new_num in last_pred:
            pred = make_strong_prediction(history_data[chat_id])
            pred_data[chat_id] = pred
            pred_fails[chat_id] = 0
            send_message(chat_id, f"✅ ربح! {new_num} من {last_pred}\nتوقع جديد 4 قوي: {pred}")
            return "ok"
        else:
            fails += 1
            res = f"❌ {new_num} مو من {last_pred} | {fails}/10\n"
            if fails >= 10:
                pred = make_strong_prediction(history_data[chat_id])
                pred_data[chat_id] = pred
                pred_fails[chat_id] = 0
                res += f"♻️ 10 خسارات ابدلهم كلهم\nتوقع جديد: {pred}"
            else:
                pred_fails[chat_id] = fails
                res += f"باقي: {last_pred}"
            send_message(chat_id, res)
            return "ok"

    if len(nums) >= 100:
        history_data[chat_id] = nums
        pred = make_strong_prediction(nums)
        pred_data[chat_id] = pred
        pred_fails[chat_id] = 0
        send_message(chat_id, f"حفظت {len(nums)} رقم\nتوقع 4 قوي: {pred}\nهسه دز رقم رقم")
        return "ok"

    send_message(chat_id, "دزلي 100 رقم على الاقل")
    return "ok"

@app.route("/", methods=["GET"])
def index():
    return "Bot is running 4 STRONG"

if __name__ == "__main__":
    app.run()
