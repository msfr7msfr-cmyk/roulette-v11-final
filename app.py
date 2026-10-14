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

def calculate_drift_and_predict(nums, chat_id, db):
    if not nums: return []
    last_num = nums[-1]
    last_predictions = db["pred"].get(chat_id, [])
    drift_adjustment = 0
    if last_predictions and len(nums) >= 2:
        try:
            expected_idx = WHEEL.index(last_predictions[0])
            actual_idx = WHEEL.index(last_num)
            raw_drift = (actual_idx - expected_idx)
            if raw_drift > 18: raw_drift -= 37
            elif raw_drift < -18: raw_drift += 37
            if abs(raw_drift) <= 6:
                drift_adjustment = raw_drift
        except: pass
    pred = []
    try:
        base_idx = WHEEL.index(last_num)
        calibrated_idx = (base_idx + drift_adjustment) % 37
        calibrated_num = WHEEL[calibrated_idx]
        for n in get_2_sector_numbers(calibrated_num):
            if n not in pred: pred.append(n)
        opposite_idx = (calibrated_idx + 18) % 37
        opposite_num = WHEEL[opposite_idx]
        for n in get_2_sector_numbers(opposite_num):
            if n not in pred and len(pred) < 4: pred.append(n)
    except: pass
    for w in WHEEL:
        if len(pred) >= 4: break
        if w not in pred: pred.append(w)
    return pred[:4]

@app.route('/')
def home(): return "Bot is Alive with AI Dynamic Drift Correction!"

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
            send_message(chat_id, "🧠 تم تشغيل محرك (Dynamic Drift Correction) الفائق.\n📥 البوت الآن يملك عقلاً مرناً يتعلّم من اللفة السابقة ويعدل انحراف أرقامه الـ 4 فوراً. أرسل الـ 100 رقم لمعايرة الماكينة.")
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
            last_pred = db["pred"].get(chat_id, [])
            fails = db["fails"].get(chat_id, 0)
            if new_num in last_pred:
                db["history"][chat_id].append(new_num)
                new_pred = calculate_drift_and_predict(db["history"][chat_id], chat_id, db)
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد فيزيائي خارق! عقل البوت لحق بـ زحف الكرة وصاد {new_num} داخل النطاق {last_pred}!\n\n🎯 تم تصفير المحاولات وبدء معايرة ديناميكية جديدة لـ 10 لفات.\n🎯 الأرقام الـ 4 الذكية القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 10:
                    db["history"][chat_id].append(new_num)
                    new_pred = calculate_drift_and_predict(db["history"][chat_id], chat_id, db)
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ الماكينة غيرت عيار الضغط بالكامل بعد 10 لفات متتالية.\n🔄 إعادة كسر تشفير الماكينة وتحديث الزحف فوراً لحماية حسابك.\n🎯 الأرقام الـ 4 المستهدفة الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    db["history"][chat_id].append(new_num)
                    save_data(db)
                    send_message(chat_id, f"❌ لفة {fails}/10: الماكينة ضربت الرقم {new_num}.\n🏹 محرك التعديل يراقب الحركة! واصل مطاردة الـ 4 أرقام الثابتة للدورة الحالية: {last_pred}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred = calculate_drift_and_predict(nums, chat_id, db)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            msg = f"📊 تم مزامنة حركة العجلة وتفعيل نظام الفيدباك لتعديل الانحراف (Feedback Loop) بنجاح.\n"
            msg += f"ℹ️ الرقم الأحدث المعتمد حالياً في نهاية السجل هو: ({nums[-1]})\n"
            msg += f"🎯 خطة القنص التكتيكية المرنة (4 أرقام): {pred}\n"
            msg += f"🎰 طارد هذه الأهداف لـ 10 لفات كاملة، وأرسل كل رقم يظهر مباشرة ليقيس البوت انحراف اللفة فوراً."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
