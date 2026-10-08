WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]

SHORT_MEMORY = 15
SECTOR_WINDOW = 20
HOT_WINDOW = 50
GAP_LIMIT = 25

def get_sector(last_numbers):
    if len(last_numbers) < SECTOR_WINDOW:
        return "VOISINS", {"VOISINS":0,"TIERS":0,"ORPHELINS":0}
    recent_20 = last_numbers[-SECTOR_WINDOW:]
    counts = {
        "VOISINS": sum(1 for n in recent_20 if n in VOISINS),
        "TIERS": sum(1 for n in recent_20 if n in TIERS),
        "ORPHELINS": sum(1 for n in recent_20 if n in ORPHELINS)
    }
    hot_sector = max(counts, key=counts.get)
    return hot_sector, counts

def get_hot_five(last_numbers):
    from collections import Counter
    if len(last_numbers) < 5:
        return [], {"last_15": last_numbers, "repeaters": []}
    last_50 = last_numbers[-HOT_WINDOW:]
    last_15 = last_numbers[-SHORT_MEMORY:]
    freq = Counter(last_50)
    filtered = {}
    for num, count in freq.items():
        if num == 0:
            continue
        last_pos = -1
        for i in range(len(last_numbers)-1, -1, -1):
            if last_numbers[i] == num:
                last_pos = i
                break
        gap = len(last_numbers) - 1 - last_pos
        if gap <= GAP_LIMIT:
            filtered[num] = count
    freq_15 = Counter(last_15)
    scored = {}
    for num, count in filtered.items():
        bonus = 3 if freq_15[num] >= 2 else 0
        scored[num] = count + bonus
    hot_five = sorted(scored, key=scored.get, reverse=True)[:5]
    trend_info = {
        "last_15": last_15,
        "repeaters": [n for n, c in freq_15.items() if c >= 2]
    }
    return hot_five, trend_info

def predict(last_numbers):
    sector, sector_counts = get_sector(last_numbers)
    hot_five, trend_info = get_hot_five(last_numbers)
    return {
        "sector": sector,
        "play": hot_five,
        "counts": sector_counts,
        "repeaters": trend_info["repeaters"],
        "last_15": trend_info["last_15"]
    }
