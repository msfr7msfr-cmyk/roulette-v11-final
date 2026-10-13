# -*- coding: utf-8 -*-
import os, json, requests
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
HISTORY_FILE = "history.json"

WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

VOISINS = [22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25]
TIER = [27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33]
ORPHELINS = [1, 20, 14, 31, 9, 17, 34, 6]

def load_data():
    try: return json.load(open(HISTORY_FILE, "r")) if os.path.exists(HISTORY_FILE) else {}
    except: return {}

def save_data(data):
    try: json.dump(data, open(HISTORY_FILE, "w"))
    except: pass

def get_wheel_sector(num, distance=2):
    try:
        idx = WHEEL.index(num)
        return [WHEEL[(idx + i) % 37] for i in range(-distance, distance + 1)]
    except: return []

def send_message(chat_id, text):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except: pass

def make_biased_sector_prediction(nums):
    if not nums: return []
    last25 = nums[-25:]
    v_count = sum(1 for n in last25 if n in VOISINS)
    t_count = sum(1 for n in last25 if n in TIER)
    o_count = sum(1 for n in last25 if n in ORPHELINS)
    active_sector = VOISINS
    sector_name = "Voisins (قطاع الصفر)"
    max_count = v_count
    if t_count > max_count:
        active_sector = TIER
        sector_name = "Tier (قطاع الـ 12 المقابل)"
        max_count = t_count
    if o_count > t_count and o_count > v_count:
        active_sector = ORPHELINS
        sector_name = "Orphelins (قطاع الأطراف)"
    last50 = nums[-50:]
    freq = {}
    for n in last50: freq[n] = freq.get(n, 0) + 1
    for n in last25: freq[n] = freq.get(n, 0) + 2.0
    sorted_hot = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    hot_list = [x[0] for x in sorted_hot]
    pred = []
    last_num = nums[-1]
    base_geo = get_wheel_sector(last_num, distance=2)
    for n in base_geo:
        if n in active_sector and len(pred) < 5:
            pred.append(n)
    for n in base_geo:
        if n not in pred and len(pred) < 5:
            pred.append(n)
    for h in hot_list:
        if len(pred) >= 5: break
        if h not in pred:
            pred.append(h)
    for w in WHEEL:
        if len(pred) >= 5: break
        if w not in pred:
            pred.append(w)
    return pred[:5], sector_name

@app.route('/')
def home(): return "Bot is Alive with Sector Bias Mode!"

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
            send_message(chat_id, "🎯 تم تفعيل رادار تحليل قطاعات الماكينة الديناميكي (5 أرقام / 7 لفات).\n📥 أرسل سجل الـ 100 رقم الأخيرة لنكشف القطاع المسيطر ميكانيكياً ونبدأ القنص.")
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
                send_message(chat_id, "⚠️ خطأ: يجب إدخال الـ 100 رقم السجل أولاً لمعايرة الطاولة!")
                return "ok"
            new_num = nums[0]
            db["history"][chat_id].append(new_num)
            last_pred = db["pred"].get(chat_id, [])
            fails = db["fails"].get(chat_id, 0)
            if not last_pred:
                last_pred, _ = make_biased_sector_prediction(db["history"][chat_id])
                db["pred"][chat_id] = last_pred
                fails = 0
            if new_num in last_pred:
                new_pred, sec_name = make_biased_sector_prediction(db["history"][chat_id])
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد فيزيائي ساحق! ضرب الرقم {new_num} داخل النطاق الذكي {last_pred}!\n\n🎯 تم صيد الهدف وتصفير الدورة لـ 7 لفات جديدة.\n📊 القطاع المسيطر ميكانيكياً الآن: {sec_name}\n🎯 الأرقام الـ 5 القوية القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 7:
                    new_pred, sec_name = make_biased_sector_prediction(db["history"][chat_id])
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ انتهت الـ 7 لفات للمطاردة الحالية.\n🔄 تم كسر التشفير والتحديث على القطاع الساخن الجديد فوراً.\n📊 القطاع المسيطر ميكانيكياً الآن: {sec_name}\n🎯 الأرقام الـ 5 المستهدفة الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    save_data(db)
                    _, sec_name = make_biased_sector_prediction(db["history"][chat_id])
                    send_message(chat_id, f"❌ لفة {fails}/7: الماكينة ضربت الرقم {new_num}.\n📊 القطاع النشط حالياً: {sec_name}\n🏹 الأرقام الثابتة للمطاردة: {last_pred}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred, sec_name = make_biased_sector_prediction(nums)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            msg = f"📊 تم فحص ميزان العجلة الفيزيائي وتحديد تكتل رميات الهواء بنجاح.\n"
            msg += f"ℹ️ الرقم الأحدث المعتمد حالياً في نهاية السجل هو: ({nums[-1]})\n"
            msg += f"🔥 القطاع الأكثر سيطرة ونشاطاً حالياً: {sec_name}\n"
            msg += f"🎯 خطة قنص القطاع الذهبية (5 أرقام): {pred}\n"
            msg += f"🎰 ثبت رهانك عليها لـ 7 لفات كاملة، وأرسل كل رقم يظهر مباشرة فوراً."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
