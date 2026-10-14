# -*- coding: utf-8 -*-
import os, json, requests
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
HISTORY_FILE = "history.json"

WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

def load_data():
    try: return json.load(open(HISTORY_FILE, "r")) if os.path.exists(HISTORY_FILE) else {}
    except: return {}

def save_data(data):
    try: json.dump(data, open(HISTORY_FILE, "w"))
    except: pass

def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except: pass

def make_calibrated_triangular_prediction(nums):
    if not nums: return []
    last50 = nums[-50:]
    last20 = nums[-20:]
    freq = {}
    for n in last50: freq[n] = freq.get(n, 0) + 1
    for n in last20: freq[n] = freq.get(n, 0) + 3.0
    last_num = nums[-1]
    pred = []
    try:
        last_idx = WHEEL.index(last_num)
        pred.append(last_num)
        left_neighbor = WHEEL[(last_idx - 1) % 37]
        right_neighbor = WHEEL[(last_idx + 1) % 37]
        chosen_neighbor = left_neighbor if freq.get(left_neighbor, 0) >= freq.get(right_neighbor, 0) else right_neighbor
        pred.append(chosen_neighbor)
        idx_one_third = (last_idx + 12) % 37
        sector_one = [WHEEL[(idx_one_third - 1) % 37], WHEEL[idx_one_third], WHEEL[(idx_one_third + 1) % 37]]
        sector_one_sorted = sorted(sector_one, key=lambda x: freq.get(x, 0), reverse=True)
        for n in sector_one_sorted:
            if n not in pred and len(pred) < 4:
                pred.append(n)
        idx_two_third = (last_idx + 24) % 37
        sector_two = [WHEEL[(idx_two_third - 1) % 37], WHEEL[idx_two_third], WHEEL[(idx_two_third + 1) % 37]]
        sector_two_sorted = sorted(sector_two, key=lambda x: freq.get(x, 0), reverse=True)
        for n in sector_two_sorted:
            if n not in pred and len(pred) < 6:
                pred.append(n)
    except: pass
    for w in WHEEL:
        if len(pred) >= 6: break
        if w not in pred: pred.append(w)
    return pred[:6]

@app.route('/')
def home(): return "Bot is Alive with Calibrated Triangular Mode!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data or "message" not in data or "text" not in data["message"]: return "ok"
        chat_id = str(data["message"]["chat"]["id"])
        text = data["message"]["text"].strip()
        db = load_data()
        if "history" not in db: db["history"] = {}
        if "pred" not in db: db["pred"] = {}
        if "fails" not in db: db["fails"] = {}
        if text == "/start":
            db["history"][chat_id], db["pred"][chat_id], db["fails"][chat_id] = [], [], 0
            save_data(db)
            send_message(chat_id, "🔺 تم تشغيل رادار (المثلث المعاير ذكياً).\n📥 أرسل لي سجل الـ 100 رقم الأخيرة لضبط عيار الـ 6 أرقام الموزعة بوزن فيزيائي وإحصائي دقيق.")
            return "ok"
        nums = []
        for x in text.replace(",", " ").split():
            if x.lstrip("-").isdigit():
                v = int(x)
                if 0 <= v <= 36: nums.append(v)
        if len(nums) == 0:
            send_message(chat_id, "⚠️ يرجى إرسال أرقام صحيحة فقط من 0 إلى 36.")
            return "ok"
        if len(nums) == 1:
            if chat_id not in db["history"] or len(db["history"][chat_id]) < 100:
                send_message(chat_id, "⚠️ خطأ: يجب إدخال الـ 100 رقم السجل أولاً لمعايرة الماكينة!")
                return "ok"
            new_num = nums[0]
            db["history"][chat_id].append(new_num)
            last_pred = db["pred"].get(chat_id, [])
            fails = db["fails"].get(chat_id, 0)
            if not last_pred:
                last_pred = make_calibrated_triangular_prediction(db["history"][chat_id])
                db["pred"][chat_id] = last_pred
                fails = 0
            if new_num in last_pred:
                new_pred = make_calibrated_triangular_prediction(db["history"][chat_id])
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد ساحق بالعيار الموزون! ضرب الرقم {new_num} داخل النطاقات المثلثية {last_pred}!\n\n🎯 تم قنص الهدف وتصفير المحاولات لـ 5 لفات جديدة بربح صافٍ ممتاز.\n🎯 الأرقام الـ 6 المعايرة القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 5:
                    new_pred = make_calibrated_triangular_prediction(db["history"][chat_id])
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ انتهت الـ 5 لفات دون ضربة.\n🔄 تم إعادة عيار الحصار الميكانيكي فوراً واقتناص الأرقام الأكثر سخونة للرمية الأخيرة.\n🎯 الأرقام الـ 6 المستهدفة الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    save_data(db)
                    send_message(chat_id, f"❌ لفة {fails}/5: الماكينة ضربت الرقم {new_num}.\n🏹 العيار مستقر والنطاق ساخن! واصل مطاردة الـ 6 أرقام الثابتة: {last_pred}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred = make_calibrated_triangular_prediction(nums)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            msg = f"📊 تم نصب فخ المثلث الموزون وضبط عيار الاختيار الإحصائي بنجاح.\n"
            msg += f"ℹ️ الرقم الأحدث المعتمد حالياً في نهاية السجل هو: ({nums[-1]})\n"
            msg += f"🔺 هندسة الاختيار: تم انتخاب أقوى رقمين ساخنين في كل ثلث من العجلة ميكانيكياً.\n"
            msg += f"🎯 خطة القنص المعايرة (6 أرقام): {pred}\n"
            msg += f"🎰 ثبت رهانك لـ 5 لفات كاملة، وأرسل كل رقم يظهر مباشرة فوراً."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
