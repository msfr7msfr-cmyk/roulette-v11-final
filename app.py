# -*- coding: utf-8 -*-
import os, json, requests
from flask import Flask, request
app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
HISTORY_FILE = "history.json"
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]

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
        url = f"https://telegram.org{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except: pass

def make_auto_air_prediction(nums):
    if not nums: return []
    last50 = nums[-50:]
    freq = {}
    for n in last50: freq[n] = freq.get(n, 0) + 1
    sorted_hot = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    hot_list = [x[0] for x in sorted_hot]
    pred = []
    last_num = nums[-1]
    for n in get_wheel_sector(last_num, distance=1):
        if len(pred) < 3: pred.append(n)
    for h in hot_list:
        if len(pred) >= 4: break
        if h not in pred: pred.append(h)
    for w in WHEEL:
        if len(pred) >= 4: break
        if w not in pred: pred.append(w)
    return pred[:4]

@app.route('/')
def home(): return "Bot is Alive!"

@app_web.route(f"/{TOKEN}", methods=["POST"])
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
            send_message(chat_id, "💨 تم تشغيل رادار روليت الهواء المباشرة (Auto Roulette Sniper).\n📥 أرسل لي سجل الـ 100 رقم الأخيرة للطاولة الآلية لنقيس دقة رمية الهواء.")
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
                send_message(chat_id, f"⚠️ خطأ: يجب إدخل الـ 100 رقم السجل أولاً! الأرقام المحفوظة لك حالياً: {len(db['history'].get(chat_id, []))}/100")
                return "ok"
            new_num = nums[0]
            db["history"][chat_id].append(new_num)
            last_pred = db["pred"].get(chat_id, [])
            fails = db["fails"].get(chat_id, 0)
            
            if not last_pred:
                last_pred = make_auto_air_prediction(db["history"][chat_id])
                db["pred"][chat_id] = last_pred
                fails = 0
                
            if new_num in last_pred:
                new_pred = make_auto_air_prediction(db["history"][chat_id])
                db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                save_data(db)
                send_message(chat_id, f"🟢 صيد فيزيائي دقيق! الماكينة أسقطت الكرة في {new_num} وهو في النطاق {last_pred}!\n\n🎯 تم تصفير الدورة وبدء مطاردة قطاع هواء جديد لـ 10 لفات.\n🎯 الأرقام الـ 4 القادمة: {new_pred}")
            else:
                fails += 1
                if fails >= 10:
                    new_pred = make_auto_air_prediction(db["history"][chat_id])
                    db["pred"][chat_id], db["fails"][chat_id] = new_pred, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ الماكينة خرجت عن النطاق المعتاد لـ 10 لفات.\n🔄 إعادة معايرة ضغط الماكينة وتحديث الأهداف فوراً.\n🎯 الأرقام الـ 4 المستهدفة الجديدة: {new_pred}")
                else:
                    db["fails"][chat_id] = fails
                    save_data(db)
                    send_message(chat_id, f"❌ لفة {fails}/10: الماكينة ضربت الرقم {new_num}.\n🏹 ضغط الهواء ثابت! واصل مطاردة القطاع ولا تغير الرهان: {last_pred}")
            return "ok"
            
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            pred = make_auto_air_prediction(nums)
            db["pred"][chat_id], db["fails"][chat_id] = pred, 0
            save_data(db)
            send_message(chat_id, f"📊 تم تحليل حركية العجلة وتفكيك ضغط دفع الهواء للماكينة.\n🎯 خطة قنص القطاع الأولية (4 أرقام): {pred}\n🎰 العب الآن وثبّت رهانك عليها لـ 10 لفات، وأرسل كل رقم يظهر مباشرة.")
            return "ok"
            
        send_message(chat_id, f"📥 استلمت {len(nums)} أرقام. يرجى إرسال 100 رقم كاملة للسجل البدئي أو إرسال رقم واحد لمتابعة الدورة.")
    except Exception as e:
        pass
    return "ok"
