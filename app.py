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
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except: pass

def make_sequence_loop_prediction(nums):
    if not nums or len(nums) < 5: return []
    last_num = nums[-1]
    pred = []
    for i in range(len(nums) - 1):
        if nums[i] == last_num:
            next_num = nums[i + 1]
            if next_num not in pred:
                pred.append(next_num)
    last25 = nums[-25:]
    freq = {}
    for n in last25: freq[n] = freq.get(n, 0) + 1
    sorted_hot = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    for h in sorted_hot:
        if len(pred) >= 5: break
        if h[0] not in pred:
            pred.append(h[0])
    for w in WHEEL:
        if len(pred) >= 5: break
        if w not in pred: pred.append(w)
    return pred[:5]

@app.route('/')
def home(): return "Bot is Alive with Sequence Loop Sniper Mode!"

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
            send_message(chat_id, "🧠 تم تشغيل العقل الخارق (Historical Sequence Sniper).\n📥 هذا البوت مبرمج على قنص الأشرطة المكررة والسلاسل المتوازية لطاولتك الحالية. أرسل السجل كاملاً لنبدأ.")
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
                send_message(chat_id, "⚠️ خطأ: يجب إدخال السجل البدئي أولاً لمعايرة ذاكرة الطاولة!")
                return "ok"
            new_num = nums[0]
            last_pred = db["pred"].get(chat_id, [])
            fails = db["fails"].get(chat_id, 0)
            if new_num in last_pred:
                db["history"][chat_id].append(new_num)
                new_pred = make_sequence_loop_prediction(db["history"][chat_id])
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد تاريخي ساحق! الماكينة نفذت نظريتك المتوازية وصادت الرقم {new_num} داخل الشريط {last_pred}!\n\n🎯 تم تصفير الدورة وبدء قنص شريط جديد لـ 6 لفات ثابتة.\n🎯 الأرقام الـ 5 المستهدفة القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 6:
                    db["history"][chat_id].append(new_num)
                    new_pred = make_sequence_loop_prediction(db["history"][chat_id])
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ انتهت الـ 6 لفات الثابتة للمطاردة.\n🔄 قفزة ميكانيكية: تم تحديث الأهداف وقنص السلسلة الموازية للرمية الأخيرة فوراً.\n🎯 الأرقام الـ 5 الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    db["history"][chat_id].append(new_num)
                    save_data(db)
                    send_message(chat_id, f"❌ لفة {fails}/6: ظهر الرقم {new_num}.\n🏹 الشريط مستقر والدورة مستمرة! ثبت رهانك ولا تغير الـ 5 أرقام القوية الحالية: {last_pred}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred = make_sequence_loop_prediction(nums)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            msg = f"📊 تم تفكيك شفرة ذاكرة الجدول الحركي ومزامنة الأشرطة المكررة للماكينة بنجاح.\n"
            msg += f"ℹ️ الرقم الأحدث المعتمد حالياً في نهاية السجل هو: ({nums[-1]})\n"
            msg += f"🎯 خطة قنص السلسلة المتوازية (5 أرقام ثابتة): {pred}\n"
            msg += f"🎰 طارد هذه الأهداف لـ 6 لفات كاملة، وأرسل كل رقم يظهر مباشرة فوراً."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
