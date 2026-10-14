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

def get_2_sector_numbers(num):
    try:
        idx = WHEEL.index(num)
        return [WHEEL[idx], WHEEL[(idx + 1) % 37]]
    except: return []

def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except: pass

def make_triangular_sector_prediction(nums):
    if not nums: return []
    last_num = nums[-1]
    pred = []
    try:
        last_idx = WHEEL.index(last_num)
        for n in get_2_sector_numbers(last_num):
            if n not in pred: pred.append(n)
        idx_one_third = (last_idx + 12) % 37
        num_one_third = WHEEL[idx_one_third]
        for n in get_2_sector_numbers(num_one_third):
            if n not in pred and len(pred) < 4: pred.append(n)
        idx_two_third = (last_idx + 24) % 37
        num_two_third = WHEEL[idx_two_third]
        for n in get_2_sector_numbers(num_two_third):
            if n not in pred and len(pred) < 6: pred.append(n)
    except: pass
    for w in WHEEL:
        if len(pred) >= 6: break
        if w not in pred: pred.append(w)
    return pred[:6]

@app.route('/')
def home(): return "Bot is Alive with Triangular Sector Trap!"

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
            send_message(chat_id, "🔺 تم تشغيل رادار (المثلث الفيزيائي الموزع) المطور كلياً.\n📥 أرسل سجل الـ 100 رقم الأخيرة لنقوم بتقسيم الفخ (2 رقم في 3 اتجاهات متساوية حول العجلة) ونبدأ صيد الـ 5 لفات الخاطف.")
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
                last_pred = make_triangular_sector_prediction(db["history"][chat_id])
                db["pred"][chat_id] = last_pred
                fails = 0
            if new_num in last_pred:
                new_pred = make_triangular_sector_prediction(db["history"][chat_id])
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد ساحق بنظام المثلث الفيزيائي! ضرب الرقم {new_num} داخل أحد النطاقات الثلاثة {last_pred}!\n\n🎯 تم تصفير الدورة وبدء فخ مثلث جديد لـ 5 لفات فقط.\n🎯 الأرقام الـ 6 القوية القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 5:
                    new_pred = make_triangular_sector_prediction(db["history"][chat_id])
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ انتهت الـ 5 لفات السريعة للمطاردة دون ضربة.\n🔄 هروب تكتيكي آمن: تم تحديث فخ المثلث الجغرافي على محاور الطاولة الحالية فوراً.\n🎯 الأرقام الـ 6 المستهدفة الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    save_data(db)
                    send_message(chat_id, f"❌ لفة {fails}/5: الماكينة ضربت الرقم {new_num}.\n🏹 ضغط الهواء يتوزع ميكانيكياً! واصل مطاردة الـ 6 أرقام الثابتة: {last_pred}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred = make_triangular_sector_prediction(nums)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            msg = f"📊 تم نصب فخ المثلث المتقاطع وتوزيع الـ 6 أرقام بالتساوي حول محيط العجلة.\n"
            msg += f"ℹ️ الرقم الأحدث المعتمد حالياً في نهاية السجل هو: ({nums[-1]})\n"
            msg += f"🔺 التقسيم الهيكلي: (2 رقم في قطاع السقوط الحالي + 2 رقم في الثلث الأول + 2 رقم في الثلث الثاني)\n"
            msg += f"🎯 خطة قنص المثلث الخاطفة (6 أرقام): {pred}\n"
            msg += f"🎰 ثبت رهانك الموزع لـ 5 لفات فقط، وأرسل كل رقم يظهر مباشرة فوراً."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
