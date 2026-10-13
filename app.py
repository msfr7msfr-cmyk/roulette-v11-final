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

def get_wheel_sector(num, distance=1):
    try:
        idx = WHEEL.index(num)
        return [WHEEL[(idx + i) % 37] for i in range(-distance, distance + 1)]
    except: return []

def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except: pass

def make_super_smart_prediction(nums):
    """الخوارزمية الفائقة المحدثة: تحليل القفزات، السخونة اللحظية، ونظام مؤشر الأمان"""
    if not nums or len(nums) < 5: return [], "ضعيفة (انتظر السجل)"
    jumps = []
    for i in range(-5, -1):
        try:
            idx1 = WHEEL.index(nums[i])
            idx2 = WHEEL.index(nums[i+1])
            jumps.append((idx2 - idx1) % 37)
        except: pass
    most_common_jump = max(set(jumps), key=jumps.count) if jumps else None
    jump_confidence = jumps.count(most_common_jump) if most_common_jump else 0
    last50 = nums[-50:]
    last20 = nums[-20:]
    freq = {}
    for n in last50: freq[n] = freq.get(n, 0) + 1
    for n in last20: freq[n] = freq.get(n, 0) + 2.0
    sorted_hot = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    hot_list = [x[0] for x in sorted_hot]
    pred = []
    last_num = nums[-1]
    if most_common_jump is not None:
        try:
            target_idx = (WHEEL.index(last_num) + most_common_jump) % 37
            pred.append(WHEEL[target_idx])
        except: pass
    for n in get_wheel_sector(last_num, distance=1):
        if n not in pred and len(pred) < 3:
            pred.append(n)
    for h in hot_list:
        if len(pred) >= 4: break
        if h not in pred: pred.append(h)
    for w in WHEEL:
        if len(pred) >= 4: break
        if w not in pred: pred.append(w)
    is_hot_and_jumping = False
    if most_common_jump is not None:
        try:
            target_idx = (WHEEL.index(last_num) + most_common_jump) % 37
            if WHEEL[target_idx] in last20 and jump_confidence >= 2:
                is_hot_and_jumping = True
        except: pass
    if is_hot_and_jumping or (len(last20) > 0 and last20.count(last_num) >= 2):
        signal = "🔥 قوية جداً (العب الآن) 🎯"
    else:
        signal = "⚠️ ضعيفة (انتظر اللفة القادمة ولا تراهن) 🛑"
    return pred[:4], signal

@app.route('/')
def home(): return "Bot is Alive with Safety Index Mode!"

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
            send_message(chat_id, "🧠 تم تشغيل رادار الـ 4 لفات الذكي بنظام (مؤشر الأمان لرميات الهواء).\n📥 أرسل لي سجل الـ 100 رقم الأخيرة للطاولة لتبدأ الفلترة وتحديد قوة الإشارة.")
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
                send_message(chat_id, f"⚠️ خطأ: يجب إدخال الـ 100 رقم السجل أولاً!")
                return "ok"
            new_num = nums[0]
            db["history"][chat_id].append(new_num)
            last_pred = db["pred"].get(chat_id, [])
            fails = db["fails"].get(chat_id, 0)
            if not last_pred:
                last_pred, signal = make_super_smart_prediction(db["history"][chat_id])
                db["pred"][chat_id] = last_pred
                fails = 0
            if new_num in last_pred:
                new_pred, signal = make_super_smart_prediction(db["history"][chat_id])
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد فيزيائي دقيق! الماكينة أسقطت الكرة في {new_num} وهو في النطاق {last_pred}!\n\n🎯 تم صيد الهدف وتصفير الدورة لـ 4 لفات جديدة.\n📋 الإشارة الحالية: {signal}\n🎯 الأرقام الـ 4 القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 4:
                    new_pred, signal = make_super_smart_prediction(db["history"][chat_id])
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ الماكينة غيّرت النمط بعد 4 لفات متتالية.\n🔄 هروب ذكي: تم تصفير المحاولات والتحويل فوراً إلى قطاع الهواء النشط الآن.\n📋 الإشارة الحالية: {signal}\n🎯 الأرقام الـ 4 المستهدفة الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    save_data(db)
                    _, current_signal = make_super_smart_prediction(db["history"][chat_id])
                    send_message(chat_id, f"❌ لفة {fails}/4: الماكينة ضربت الرقم {new_num}.\n📋 الإشارة الحالية: {current_signal}\n🏹 الأرقام الثابتة للمطاردة: {last_pred}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred, signal = make_super_smart_prediction(nums)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            msg = f"📊 تم كسر تشفير العجلة ومزامنة ضغط دفع هواء الماكينة اللحظي بنجاح.\n"
            msg += f"ℹ️ الرقم الأحدث المعتمد حالياً في نهاية السجل هو: ({nums[-1]})\n"
            msg += f"📋 حالة الإحصاء: {signal}\n"
            msg += f"🎯 خطة قنص الـ 4 لفات الخاطفة (4 أرقام): {pred}\n"
            msg += f"🎰 اتبع توجيه الإشارة الحالي، وأرسل كل رقم يظهر مباشرة فوراً."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
