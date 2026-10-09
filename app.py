from flask import Flask, request
import os
import requests

app = Flask(__name__)
TOKEN = os.environ.get("BOT_TOKEN")

history_data = {}
pred_data = {}
pred_fails = {}

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def make_hot_prediction(nums, exclude=None):
    # ناخذ اخر 35 لفة
    last = nums[-35:] if len(nums) >= 35 else nums

    freq = {}
    for n in last:
        freq[n] = freq.get(n, 0) + 1

    # نرتب حسب التكرار
    sorted_hot = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    hot_list = [x[0] for x in sorted_hot]

    # اذا عدنا استبعاد (بعد 10 خسارات) نجيب غيرهم
    pred = []
    if exclude:
        for h in hot_list:
            if h not in exclude and h not in pred:
                pred.append(h)
            if len(pred) >= 8:
                break
        # اذا ما كفى نكمل من الباقي
        if len(pred) < 8:
            for h in hot_list:
                if h not in pred:
                    pred.append(h)
                if len(pred) >= 8:
                    break
    else:
        pred = hot_list[:8]

    # اذا بعدد الارقام قليل نكمل لحد 8 من الارقام الباردة
    if len(pred) < 8:
        gaps = {i: 999 for i in range(37)}
        for idx, val in enumerate(reversed(nums)):
            if gaps[val] == 999:
                gaps[val] = idx
        sorted_cold = sorted(gaps.items(), key=lambda x: x[1], reverse=True)
        for c, g in sorted_cold:
            if c not in pred:
                pred.append(c)
            if len(pred) >= 8:
                break

    return pred[:8]

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
        send_message(chat_id, "البوت الجديد 8 ارقام حارة\nدزلي 35 رقم على الاقل")
        return "ok"

    nums = []
    for x in text.replace(",", " ").split():
        if x.lstrip("-").isdigit():
            v = int(x)
            if 0 <= v <= 36:
                nums.append(v)

    if len(nums) == 0:
        return "ok"

    # لفة وحدة
    if len(nums) == 1:
        if chat_id not in history_data or len(history_data[chat_id]) < 35:
            send_message(chat_id, "بالبداية دزلي 35 رقم")
            return "ok"

        new_num = nums[0]
        history_data[chat_id].append(new_num)
        last_pred = pred_data.get(chat_id, [])
        fails = pred_fails.get(chat_id, 0)

        if new_num in last_pred:
            res = f"✅ ربح! {new_num} من {last_pred}\n"
            pred = make_hot_prediction(history_data[chat_id])
            pred_data[chat_id] = pred
            pred_fails[chat_id] = 0
            res += f"♻️ ابدلهم كلهم (ربح)\nتوقع جديد 8 حارة: {pred}"
            send_message(chat_id, res)
            return "ok"
        else:
            fails += 1
            res = f"❌ {new_num} مو من {last_pred} | {fails}/10\n"
            if fails >= 10:
                pred = make_hot_prediction(history_data[chat_id], exclude=last_pred)
                pred_data[chat_id] = pred
                pred_fails[chat_id] = 0
                res += f"♻️ 10 خسارات ابدلهم كلهم\nتوقع جديد: {pred}"
            else:
                pred_fails[chat_id] = fails
                res += f"باقي: {last_pred}"
            send_message(chat_id, res)
            return "ok"

    # تاريخ كبير
    if len(nums) >= 35:
        history_data[chat_id] = nums
        pred = make_hot_prediction(nums)
        pred_data[chat_id] = pred
        pred_fails[chat_id] = 0
        send_message(chat_id, f"حفظت {len(nums)} رقم\nتوقع 8 حارة: {pred}\nهسه دز رقم رقم")
        return "ok"

    send_message(chat_id, "دزلي 35 رقم على الاقل")
    return "ok"

@app.route("/", methods=["GET"])
def index():
    return "Bot is running 8 HOT"

if __name__ == "__main__":
    app.run()
