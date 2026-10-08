WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]
GAP_LIMIT = 15

def get_neighbors(num):
    i = WHEEL.index(num)
    return [WHEEL[(i-1)%37], WHEEL[(i+1)%37], WHEEL[(i-2)%37], WHEEL[(i+2)%37]]

def get_hot_five(last_numbers):
    from collections import Counter
    f50 = Counter(last_numbers[-50:])
    f8 = Counter(last_numbers[-8:])
    f15 = Counter(last_numbers[-15:])

    scored = {}
    for num in range(37):
        if num not in f50: continue
        # GAP
        last_pos = len(last_numbers)-1 - last_numbers[::-1].index(num)
        gap = len(last_numbers)-1 - last_pos
        base = f50[num]
        if gap > 15:
            if base < 3: continue
            base *= 0.5

        # صفر
        if num == 0 and gap > 20 and last_numbers[-20:].count(0) < 2:
            continue

        score = base + f8[num]*3 + sum(f50.get(x,0) for x in get_neighbors(num))*0.5
        if f15[num] >= 2: score += 3
        if last_numbers[-5:].count(num) >= 2: score += 2
        scored[num] = score

    return sorted(scored, key=scored.get, reverse=True)[:5]
