import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

from aerospace_engine import compute_aerospace_assurance
from industrial_engine import compute_industrial_analysis


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
LATEST_JSON = REPORT_DIR / "latest_analysis.json"
LATEST_MD = REPORT_DIR / "latest_analysis.md"
WINDOWS = [5, 10, 20, 50, 100]
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def taipei_now():
    return datetime.now(TAIPEI_TZ).replace(tzinfo=None)

DEFAULT_MODEL_WEIGHTS = {
    "heat_short": 0.24,
    "heat_mid": 0.2,
    "heat_long": 0.1,
    "omission": 0.13,
    "pair": 0.1,
    "tail_zone": 0.07,
    "repeat_neighbor": 0.05,
    "drag": 0.09,
    "date": 0.03,
    "similar": 0.04,
    "twin": 0.03,
}

ZH = {
    "report_title": "539 \u958b\u734e\u5f8c\u7d71\u8a08\u5206\u6790",
    "generated_at": "\u7522\u751f\u6642\u9593",
    "latest_period": "\u6700\u65b0\u671f\u5225",
    "latest_numbers": "\u6700\u65b0\u865f\u78bc",
    "notice": "\u8aaa\u660e：\u4ee5\u4e0b\u70ba\u6b77\u53f2\u7d71\u8a08\u8a55\u5206，\u4e0d\u4ee3\u8868\u4fdd\u8b49\u958b\u51fa\u6216\u6295\u6ce8\u5efa\u8b70。",
    "failure_review": "\u5931\u6557\u6aa2\u8a0e",
    "model_backtest": "\u6a21\u578b\u56de\u6e2c",
    "card_relations": "\u724c\u578b\u95dc\u806f",
    "strong_packs": "\u5f37\u724c\u7d44",
    "candidates_top15": "\u4e0b\u4e00\u671f\u5019\u9078\u865f\u78bc Top 15",
    "reference_sets": "\u53c3\u8003\u7d44\u5408",
    "strategy_performance": "\u7b56\u7565\u8868\u73fe",
    "window_summary": "\u5340\u9593\u6458\u8981",
}


def fetch_draws(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT period, draw_date, n1, n2, n3, n4, n5
            FROM draws_539
            ORDER BY period
            """
        ).fetchall()
    return [
        {
            "period": row["period"],
            "draw_date": row["draw_date"],
            "numbers": [row["n1"], row["n2"], row["n3"], row["n4"], row["n5"]],
        }
        for row in rows
    ]


def odd_even(numbers):
    odd = sum(1 for n in numbers if n % 2)
    return {"odd": odd, "even": len(numbers) - odd}


def big_small(numbers):
    small = sum(1 for n in numbers if n <= 19)
    return {"small": small, "big": len(numbers) - small}


def zones(numbers):
    counts = dict.fromkeys(["01-10", "11-20", "21-30", "31-39"], 0)
    for n in numbers:
        if n <= 10:
            counts["01-10"] += 1
        elif n <= 20:
            counts["11-20"] += 1
        elif n <= 30:
            counts["21-30"] += 1
        else:
            counts["31-39"] += 1
    return counts


def draw_features(numbers):
    ordered = sorted(numbers)
    return {
        "sum": sum(numbers),
        "odd_even": odd_even(numbers),
        "big_small": big_small(numbers),
        "zones": zones(numbers),
        "tails": Counter(n % 10 for n in numbers),
        "span": max(numbers) - min(numbers),
        "consecutive_pairs": sum(1 for a, b in zip(ordered, ordered[1:]) if b - a == 1),
    }


def frequency(draws):
    counter = Counter()
    for draw in draws:
        counter.update(draw["numbers"])
    return counter


def pair_frequency(draws):
    counter = Counter()
    for draw in draws:
        for pair in combinations(sorted(draw["numbers"]), 2):
            counter[pair] += 1
    return counter


def omission(draws):
    last_seen = {n: None for n in range(1, 40)}
    for idx, draw in enumerate(draws):
        for n in draw["numbers"]:
            last_seen[n] = idx
    last_index = len(draws) - 1
    return {n: (last_index - last_seen[n] if last_seen[n] is not None else len(draws)) for n in range(1, 40)}


def normalize_map(values):
    lo = min(values.values())
    hi = max(values.values())
    if hi == lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def rank_values(values):
    return sorted(range(1, 40), key=lambda n: (values.get(n, 0), -n), reverse=True)


def normalize_number(value):
    value = abs(int(value))
    if value == 0:
        return 39
    return ((value - 1) % 39) + 1


def next_draw_date(draw_date):
    current = datetime.strptime(draw_date, "%Y-%m-%d").date()
    candidate = current + timedelta(days=1)
    while candidate.weekday() == 6:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def date_card_numbers(date_text):
    date_value = datetime.strptime(date_text, "%Y-%m-%d")
    roc_year = date_value.year - 1911
    raw_values = [
        roc_year,
        date_value.month,
        date_value.day,
        int(f"{date_value.month}{date_value.day:02d}"),
        sum(int(ch) for ch in date_value.strftime("%Y%m%d")),
        roc_year + date_value.month,
        roc_year + date_value.day,
        date_value.month + date_value.day,
    ]
    numbers = []
    for value in raw_values:
        n = normalize_number(value)
        if n not in numbers:
            numbers.append(n)
    return numbers[:8]


def reverse_number(number):
    text = f"{number:02d}"
    reversed_number = int(text[::-1])
    if 1 <= reversed_number <= 39 and reversed_number != number:
        return reversed_number
    return None


def relationship_analysis(draws):
    latest = draws[-1]
    latest_numbers = latest["numbers"]
    latest_set = set(latest_numbers)
    next_date = next_draw_date(latest["draw_date"])

    drag_counter = Counter()
    drag_by_source = defaultdict(Counter)
    for idx in range(len(draws) - 1):
        current_numbers = set(draws[idx]["numbers"])
        next_numbers = draws[idx + 1]["numbers"]
        for source in latest_set & current_numbers:
            drag_counter.update(next_numbers)
            drag_by_source[source].update(next_numbers)
    drag_scores = normalize_map({n: drag_counter.get(n, 0) for n in range(1, 40)})

    date_candidates = date_card_numbers(next_date)
    date_counter = Counter()
    for draw in draws[-720:]:
        derived = set(date_card_numbers(draw["draw_date"]))
        date_counter.update(set(draw["numbers"]) & derived)
    date_scores = {n: 0.0 for n in range(1, 40)}
    for n in date_candidates:
        date_scores[n] = 0.7 + min(date_counter.get(n, 0) / 10, 0.3)

    tail_counts = Counter()
    for draw in draws[-50:]:
        tail_counts.update(n % 10 for n in draw["numbers"])
    tail_scores = normalize_map({tail: tail_counts.get(tail, 0) for tail in range(10)})
    tail_number_scores = {n: tail_scores[n % 10] for n in range(1, 40)}

    similar_sources = defaultdict(list)
    similar_scores = {n: 0.0 for n in range(1, 40)}
    for source in latest_numbers:
        for candidate in (source - 1, source + 1, reverse_number(source)):
            if candidate and 1 <= candidate <= 39:
                similar_scores[candidate] += 1
                similar_sources[candidate].append(source)
    similar_scores = normalize_map(similar_scores)

    twin_sources = defaultdict(list)
    twin_scores = {n: 0.0 for n in range(1, 40)}
    for source in latest_numbers:
        tail = source % 10
        for candidate in range(1, 40):
            if candidate != source and candidate % 10 == tail and abs(candidate - source) == 10:
                twin_scores[candidate] += 1
                twin_sources[candidate].append(source)
    twin_scores = normalize_map(twin_scores)

    return {
        "next_draw_date": next_date,
        "drag": {
            "top": [{"number": n, "count": drag_counter.get(n, 0)} for n in rank_values(drag_scores)[:12]],
            "by_latest_number": {
                f"{source:02d}": [{"number": n, "count": c} for n, c in drag_by_source[source].most_common(8)]
                for source in latest_numbers
            },
            "scores": drag_scores,
        },
        "date": {
            "date": next_date,
            "candidates": date_candidates,
            "scores": date_scores,
        },
        "tail": {
            "top_tails": [{"tail": tail, "count": count} for tail, count in tail_counts.most_common(5)],
            "scores": tail_number_scores,
        },
        "similar": {
            "top": [{"number": n, "sources": sorted(set(similar_sources[n]))} for n in rank_values(similar_scores)[:12] if similar_scores[n] > 0],
            "scores": similar_scores,
        },
        "twin": {
            "top": [{"number": n, "sources": sorted(set(twin_sources[n]))} for n in rank_values(twin_scores)[:12] if twin_scores[n] > 0],
            "scores": twin_scores,
        },
    }


def window_summary(draws, size):
    subset = draws[-size:]
    freq = frequency(subset)
    sums = [sum(draw["numbers"]) for draw in subset]
    oe = Counter()
    bs = Counter()
    zc = Counter()
    tail = Counter()
    consecutive_total = 0
    repeat_total = 0

    previous = None
    for draw in subset:
        features = draw_features(draw["numbers"])
        oe[f"{features['odd_even']['odd']}:{features['odd_even']['even']}"] += 1
        bs[f"{features['big_small']['small']}:{features['big_small']['big']}"] += 1
        zc.update(features["zones"])
        tail.update(features["tails"])
        consecutive_total += features["consecutive_pairs"]
        if previous:
            repeat_total += len(set(previous) & set(draw["numbers"]))
        previous = draw["numbers"]

    expected = size * 5 / 39
    return {
        "size": size,
        "period_range": [subset[0]["period"], subset[-1]["period"]],
        "date_range": [subset[0]["draw_date"], subset[-1]["draw_date"]],
        "hot": [{"number": n, "count": c, "delta_vs_expected": round(c - expected, 2)} for n, c in freq.most_common(10)],
        "cold": [{"number": n, "count": freq.get(n, 0), "delta_vs_expected": round(freq.get(n, 0) - expected, 2)} for n in sorted(range(1, 40), key=lambda x: (freq.get(x, 0), x))[:10]],
        "sum_avg": round(sum(sums) / len(sums), 2),
        "sum_min": min(sums),
        "sum_max": max(sums),
        "odd_even_top": oe.most_common(3),
        "big_small_top": bs.most_common(3),
        "zone_avg": {k: round(v / size, 2) for k, v in zc.items()},
        "tail_hot": [{"tail": k, "count": v} for k, v in tail.most_common(5)],
        "avg_consecutive_pairs": round(consecutive_total / size, 2),
        "avg_repeat_from_previous": round(repeat_total / max(size - 1, 1), 2),
    }


def component_scores(draws):
    latest = draws[-1]
    latest_set = set(latest["numbers"])
    all_omission = omission(draws)
    reasons = defaultdict(list)

    components = {
        "heat_short": {n: 0.0 for n in range(1, 40)},
        "heat_mid": {n: 0.0 for n in range(1, 40)},
        "heat_long": {n: 0.0 for n in range(1, 40)},
        "omission": normalize_map(all_omission),
        "pair": {n: 0.0 for n in range(1, 40)},
        "tail_zone": {n: 0.0 for n in range(1, 40)},
        "repeat_neighbor": {n: 0.0 for n in range(1, 40)},
        "drag": {n: 0.0 for n in range(1, 40)},
        "date": {n: 0.0 for n in range(1, 40)},
        "similar": {n: 0.0 for n in range(1, 40)},
        "twin": {n: 0.0 for n in range(1, 40)},
    }

    heat_windows = {
        "heat_short": [(5, 0.55), (10, 0.45)],
        "heat_mid": [(20, 0.6), (50, 0.4)],
        "heat_long": [(100, 1.0)],
    }
    for component, config in heat_windows.items():
        raw = defaultdict(float)
        for size, share in config:
            subset = draws[-size:]
            freq = frequency(subset)
            expected = size * 5 / 39
            for n in range(1, 40):
                raw[n] += share * ((freq.get(n, 0) - expected) / max(expected, 1))
                if freq.get(n, 0) >= math.ceil(expected + 1):
                    reasons[n].append(f"\u8fd1{size}\u671f\u504f\u71b1({freq.get(n, 0)}\u6b21)")
        components[component] = normalize_map(raw)

    for n in range(1, 40):
        if all_omission[n] >= 10:
            reasons[n].append(f"\u907a\u6f0f{all_omission[n]}\u671f")

    pair_counter = pair_frequency(draws[-100:])
    pair_score = defaultdict(int)
    for n in range(1, 40):
        if n in latest_set:
            continue
        for last_n in latest_set:
            pair_score[n] += pair_counter.get(tuple(sorted((n, last_n))), 0)
    components["pair"] = normalize_map({n: pair_score[n] for n in range(1, 40)})
    for n in range(1, 40):
        if pair_score[n] >= 4:
            reasons[n].append(f"\u8207\u4e0a\u671f\u865f\u78bc\u8fd1100\u671f\u5171\u73fe{pair_score[n]}\u6b21")

    recent_tail = Counter()
    recent_zone = Counter()
    for draw in draws[-20:]:
        recent_tail.update(n % 10 for n in draw["numbers"])
        recent_zone.update(zones(draw["numbers"]))
    tail_norm = normalize_map({t: recent_tail.get(t, 0) for t in range(10)})
    zone_norm = normalize_map({k: recent_zone.get(k, 0) for k in ["01-10", "11-20", "21-30", "31-39"]})
    for n in range(1, 40):
        if n <= 10:
            zone_label = "01-10"
        elif n <= 20:
            zone_label = "11-20"
        elif n <= 30:
            zone_label = "21-30"
        else:
            zone_label = "31-39"
        components["tail_zone"][n] = (tail_norm[n % 10] + zone_norm[zone_label]) / 2

        repeat_neighbor = 0.0
        if n in latest_set:
            repeat_neighbor += 0.45
            reasons[n].append("\u4e0a\u671f\u91cd\u865f\u89c0\u5bdf")
        if any(abs(n - last_n) == 1 for last_n in latest_set):
            repeat_neighbor += 0.55
            reasons[n].append("\u4e0a\u671f\u9130\u865f\u89c0\u5bdf")
        components["repeat_neighbor"][n] = repeat_neighbor

    relations = relationship_analysis(draws)
    for n in range(1, 40):
        components["drag"][n] = relations["drag"]["scores"].get(n, 0)
        components["date"][n] = relations["date"]["scores"].get(n, 0)
        components["similar"][n] = relations["similar"]["scores"].get(n, 0)
        components["twin"][n] = relations["twin"]["scores"].get(n, 0)
        if components["drag"][n] >= 0.75:
            reasons[n].append("\u62d6\u724c\u95dc\u806f\u504f\u5f37")
        if components["date"][n] > 0:
            reasons[n].append(f"\u65e5\u671f\u724c({relations['date']['date']})")
        if components["similar"][n] > 0:
            reasons[n].append("\u76f8\u4f3c\u724c")
        if components["twin"][n] > 0:
            reasons[n].append("\u96d9\u751f\u724c")

    return components, all_omission, reasons


def score_numbers(draws, model_weights=None, failure_review_data=None):
    weights = model_weights or DEFAULT_MODEL_WEIGHTS
    components, all_omission, reasons = component_scores(draws)
    score = defaultdict(float)
    total_weight = sum(weights.values()) or 1

    for name, values in components.items():
        weight = weights.get(name, 0) / total_weight
        for n in range(1, 40):
            score[n] += weight * values.get(n, 0)

    long_freq = frequency(draws[-100:])
    long_norm = normalize_map({n: long_freq.get(n, 0) for n in range(1, 40)})
    for n in range(1, 40):
        score[n] = score[n] * 0.92 + long_norm[n] * 0.08

    if failure_review_data and failure_review_data.get("severity") == "critical":
        settled = failure_review_data.get("last_settled", {})
        failed_numbers = set((settled.get("candidate_numbers") or [])[:10])
        for pack in (settled.get("strong_pack_hits") or {}).values():
            if not pack.get("passed"):
                failed_numbers.update(pack.get("numbers", []))
        actual_numbers = set(settled.get("actual_numbers") or [])
        failed_numbers -= actual_numbers
        for n in failed_numbers:
            if 1 <= n <= 39:
                score[n] *= 0.35
                reasons[n].append("\u4e0a\u671f\u5931\u6557\u61f2\u7f70")

    ranked = rank_values(score)
    max_score = max(score.values())
    min_score = min(score.values())
    candidates = []
    for n in ranked:
        confidence = 50 if max_score == min_score else 50 + (score[n] - min_score) / (max_score - min_score) * 49
        candidates.append(
            {
                "number": n,
                "score": round(score[n], 4),
                "confidence_index": round(confidence, 1),
                "omission": all_omission[n],
                "reasons": reasons[n][:4],
            }
        )
    return candidates


def strategy_rankings(draws, model_weights=None):
    weights = model_weights or DEFAULT_MODEL_WEIGHTS
    components, _, _ = component_scores(draws)
    ensemble = {n: 0.0 for n in range(1, 40)}
    total_weight = sum(weights.values()) or 1
    for name, values in components.items():
        for n in range(1, 40):
            ensemble[n] += (weights.get(name, 0) / total_weight) * values.get(n, 0)
    rankings = {name: rank_values(values) for name, values in components.items()}
    rankings["ensemble"] = rank_values(ensemble)
    return rankings


def backtest(draws, rounds=360, top_sizes=(5, 10, 15)):
    if len(draws) < 130:
        return {"rounds": 0, "strategies": {}, "note": "\u8cc7\u6599\u4e0d\u8db3，\u7565\u904e\u56de\u6e2c。"}

    start = max(100, len(draws) - rounds - 1)
    strategy_stats = defaultdict(lambda: {f"top{size}_hits": 0 for size in top_sizes} | {"rounds": 0})

    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        rankings = strategy_rankings(train)
        for strategy, ranking in rankings.items():
            strategy_stats[strategy]["rounds"] += 1
            for size in top_sizes:
                strategy_stats[strategy][f"top{size}_hits"] += len(set(ranking[:size]) & actual)

    random_expectation = {size: round(5 * size / 39, 3) for size in top_sizes}
    result = {}
    for strategy, stats in strategy_stats.items():
        strategy_rounds = stats["rounds"]
        result[strategy] = {"rounds": strategy_rounds}
        for size in top_sizes:
            avg = stats[f"top{size}_hits"] / strategy_rounds
            result[strategy][f"top{size}_avg_hits"] = round(avg, 3)
            result[strategy][f"top{size}_edge_vs_random"] = round(avg - random_expectation[size], 3)

    return {
        "rounds": next(iter(strategy_stats.values()))["rounds"],
        "random_expectation": random_expectation,
        "strategies": result,
    }


def calibrated_weights(backtest_result):
    strategies = backtest_result.get("strategies", {})
    weights = {}
    for name in DEFAULT_MODEL_WEIGHTS:
        stats = strategies.get(name, {})
        edge = stats.get("top10_edge_vs_random", 0)
        weights[name] = DEFAULT_MODEL_WEIGHTS[name] * (1 + max(min(edge, 0.35), -0.25))
    total = sum(weights.values()) or 1
    return {name: round(value / total, 4) for name, value in weights.items()}


def latest_settled_prediction(db_path=DB_PATH):
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT based_on_period, target_period, actual_period, actual_date,
                       actual_numbers_json, candidates_json, strong_pack_hits_json,
                       top5_hits, top10_hits, top15_hits
                FROM predictions_539
                WHERE status='settled'
                ORDER BY actual_period DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return {
        "based_on_period": row[0],
        "target_period": row[1],
        "actual_period": row[2],
        "actual_date": row[3],
        "actual_numbers": json.loads(row[4] or "[]"),
        "candidate_numbers": [item["number"] for item in json.loads(row[5] or "[]")],
        "strong_pack_hits": json.loads(row[6] or "{}"),
        "top5_hits": row[7],
        "top10_hits": row[8],
        "top15_hits": row[9],
    }


def failure_review(db_path=DB_PATH):
    settled = latest_settled_prediction(db_path)
    if not settled:
        return {"has_review": False, "severity": "none", "actions": []}
    severity = "normal"
    actions = []
    if settled["top10_hits"] == 0:
        severity = "critical"
        actions = [
            "\u964d\u4f4e\u77ed\u7dda\u71b1\u865f、\u62d6\u724c、\u76f8\u4f3c\u724c\u8207\u96d9\u751f\u724c\u6b0a\u91cd",
            "\u63d0\u9ad8\u4e2d\u671f\u5747\u8861、\u907a\u6f0f\u88dc\u511f、\u5c3e\u6578\u5340\u9593\u8207\u5171\u73fe\u5206\u6563",
            "\u5f37\u724c\u7d44\u52a0\u5165\u5340\u9593\u5206\u6563\u9650\u5236，\u907f\u514d\u96c6\u4e2d\u5728\u540c\u4e00\u6bb5\u8da8\u52e2",
        ]
    elif settled["top10_hits"] <= 1:
        severity = "warning"
        actions = [
            "\u5c0f\u5e45\u964d\u4f4e\u77ed\u7dda\u8ffd\u71b1\u6b0a\u91cd",
            "\u63d0\u9ad8\u4e2d\u671f\u8207\u5340\u9593\u5206\u6563\u6bd4\u91cd",
        ]
    return {
        "has_review": True,
        "severity": severity,
        "actions": actions,
        "last_settled": settled,
    }


def apply_failure_adjustment(weights, review):
    adjusted = dict(weights)
    if not review.get("has_review"):
        return adjusted
    if review.get("severity") == "critical":
        multipliers = {
            "heat_short": 0.72,
            "drag": 0.65,
            "date": 0.75,
            "similar": 0.7,
            "twin": 0.7,
            "heat_mid": 1.18,
            "omission": 1.25,
            "pair": 1.14,
            "tail_zone": 1.2,
            "repeat_neighbor": 0.85,
            "heat_long": 1.05,
        }
    elif review.get("severity") == "warning":
        multipliers = {
            "heat_short": 0.9,
            "drag": 0.92,
            "similar": 0.92,
            "heat_mid": 1.08,
            "tail_zone": 1.08,
            "omission": 1.08,
        }
    else:
        multipliers = {}
    for name, multiplier in multipliers.items():
        adjusted[name] = adjusted.get(name, 0) * multiplier
    total = sum(adjusted.values()) or 1
    return {name: round(value / total, 4) for name, value in adjusted.items()}


def build_sets(candidates):
    top = [item["number"] for item in candidates[:18]]
    overdue = [item["number"] for item in sorted(candidates, key=lambda x: (x["omission"], x["score"]), reverse=True)[:10]]
    sets = [
        sorted([top[0], top[2], top[5], top[8], top[11]]),
        sorted([top[1], top[3], top[6], overdue[0], overdue[2]]),
        sorted([top[0], top[4], top[7], top[10], overdue[1]]),
        sorted([top[2], top[5], top[9], overdue[3], overdue[4]]),
        sorted([top[0], top[6], top[12], top[15], top[17]]),
    ]
    unique_sets = []
    seen = set()
    for s in sets:
        key = tuple(s)
        if key not in seen and len(s) == 5:
            unique_sets.append(s)
            seen.add(key)
    return unique_sets


def diversity_penalty(selected, candidate):
    if not selected:
        return 0
    penalty = 0
    candidate_tail = candidate % 10
    if any(n % 10 == candidate_tail for n in selected):
        penalty += 0.025
    if any(abs(n - candidate) == 1 for n in selected):
        penalty += 0.015
    if sum(1 for n in selected if zone_label(n) == zone_label(candidate)) >= 2:
        penalty += 0.02
    return penalty


def zone_label(number):
    if number <= 10:
        return "01-10"
    if number <= 20:
        return "11-20"
    if number <= 30:
        return "21-30"
    return "31-39"


def optimized_group(candidates, size):
    score_by_number = {item["number"]: item["score"] for item in candidates}
    selected = []
    pool = [item["number"] for item in candidates[:24]]
    while len(selected) < size and pool:
        best = max(pool, key=lambda n: score_by_number[n] - diversity_penalty(selected, n))
        selected.append(best)
        pool.remove(best)
    return sorted(selected)


def build_strong_prediction_packs(candidates):
    score_by_number = {item["number"]: item["score"] for item in candidates}
    single = [candidates[0]["number"]]
    two = optimized_group(candidates, 2)
    three = optimized_group(candidates, 3)
    five = optimized_group(candidates, 5)
    nine = optimized_group(candidates, 9)

    def pack(name, hit_goal, numbers):
        return {
            "name": name,
            "hit_goal": hit_goal,
            "numbers": numbers,
            "score_sum": round(sum(score_by_number[n] for n in numbers), 4),
            "avg_score": round(sum(score_by_number[n] for n in numbers) / len(numbers), 4),
            "zones": Counter(zone_label(n) for n in numbers),
            "tails": Counter(n % 10 for n in numbers),
        }

    return {
        "strong_single": pack("\u6700\u5f37\u55ae\u652f", 1, single),
        "two_hit_one": pack("\u6700\u5f372\u4e2d1", 1, two),
        "three_hit_one": pack("\u6700\u5f373\u4e2d1", 1, three),
        "five_hit_two": pack("\u6700\u5f375\u4e2d2", 2, five),
        "nine_hit_three": pack("\u6700\u5f379\u4e2d3", 3, nine),
    }


def render_markdown(analysis):
    lines = []
    latest = analysis["latest_draw"]
    lines.append("# 539 \u958b\u734e\u5f8c\u7d71\u8a08\u5206\u6790")
    lines.append("")
    lines.append(f"- \u7522\u751f\u6642\u9593：{analysis['generated_at']}")
    lines.append(f"- \u6700\u65b0\u671f\u5225：{latest['period']} ({latest['draw_date']})")
    lines.append("- \u6700\u65b0\u865f\u78bc：" + " ".join(f"{n:02d}" for n in latest["numbers"]))
    lines.append("- \u8aaa\u660e：\u4ee5\u4e0b\u70ba\u6b77\u53f2\u7d71\u8a08\u8a55\u5206，\u4e0d\u4ee3\u8868\u4fdd\u8b49\u958b\u51fa\u6216\u6295\u6ce8\u5efa\u8b70。")
    lines.append("")

    review = analysis.get("failure_review", {})
    if review.get("has_review"):
        settled = review["last_settled"]
        lines.append("## \u5931\u6557\u6aa2\u8a0e")
        lines.append(f"- \u4e0a\u6b21\u9810\u6e2c\u671f\u5225：{settled['based_on_period']} -> {settled['actual_period']}")
        lines.append("- \u5be6\u969b\u865f\u78bc：" + " ".join(f"{n:02d}" for n in settled["actual_numbers"]))
        lines.append(f"- Top5 / Top10 / Top15 \u547d\u4e2d：{settled['top5_hits']} / {settled['top10_hits']} / {settled['top15_hits']}")
        if review.get("severity") == "critical":
            lines.append("- \u5224\u5b9a：\u91cd\u5927\u5931\u6557，\u6628\u65e5\u5f37\u724c\u7d44\u8207 Top10 \u5e7e\u4e4e\u5b8c\u5168\u504f\u96e2\u5be6\u969b\u5340\u9593。")
        elif review.get("severity") == "warning":
            lines.append("- \u5224\u5b9a：\u547d\u4e2d\u504f\u4f4e，\u9700\u8981\u964d\u4f4e\u77ed\u7dda\u8ffd\u71b1。")
        else:
            lines.append("- \u5224\u5b9a：\u547d\u4e2d\u5728\u53ef\u63a5\u53d7\u89c0\u5bdf\u7bc4\u570d。")
        for action in review.get("actions", []):
            lines.append(f"- \u6539\u5584：{action}")
        lines.append("")

    lines.append("## \u6a21\u578b\u56de\u6e2c")
    bt = analysis["backtest"]
    industrial = analysis.get("industrial_engine", {})
    lines.append(f"- \u56de\u6e2c\u671f\u6578：{bt.get('rounds', 0)}")
    lines.append(f"- \u96a8\u6a5f Top10 \u671f\u671b\u547d\u4e2d：\u7d04 {bt.get('random_expectation', {}).get(10, 0)} \u9846")
    ensemble = bt.get("strategies", {}).get("ensemble", {})
    if ensemble:
        lines.append(f"- \u7d9c\u5408\u6a21\u578b Top10 \u5e73\u5747\u547d\u4e2d：{ensemble.get('top10_avg_hits')} \u9846，\u5c0d\u96a8\u6a5f\u5dee\u503c {ensemble.get('top10_edge_vs_random')}")
    if industrial:
        ibt = industrial.get("backtest", {})
        lines.append(f"- \u5de5\u696d\u5f15\u64ce：{industrial.get('engine_version')}，\u9632\u8cc7\u6599\u6d29\u6f0f：{industrial.get('leakage_guard')}")
        lines.append(f"- \u5de5\u696d\u5f15\u64ce Top10 \u5e73\u5747\u547d\u4e2d：{ibt.get('top10_avg_hits')}，Top15：{ibt.get('top15_avg_hits')}")
    lines.append("- \u6821\u6b63\u5f8c\u6b0a\u91cd：" + ", ".join(f"{k}={v}" for k, v in analysis["model_weights"].items()))
    lines.append("")

    lines.append("## \u724c\u578b\u95dc\u806f")
    relation = analysis["relationships"]
    drag = " ".join(f"{item['number']:02d}({item['count']})" for item in relation["drag"]["top"][:10])
    date_cards = " ".join(f"{n:02d}" for n in relation["date"]["candidates"])
    tail_cards = " ".join(f"{item['tail']}\u5c3e({item['count']})" for item in relation["tail"]["top_tails"])
    similar_cards = " ".join(f"{item['number']:02d}" for item in relation["similar"]["top"][:10])
    twin_cards = " ".join(f"{item['number']:02d}" for item in relation["twin"]["top"][:10])
    lines.append(f"- \u62d6\u724c：{drag}")
    lines.append(f"- \u65e5\u671f\u724c ({relation['date']['date']})：{date_cards}")
    lines.append(f"- \u5c3e\u6578\u724c：{tail_cards}")
    lines.append(f"- \u76f8\u4f3c\u724c：{similar_cards or '\u7121'}")
    lines.append(f"- \u96d9\u751f\u724c：{twin_cards or '\u7121'}")
    lines.append("")

    lines.append("## \u5f37\u724c\u7d44")
    pack_labels = [
        ("strong_single", "\u6700\u5f37\u55ae\u652f"),
        ("two_hit_one", "\u6700\u5f372\u4e2d1"),
        ("three_hit_one", "\u6700\u5f373\u4e2d1"),
        ("five_hit_two", "\u6700\u5f375\u4e2d2"),
        ("nine_hit_three", "\u6700\u5f379\u4e2d3"),
    ]
    for key, label in pack_labels:
        pack = analysis["strong_prediction_packs"][key]
        nums = " ".join(f"{n:02d}" for n in pack["numbers"])
        lines.append(f"- {label}：{nums}，\u5e73\u5747\u5206 {pack['avg_score']}")
        if key == "nine_hit_three" and pack.get("wheel_tickets"):
            coverage = pack.get("wheel_coverage", {})
            lines.append(f"- 9\u4e2d3\u8f2a\u7d44\u8986\u84cb：{coverage.get('covered')}/{coverage.get('total')}，\u8986\u84cb\u7387 {coverage.get('rate')}")
            for idx, ticket in enumerate(pack["wheel_tickets"], 1):
                lines.append(f"  {idx}. " + " ".join(f"{n:02d}" for n in ticket))
    lines.append("")

    lines.append("## \u4e0b\u4e00\u671f\u5019\u9078\u865f\u78bc Top 15")
    lines.append("")
    lines.append("| \u6392\u540d | \u865f\u78bc | \u8a55\u5206 | \u6307\u6578 | \u907a\u6f0f | \u4e3b\u8981\u7406\u7531 |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    for idx, item in enumerate(analysis["candidates"][:15], 1):
        reason = "、".join(item["reasons"]) if item["reasons"] else "\u7d9c\u5408\u5206\u6578\u9760\u524d"
        lines.append(
            f"| {idx} | {item['number']:02d} | {item['score']:.4f} | "
            f"{item['confidence_index']:.1f} | {item['omission']} | {reason} |"
        )
    lines.append("")
    lines.append("## \u53c3\u8003\u7d44\u5408")
    lines.append("")
    for idx, combo in enumerate(analysis["suggested_sets"], 1):
        lines.append(f"{idx}. " + " ".join(f"{n:02d}" for n in combo))

    lines.append("")
    lines.append("## \u7b56\u7565\u8868\u73fe")
    lines.append("")
    lines.append("| \u7b56\u7565 | Top5 | Top10 | Top15 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for name, stats in sorted(bt.get("strategies", {}).items()):
        lines.append(
            f"| {name} | {stats.get('top5_avg_hits', 0)} | "
            f"{stats.get('top10_avg_hits', 0)} | {stats.get('top15_avg_hits', 0)} |"
        )

    lines.append("")
    lines.append("## \u5340\u9593\u6458\u8981")
    for summary in analysis["windows"]:
        lines.append("")
        lines.append(f"### \u8fd1 {summary['size']} \u671f")
        hot = " ".join(f"{x['number']:02d}({x['count']})" for x in summary["hot"][:8])
        cold = " ".join(f"{x['number']:02d}({x['count']})" for x in summary["cold"][:8])
        lines.append(f"- \u71b1\u865f：{hot}")
        lines.append(f"- \u51b7\u865f：{cold}")
        lines.append(f"- \u548c\u503c：\u5e73\u5747 {summary['sum_avg']}，\u7bc4\u570d {summary['sum_min']} - {summary['sum_max']}")
        lines.append(f"- \u5947\u5076\u5e38\u898b：{summary['odd_even_top']}")
        lines.append(f"- \u5927\u5c0f\u5e38\u898b：{summary['big_small_top']}")
        lines.append(f"- \u5e73\u5747\u9023\u865f\u7d44\u6578：{summary['avg_consecutive_pairs']}")
        lines.append(f"- \u5e73\u5747\u8207\u524d\u4e00\u671f\u91cd\u865f\u6578：{summary['avg_repeat_from_previous']}")
    lines.append("")
    return "\n".join(lines)


def analyze(db_path=DB_PATH):
    draws = fetch_draws(db_path)
    if len(draws) < 100:
        raise RuntimeError("\u8cc7\u6599\u4e0d\u8db3，\u81f3\u5c11\u9700\u8981 100 \u671f\u624d\u80fd\u7522\u751f\u5b8c\u6574\u5206\u6790。")

    bt = backtest(draws)
    review = failure_review(db_path)
    weights = apply_failure_adjustment(calibrated_weights(bt), review)
    industrial = compute_industrial_analysis(draws, review)
    aerospace = compute_aerospace_assurance(draws, industrial)
    if aerospace["release_assurance"]["status"] == "blocked":
        industrial.setdefault("release_gate", {})["status"] = "aerospace_blocked"
    elif aerospace["release_assurance"]["status"] == "watch_only":
        industrial.setdefault("release_gate", {})["aerospace_status"] = "watch_only"
    analysis = {
        "generated_at": taipei_now().isoformat(timespec="seconds"),
        "latest_draw": draws[-1],
        "windows": [window_summary(draws, size) for size in WINDOWS],
        "relationships": relationship_analysis(draws),
        "failure_review": review,
        "industrial_engine": industrial,
        "aerospace_assurance": aerospace,
        "backtest": bt,
        "model_weights": weights,
        "candidates": industrial["candidates"],
    }
    analysis["suggested_sets"] = build_sets(analysis["candidates"])
    analysis["strong_prediction_packs"] = industrial["strong_prediction_packs"]
    return analysis


def save_analysis(analysis):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_MD.write_text(render_markdown(analysis), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="\u4eca\u5f69539\u958b\u734e\u5f8c\u7d71\u8a08\u5206\u6790")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    analysis = analyze(Path(args.db))
    save_analysis(analysis)
    print(f"\u5df2\u7522\u751f\u5206\u6790\u5831\u544a：{LATEST_MD}")
    print("\u5019\u9078 Top 10：" + " ".join(f"{x['number']:02d}" for x in analysis["candidates"][:10]))
    print("\u53c3\u8003\u7d44\u5408 1：" + " ".join(f"{n:02d}" for n in analysis["suggested_sets"][0]))


if __name__ == "__main__":
    main()
