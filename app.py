import collections

# خريطة الجيران اوروبي
NEIGHBORS = {
    0:[32,26], 32:[0,15], 15:[32,19], 19:[15,4], 4:[19,21], 21:[4,2], 2:[21,25],
    25:[2,17], 17:[25,34], 34:[17,6], 6:[34,27], 27:[6,13], 13:[27,36], 36:[13,11],
    11:[36,30], 30:[11,8], 8:[30,23], 23:[8,10], 10:[23,5], 5:[10,24], 24:[5,16],
    16:[24,33], 33:[16,1], 1:[33,20], 20:[1,14], 14:[20,31], 31:[14,9], 9:[31,22],
    22:[9,18], 18:[22,29], 29:[18,7], 7:[29,28], 28:[7,12], 12:[28,35], 35:[12,3],
    3:[35,26], 26:[3,0]
}

VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]

def analyze(history):
    if len(history) < 20:
        return "انتظر 20 لفة"

    last_15 = history[-15:]
    last_50 = history[-50:]

    f15 = collections.Counter(last_15)

    # حساب Gap
    gap = {}
    for n in range(37):
        try:
            gap[n] = list(reversed(history)).index(n)
        except:
            gap[n] = 99

    # حساب 50 مع فلتر Gap 10 + وزن زمني
    score50 = {}
    for n in range(37):
        if gap[n] >= 10: # فلتر الموت الي طلبته
            continue

        count = 0
        # وزن زمني
        last10 = history[-10:]
        last25 = history[-25:]

        c10 = last10.count(n)
        c25 = last25.count(n) - c10
        c50 = last_50.count(n) - (c10+c25)

        count = (c10 * 3) + (c25 * 1) + (c50 * 0.2)

        # بونص repeater مخفف
        if f15[n] >= 2:
            count += 1.5
        if f15[n] >= 3:
            count += 1.0

        if count > 0:
            score50[n] = count

    # ترتيب الحارة
    hot5 = sorted(score50.items(), key=lambda x: x[1], reverse=True)[:5]

    # الاساسي - اعلى 5 سكور
    basic = [n for n,_ in hot5]

    # مع الجيران - فلتر الجيران الميت
    with_neighbors = []
    for num in basic[:3]: # نرشح جيران اقوى 3 بس
        if gap[num] < 10: # اذا الاساسي حي
            with_neighbors.append(num)
            for nb in NEIGHBORS.get(num, [])[:1]: # جار واحد بس مو اثنين
                if gap[nb] < 10:
                    with_neighbors.append(nb)
        if len(with_neighbors) >= 5:
            break

    with_neighbors = with_neighbors[:5]

    # نقطة دخول
    strong = sum(1 for _,s in hot5 if s >= 2.0)
    if strong < 2:
        entry = "⚠️ انتظار - ماكو فرصة قوية"
    else:
        entry = "✅ العب ثابت 4 لفات"

    # قطاع
    last20 = history[-20:]
    v = sum(1 for x in last20 if x in VOISINS)
    t = sum(1 for x in last20 if x in TIERS)
    o = sum(1 for x in last20 if x in ORPHELINS)

    sector = f"Voisins({v}/20)" if v>=t and v>=o else f"Tiers({t}/20)" if t>=o else f"Orphelins({o}/20)"

    # طباعة مثل بوتك
    hot_str = ", ".join([f"{n}({last_50.count(n)}x)" for n,_ in hot5])
    print(f"🧠 V22 - 15+Gap10+TimeWeight")
    print(f"📍 اخر: {history[-1]} | قطاع: {sector}")
    print(f"🔥 5 الحارة (50 لفة): {hot_str}")
    print(f"💰 الاساسي: {basic}")
    print(f"💰 مع الجيران: {with_neighbors}")
    print(f"{entry} | اخر 10: {history[-10:]}")

    return basic, with_neighbors

# مثال تشغيل على سجلك
history = [14, 0, 27, 18, 14, 32, 8, 9, 2, 20, 11, 15, 5, 24, 26, 9, 17, 32, 24, 5, 20, 9, 21, 9, 8, 16, 31, 29, 5, 24, 25, 31, 11, 10, 19, 34, 30, 0, 1, 3, 13, 35, 28, 23, 14, 16, 25, 6, 32, 18, 2, 32, 35, 7, 30, 27, 26, 8, 16, 16, 32, 6, 1, 20, 2, 21, 7, 11, 36, 31, 0, 27, 8, 28, 20, 27, 5, 14, 32]
analyze(history)
