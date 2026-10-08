# V21 - ROULETTE PREDICTOR (15 + GAP + REPEATER)
# يبني على V20 بدون تخريب

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]

VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]

SHORT_MEMORY = 15
SECTOR_WINDOW = 20
HOT_WINDOW = 50
GAP_LIMIT = 25

def get_sector(last_numbers):
    recent_20 = last_numbers[-SECTOR_WINDOW:]
    counts = {
        "VOISINS": sum(1 for n in recent_20 if n in VOISINS),
        "TIERS": sum(1 for n in recent_20 if n in TIERS),
        "ORPHELINS": sum(1 for n in recent_20 if n in ORPHELINS)
    }
    hot_sector = max(counts, key=counts.get)
    return hot_sector, counts

def get_hot_five(last_numbers):
    last_50 = last_numbers[-HOT_WINDOW:]
    last_15 = last_numbers[-SHORT_MEMORY:]

    # 1. حساب التكرار
    from collections import Counter
    freq = Counter(last_50)

    # 2. فلتر الفجوة (جديد V21)
    # اذا رقم ما طلع من 25 لفة واكثر، نحذفه
    filtered = {}
    for num, count in freq.items():
        if num == 0:
            continue
        # وين اخر مرة طلع؟
        last_pos = -1
        for i in range(len(last_numbers)-1, -1, -1):
            if last_numbers[i] == num:
                last_pos = i
                break
        gap = len(last_numbers) - 1 - last_pos
        if gap <= GAP_LIMIT:
            filtered[num] = count

    # 3. بونص Repeater (جديد V21)
    freq_15 = Counter(last_15)
    scored = {}
    for num, count in filtered.items():
        bonus = 0
        if freq_15[num] >= 2: # طلع مرتين بآخر 15
            bonus = 3
        scored[num] = count + bonus

    # 4. ترتيب واختيار 5
    hot_five = sorted(scored, key=scored.get, reverse=True)[:5]

    # 5. معلومات اضافية للقرار
    trend_info = {
        "last_15": last_15,
        "repeaters": [n for n,c in freq_15.items() if c >= 2]
    }

    return hot_five, trend_info

def predict(last_numbers):
    sector, sector_counts = get_sector(last_numbers)
    hot_five, trend_info = get_hot_five(last_numbers)

    # نطبق الفكس 4 على الخمسة الحارة
    print(f"SECTOR HOT: {sector} -> {sector_counts}")
    print(f"SHORT 15: {trend_info['last_15']}")
    print(f"REPEATERS in 15: {trend_info['repeaters']}")
    print(f"HOT FIVE (بعد فلتر الفجوة + بونص): {hot_five}")

    return {
        "sector": sector,
        "play": hot_five,
        "repeaters": trend_info['repeaters']
    }

# مثال
# history = [...ارقامك هنا...]
# predict(history)
