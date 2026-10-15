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

def make_isolated_session_prediction(nums):
    if not nums: return []
    last_num = nums[-1]
    pred = []
    recent_nums = nums[-20:]
    for i in range(len(recent_nums) - 1):
        if recent_nums[i] == last_num:
            next_num = recent_nums[i + 1]
            if next_num not in pred:
                pred.append(next_num)
    freq = {}
    for n in recent_nums: freq[n] = freq.get(n, 0) + 1
    sorted_hot = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    for h in sorted_hot:
        if len(pred) >= 5: break
        if h[0] not in pred:
            pred.append(h[0])
    for i in range(len(nums) - 1):
        if len(pred) >= 5: break
        if nums[i] == last_num and nums[i+1] not in pred:
            pred.append(nums[i+1])
    for w in WHEEL:
        if len(pred) >= 5: break
        if w not in pred: pred.append(w)
    return pred[:5]

@app.route('/')
def home(): return "Bot is Alive with 20-History / 5-Spins Calibrated Mode!"

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
            send_message(chat_id, "🧠 تم تفعيل نظام (الذاكرة الـ 20 / المطاردة الـ 5 الثابتة).\n🧹 تم تنظيف السيرفر تماماً.\n📥 أرسل سجل الـ 100 رقم لجلسة اليوم الحالي فقط لنربط عيار الأشرطة المكررة ونبدأ الصيد الحتمي.")
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
                send_message(chat_id, "⚠️ خطأ: يرجى إرسال الـ 100 رقم البدئية الخاصة بجلسة اليوم أولاً!")
                return "ok"
            new_num = nums[0]
            last_pred = db["pred"].get(chat_id, [])
            fails = db["fails"].get(chat_id, 0)
            if new_num in last_pred:
                db["history"][chat_id].append(new_num)
                new_pred = make_isolated_session_prediction(db["history"][chat_id])
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد تاريخي بالعيار الجديد! البوت اقتنص النمط وصاد {new_num} داخل النطاق {last_pred}!\n\n🎯 تم تصفير المحاولات وبدء دورة قنص جديدة لـ 5 لفات ثابتة كلياً.\n🎯 الأرقام الـ 5 القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 5:
                    db["history"][chat_id].append(new_num)
                    new_pred = make_isolated_session_prediction(db["history"][chat_id])
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ انتهت الـ 5 لفات الثابتة دون ضربة.\n🔄 تحديث العيار: تم تغيير المحاولات وقنص السلسلة الموازية الجديدة بناءً على آخر 20 لفة حية.\n🎯 الأرقام الـ 5 الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    db["history"][chat_id].append(new_num)
                    save_data(db)
                    send_message(chat_id, f"❌ لفة {fails}/5: ظهر الرقم {new_num}.\n🏹 الذاكرة الـ 20 مستقرة! واصل مطاردة الـ 5 أرقام الثابتة دون تغيير: {last_pred}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred = make_isolated_session_prediction(nums)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            msg = f"📊 تم ربط عقل البوت بالنمط الموزون (آخر 20 لفة تاريخية / مطاردة 5 لفات).\n"
            msg += f"ℹ️ الرقم الأحدث المعتمد حالياً في نهاية السجل هو: ({nums[-1]})\n"
            msg += f"🎯 خطة قنص السلسلة المتوازية المعايرة (5 أرقام ثابتة): {pred}\n"
            msg += f"🎰 طارد هذه الأهداف لـ 5 لفات كاملة، وأرسل كل رقم يظهر مباشرة فوراً."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
