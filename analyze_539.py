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
from industrial_engine import (
    MODEL_SOURCE_LABELS,
    compute_industrial_analysis,
    score_numbers as industrial_score_numbers,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
LATEST_JSON = REPORT_DIR / "latest_analysis.json"
LATEST_MD = REPORT_DIR / "latest_analysis.md"
MONTHLY_REVIEW_JSON = REPORT_DIR / "monthly_prediction_review.json"
WINDOWS = [5, 10, 20, 50, 100]
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def taipei_now():
    return datetime.now(TAIPEI_TZ).replace(tzinfo=None)


def expected_latest_draw_date(now=None):
    now = now or taipei_now()
    candidate = now.date()
    if now.time().hour < 21:
        candidate -= timedelta(days=1)
    while candidate.weekday() == 6:
        candidate -= timedelta(days=1)
    return candidate.isoformat()


def build_data_freshness(latest_date, now=None):
    now = now or taipei_now()
    expected = expected_latest_draw_date(now)
    latest = datetime.strptime(latest_date, "%Y-%m-%d").date()
    expected_date = datetime.strptime(expected, "%Y-%m-%d").date()
    return {
        "status": "fresh" if latest >= expected_date else "stale",
        "latest_date": latest_date,
        "expected_latest_date": expected,
        "lag_days": max((expected_date - latest).days, 0),
        "checked_at": now.isoformat(timespec="seconds"),
    }

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
        rolling = failure_review_data.get("rolling_adjustment", {})
        monthly_recall_numbers = {
            int(item.get("number"))
            for item in rolling.get("monthly_recall_numbers", [])
            if item.get("number")
        }
        daily_recall_numbers = {
            int(item.get("number"))
            for item in rolling.get("missed_actual_numbers", [])
            if item.get("number")
        }
        failed_numbers = set((settled.get("candidate_numbers") or [])[:10])
        for pack in (settled.get("strong_pack_hits") or {}).values():
            if not pack.get("passed"):
                failed_numbers.update(pack.get("numbers", []))
        actual_numbers = set(settled.get("actual_numbers") or [])
        failed_numbers -= actual_numbers
        for n in failed_numbers:
            if 1 <= n <= 39:
                if n in monthly_recall_numbers or n in daily_recall_numbers:
                    score[n] *= 0.78
                    reasons[n].append("\u6708\u5ea6\u6f0f\u6293\u56de\u88dc")
                else:
                    score[n] *= 0.48
                    reasons[n].append("\u4e0a\u671f\u5931\u6557\u8edf\u61f2\u7f70")

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


def backtest(draws, rounds=240, top_sizes=(5, 10, 15)):
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


def number_zone_label(number):
    if number <= 10:
        return "01-10"
    if number <= 20:
        return "11-20"
    if number <= 30:
        return "21-30"
    return "31-39"


def rank_bucket(rank):
    if rank is None:
        return "missing"
    if rank <= 5:
        return "01-05"
    if rank <= 10:
        return "06-10"
    if rank <= 15:
        return "11-15"
    if rank <= 25:
        return "16-25"
    return "26-39"


def month_prediction_review(db_path=DB_PATH, month=None):
    now = taipei_now()
    month = month or now.strftime("%Y-%m")
    start = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT based_on_period,based_on_date,target_period,actual_period,actual_date,
                       actual_numbers_json,candidates_json,strong_pack_hits_json,
                       top5_hits,top10_hits,top15_hits
                FROM predictions_539
                WHERE status='settled' AND actual_date >= ? AND actual_date < ?
                ORDER BY actual_date
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    if not rows:
        return {
            "month": month,
            "sample_size": 0,
            "status": "no_settled_predictions",
            "diagnosis": "\u672c\u6708\u5c1a\u7121\u5df2\u7d50\u7b97\u9810\u6e2c\uff0c\u7121\u6cd5\u505a\u6708\u5ea6\u6821\u6b63\u3002",
            "daily_reviews": [],
            "adjustment_plan": [],
        }

    top5_values = []
    top10_values = []
    top15_values = []
    rank_buckets = Counter()
    missed_top10_numbers = Counter()
    missed_top15_numbers = Counter()
    missed_tails = Counter()
    missed_zones = Counter()
    source_hits = Counter()
    source_misses = Counter()
    pack_stats = defaultdict(lambda: {"rounds": 0, "passes": 0, "hits": 0, "zero_hits": 0})
    daily_reviews = []

    for row in rows:
        candidates = json.loads(row[6] or "[]")
        candidate_numbers = [int(item.get("number")) for item in candidates if item.get("number")]
        actual_numbers = [int(number) for number in json.loads(row[5] or "[]")]
        actual_set = set(actual_numbers)
        ranks = {
            number: (candidate_numbers.index(number) + 1 if number in candidate_numbers else None)
            for number in actual_numbers
        }
        for number, rank in ranks.items():
            rank_buckets[rank_bucket(rank)] += 1
        top10_set = set(candidate_numbers[:10])
        top15_set = set(candidate_numbers[:15])
        for number in actual_set - top10_set:
            missed_top10_numbers[number] += 1
            missed_tails[number % 10] += 1
            missed_zones[number_zone_label(number)] += 1
        for number in actual_set - top15_set:
            missed_top15_numbers[number] += 1

        for item in candidates[:15]:
            number = int(item.get("number"))
            hit = number in actual_set
            for reason in item.get("reasons") or ["\u7d9c\u5408\u6a21\u578b"]:
                if hit:
                    source_hits[reason] += 1
                else:
                    source_misses[reason] += 1

        pack_hits = json.loads(row[7] or "{}")
        for key, item in pack_hits.items():
            pack_stats[key]["rounds"] += 1
            pack_stats[key]["passes"] += 1 if item.get("passed") else 0
            hits = int(item.get("hits", 0) or 0)
            pack_stats[key]["hits"] += hits
            pack_stats[key]["zero_hits"] += 1 if hits == 0 else 0

        top5_values.append(int(row[8] or 0))
        top10_values.append(int(row[9] or 0))
        top15_values.append(int(row[10] or 0))
        daily_reviews.append({
            "actual_date": row[4],
            "target_period": row[2],
            "actual_numbers": actual_numbers,
            "top5_hits": int(row[8] or 0),
            "top10_hits": int(row[9] or 0),
            "top15_hits": int(row[10] or 0),
            "actual_ranks": ranks,
            "missed_top10": sorted(actual_set - top10_set),
            "missed_top15": sorted(actual_set - top15_set),
        })

    sample_size = len(rows)
    avg_top5 = round(sum(top5_values) / sample_size, 3)
    avg_top10 = round(sum(top10_values) / sample_size, 3)
    avg_top15 = round(sum(top15_values) / sample_size, 3)
    rank_total = sum(rank_buckets.values()) or 1
    front_hit_rate = round((rank_buckets["01-05"] + rank_buckets["06-10"]) / rank_total, 3)
    late_or_missing_rate = round(
        (rank_buckets["16-25"] + rank_buckets["26-39"] + rank_buckets["missing"]) / rank_total,
        3,
    )
    if avg_top10 < 1.5 or late_or_missing_rate >= 0.55:
        status = "critical_recall_gap"
        diagnosis = "\u672c\u6708\u4e3b\u8981\u554f\u984c\u662f\u53ec\u56de\u7387\u4e0d\u8db3\uff1a\u5be6\u958b\u865f\u5927\u91cf\u843d\u5728 Top15 \u5f8c\u6bb5\u6216\u5019\u9078\u5916\uff0c\u5fc5\u9808\u512a\u5148\u4fee\u6b63\u6392\u5e8f\u56de\u62c9\u8207\u5305\u7d44\u5408\u8986\u84cb\u3002"
    elif avg_top10 < 1.8:
        status = "warning_rank_gap"
        diagnosis = "\u672c\u6708 Top10 \u547d\u4e2d\u504f\u4f4e\uff0c\u9700\u8981\u63d0\u9ad8\u5f8c\u6bb5\u547d\u4e2d\u865f\u56de\u62c9\u8207\u5206\u5340\u8986\u84cb\u3002"
    else:
        status = "stable_watch"
        diagnosis = "\u672c\u6708 Top10 \u547d\u4e2d\u63a5\u8fd1\u53ef\u89c0\u5bdf\u5340\u9593\uff0c\u6301\u7e8c\u7528\u6708\u5ea6\u8cc7\u6599\u5fae\u8abf\u3002"

    source_rows = []
    for reason in set(source_hits) | set(source_misses):
        hit = source_hits[reason]
        miss = source_misses[reason]
        total = hit + miss
        source_rows.append({
            "reason": reason,
            "hit": hit,
            "miss": miss,
            "hit_rate": round(hit / total, 3) if total else 0,
        })
    source_rows.sort(key=lambda item: (item["hit_rate"], item["hit"], -item["miss"]), reverse=True)

    pack_summary = {}
    for key, item in pack_stats.items():
        rounds = item["rounds"] or 1
        pack_summary[key] = {
            "rounds": item["rounds"],
            "pass_rate": round(item["passes"] / rounds, 3),
            "avg_hits": round(item["hits"] / rounds, 3),
            "zero_hit_rate": round(item["zero_hits"] / rounds, 3),
        }

    adjustment_plan = [
        "\u6708\u5ea6\u6a21\u5f0f\uff1a\u4ee5\u672c\u6708\u6f0f\u6293\u5be6\u958b\u865f\u3001\u5c3e\u6578\u3001\u5340\u9593\u512a\u5148\u505a\u6392\u5e8f\u56de\u62c9\uff0c\u4e0d\u518d\u53ea\u4f9d\u4e0a\u4e00\u671f\u7d50\u679c\u8df3\u52d5\u3002",
        "Top10 \u56de\u62c9\uff1a\u672c\u6708\u91cd\u8907\u6f0f\u6293\u7684\u865f\u78bc\u82e5\u540c\u6642\u5177\u5099\u5206\u5340/\u5c3e\u6578/\u5171\u73fe\u6216\u547d\u4e2d\u7a7f\u900f\u7387\u652f\u6490\uff0c\u5141\u8a31\u9032\u5165 Top10 \u908a\u754c\u5019\u9078\u3002",
        "5\u4e2d2/9\u4e2d3\uff1a\u964d\u4f4e\u524d\u6bb5\u6392\u540d\u55ae\u4e00\u8def\u5f91\u4f9d\u8cf4\uff0c\u6539\u7528\u5206\u5340\u8986\u84cb\u8207\u5c3e\u6578\u5206\u6563\u88dc\u8db3\u3002",
        "\u932f\u6bba\u63a7\u5236\uff1a\u4e0a\u671f\u5931\u6557\u865f\u4e0d\u518d\u786c\u6bba\uff0c\u53ea\u6709\u9023\u7e8c\u843d\u7a7a\u4e14\u7121\u6708\u5ea6\u56de\u88dc\u8a0a\u865f\u624d\u91cd\u964d\u6b0a\u3002",
    ]

    return {
        "month": month,
        "sample_size": sample_size,
        "status": status,
        "diagnosis": diagnosis,
        "top5_avg_hits": avg_top5,
        "top10_avg_hits": avg_top10,
        "top15_avg_hits": avg_top15,
        "front_hit_rate": front_hit_rate,
        "late_or_missing_rate": late_or_missing_rate,
        "rank_buckets": dict(rank_buckets),
        "daily_reviews": daily_reviews,
        "missed_top10_numbers": [{"number": n, "missed_count": c} for n, c in missed_top10_numbers.most_common(15)],
        "missed_top15_numbers": [{"number": n, "missed_count": c} for n, c in missed_top15_numbers.most_common(15)],
        "missed_tails": [{"tail": n, "missed_count": c} for n, c in missed_tails.most_common(10)],
        "missed_zones": [{"zone": n, "missed_count": c} for n, c in missed_zones.most_common()],
        "source_performance": source_rows[:12],
        "pack_summary": pack_summary,
        "best_days": sorted(daily_reviews, key=lambda item: (item["top10_hits"], item["top15_hits"]), reverse=True)[:5],
        "worst_days": sorted(daily_reviews, key=lambda item: (item["top10_hits"], item["top15_hits"]))[:5],
        "adjustment_plan": adjustment_plan,
    }


def rolling_failure_profile(db_path=DB_PATH, limit=30):
    monthly_review = month_prediction_review(db_path)
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT candidates_json, actual_numbers_json, top5_hits, top10_hits, top15_hits
                FROM predictions_539
                WHERE status='settled'
                ORDER BY actual_period DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {
            "sample_size": 0,
            "monthly_review": monthly_review,
            "penalized_reasons": [],
            "boosted_reasons": [],
            "repeated_failed_numbers": [],
            "late_hit_numbers": [],
            "missed_actual_numbers": [],
            "monthly_recall_numbers": monthly_review.get("missed_top10_numbers", []),
            "monthly_recall_tails": monthly_review.get("missed_tails", []),
            "monthly_recall_zones": monthly_review.get("missed_zones", []),
            "recent_performance": {},
        }

    reason_stats = defaultdict(lambda: {"hit": 0, "miss": 0})
    number_misses = Counter()
    missed_actual_numbers = Counter()
    missed_actual_tails = Counter()
    missed_actual_zones = Counter()
    late_hit_reasons = Counter()
    late_hit_numbers = Counter()
    top5_values = []
    top10_values = []
    top15_values = []
    for candidates_json, actual_json, top5_hits, top10_hits, top15_hits in rows:
        candidates = json.loads(candidates_json or "[]")
        actual = set(json.loads(actual_json or "[]"))
        top10_numbers = {int(item.get("number")) for item in candidates[:10] if item.get("number")}
        for number in actual - top10_numbers:
            missed_actual_numbers[number] += 1
            missed_actual_tails[number % 10] += 1
            if number <= 10:
                zone = "01-10"
            elif number <= 20:
                zone = "11-20"
            elif number <= 30:
                zone = "21-30"
            else:
                zone = "31-39"
            missed_actual_zones[zone] += 1
        if top5_hits is not None:
            top5_values.append(int(top5_hits))
        if top10_hits is not None:
            top10_values.append(int(top10_hits))
        if top15_hits is not None:
            top15_values.append(int(top15_hits))
        for rank, item in enumerate(candidates[:15], 1):
            number = int(item.get("number"))
            hit = number in actual
            reasons = item.get("reasons") or ["\u7d9c\u5408\u6a21\u578b"]
            if not hit:
                number_misses[number] += 1
            for reason in reasons:
                reason_stats[reason]["hit" if hit else "miss"] += 1
                if hit and 11 <= rank <= 15:
                    late_hit_reasons[reason] += 1
                    late_hit_numbers[number] += 1

    penalized = []
    boosted = []
    for reason, stats in reason_stats.items():
        total = stats["hit"] + stats["miss"]
        hit_rate = stats["hit"] / total if total else 0
        if stats["miss"] >= 5 and hit_rate <= 0.18:
            penalized.append({"reason": reason, "hit": stats["hit"], "miss": stats["miss"], "hit_rate": round(hit_rate, 3)})
        if late_hit_reasons.get(reason, 0) >= 2 or (stats["hit"] >= 2 and hit_rate >= 0.45):
            boosted.append({"reason": reason, "hit": stats["hit"], "miss": stats["miss"], "late_hit_count": late_hit_reasons.get(reason, 0), "hit_rate": round(hit_rate, 3)})

    def avg(values, size):
        sample = values[:size]
        return round(sum(sample) / len(sample), 3) if sample else 0

    recent_performance = {
        "last3_top5_avg": avg(top5_values, 3),
        "last3_top10_avg": avg(top10_values, 3),
        "last3_top15_avg": avg(top15_values, 3),
        "last5_top5_avg": avg(top5_values, 5),
        "last5_top10_avg": avg(top10_values, 5),
        "last5_top15_avg": avg(top15_values, 5),
        "last10_top5_avg": avg(top5_values, 10),
        "last10_top10_avg": avg(top10_values, 10),
        "last10_top15_avg": avg(top15_values, 10),
        "recent_slump": bool(len(top10_values) >= 5 and (avg(top10_values, 5) < 1.6 or avg(top5_values, 5) < 0.8)),
        "critical_slump": bool(len(top10_values) >= 3 and (avg(top10_values, 3) < 1.4 or avg(top15_values, 3) < 1.8)),
    }

    return {
        "sample_size": len(rows),
        "policy": "daily_and_monthly_miss_review_rolls_into_next_prediction_with_recall_mode",
        "monthly_review": monthly_review,
        "penalized_reasons": sorted(penalized, key=lambda item: (item["miss"], -item["hit"]), reverse=True)[:12],
        "boosted_reasons": sorted(boosted, key=lambda item: (item.get("late_hit_count", 0), item["hit"]), reverse=True)[:12],
        "repeated_failed_numbers": [{"number": n, "miss_count": c} for n, c in number_misses.most_common() if c >= 3][:12],
        "late_hit_numbers": [{"number": n, "late_hit_count": c} for n, c in late_hit_numbers.most_common()][:12],
        "missed_actual_numbers": [{"number": n, "missed_count": c} for n, c in missed_actual_numbers.most_common()][:15],
        "missed_actual_tails": [{"tail": n, "missed_count": c} for n, c in missed_actual_tails.most_common()][:10],
        "missed_actual_zones": [{"zone": n, "missed_count": c} for n, c in missed_actual_zones.most_common()],
        "monthly_recall_numbers": monthly_review.get("missed_top10_numbers", [])[:15],
        "monthly_recall_tails": monthly_review.get("missed_tails", [])[:10],
        "monthly_recall_zones": monthly_review.get("missed_zones", []),
        "recent_performance": recent_performance,
    }


def failure_review(db_path=DB_PATH):
    settled = latest_settled_prediction(db_path)
    if not settled:
        return {"has_review": False, "severity": "none", "actions": []}
    rolling_adjustment = rolling_failure_profile(db_path)
    monthly_review = rolling_adjustment.get("monthly_review", {})
    severity = "normal"
    actions = []
    recent_performance = rolling_adjustment.get("recent_performance", {})
    monthly_critical = monthly_review.get("status") == "critical_recall_gap"
    if settled["top10_hits"] == 0 or recent_performance.get("critical_slump") or monthly_critical:
        severity = "critical"
        actions = [
            "\u964d\u4f4e\u77ed\u7dda\u71b1\u865f\u3001\u62d6\u724c\u3001\u76f8\u4f3c\u724c\u8207\u96d9\u751f\u724c\u6b0a\u91cd",
            "\u63d0\u9ad8\u4e2d\u671f\u5747\u8861\u3001\u907a\u6f0f\u88dc\u511f\u3001\u5c3e\u6578\u5340\u9593\u8207\u5171\u73fe\u5206\u6563",
            "\u5f37\u724c\u7d44\u52a0\u5165\u5340\u9593\u5206\u6563\u9650\u5236\uff0c\u907f\u514d\u96c6\u4e2d\u5728\u540c\u4e00\u6bb5\u8da8\u52e2",
            "\u555f\u7528\u8fd1\u671f\u5931\u6e96\u4fee\u6b63\u6a21\u5f0f\uff0c\u5c07\u5be6\u969b\u958b\u51fa\u4f46 Top10 \u6f0f\u6293\u7684\u865f\u78bc\u3001\u5c3e\u6578\u8207\u5340\u9593\u8f49\u5165\u4e0b\u671f\u88dc\u4f4d",
            "\u555f\u7528\u6708\u5ea6\u6392\u540d\u56de\u62c9\uff1a\u5c07\u672c\u6708\u91cd\u8907\u6f0f\u6293\u7684\u5be6\u958b\u865f\u3001\u5c3e\u6578\u8207\u5340\u9593\u7d0d\u5165\u4e0b\u671f Top10 \u908a\u754c\u6821\u6e96",
        ]
    elif settled["top10_hits"] <= 1 or recent_performance.get("recent_slump"):
        severity = "warning"
        actions = [
            "\u5c0f\u5e45\u964d\u4f4e\u77ed\u7dda\u8ffd\u71b1\u6b0a\u91cd",
            "\u63d0\u9ad8\u4e2d\u671f\u8207\u5340\u9593\u5206\u6563\u6bd4\u91cd",
            "\u555f\u7528\u8fd1\u671f Top10 \u88dc\u4f4d\uff0c\u5c07\u5f8c\u6bb5\u547d\u4e2d\u8207\u6f0f\u6293\u5be6\u958b\u865f\u78bc\u5f80\u524d\u63a8",
        ]
    return {
        "has_review": True,
        "severity": severity,
        "actions": actions,
        "last_settled": settled,
        "monthly_review": monthly_review,
        "rolling_adjustment": rolling_adjustment,
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


def build_two_stage_group_model(candidates):
    group_ranges = [
        ("1-5", 1, 5),
        ("6-10", 6, 10),
        ("11-15", 11, 15),
        ("16-20", 16, 20),
        ("21-25", 21, 25),
        ("26-30", 26, 30),
        ("31-35", 31, 35),
        ("36-39", 36, 39),
    ]
    min_probability = 85.0
    min_score = 90.0
    ranked = []
    for rank, item in enumerate(candidates, 1):
        score = float(item.get("score", 0) or 0)
        score_percent = score if score > 2 else score * 100
        probability = float(item.get("confidence_index", 0) or 0)
        number = int(item.get("number"))
        stability_count = int(item.get("stability_count", 0) or 0)
        if probability >= 92 and score_percent >= 94 and stability_count >= 3:
            risk = "low"
        elif probability >= 88 and score_percent >= 92:
            risk = "medium"
        else:
            risk = "watch"
        ranked.append(
            {
                "number": number,
                "rank": rank,
                "score_percent": round(score_percent, 1),
                "model_probability_percent": round(probability, 1),
                "omission": item.get("omission"),
                "stability_count": stability_count,
                "risk_level": risk,
                "reasons": item.get("reasons", [])[:5],
                "qualified": probability >= min_probability and score_percent >= min_score,
            }
        )

    first_round = []
    first_selected = []
    for label, start, end in group_ranges:
        group_items = [
            item for item in ranked
            if start <= item["number"] <= end and item["qualified"]
        ][:2]
        first_round.append(
            {
                "group": label,
                "range": [start, end],
                "max_output": 2,
                "status": "released" if group_items else "withheld_low_score",
                "numbers": group_items,
            }
        )
        first_selected.extend(group_items)

    first_selected = sorted(first_selected, key=lambda item: item["rank"])
    second_round = []
    final_numbers = []
    for idx in range(4):
        source = first_selected[idx * 4:(idx + 1) * 4]
        selected = [item for item in source if item["qualified"]][:4]
        second_round.append(
            {
                "group": f"R2-{idx + 1}",
                "source_numbers": [item["number"] for item in source],
                "max_output": 4,
                "status": "released" if selected else "withheld_low_score",
                "numbers": selected,
            }
        )
        final_numbers.extend(selected)

    final_numbers = sorted(final_numbers, key=lambda item: item["rank"])
    return {
        "model_name": "two_stage_8_zone_research_model",
        "purpose": "research_only_not_official_prediction",
        "thresholds": {
            "minimum_model_probability_percent": min_probability,
            "minimum_score_percent": min_score,
            "first_round_max_per_zone": 2,
            "second_round_group_count": 4,
            "second_round_max_per_group": 4,
        },
        "zone_ranges": [item[0] for item in group_ranges],
        "first_round": first_round,
        "second_round": second_round,
        "final_numbers": final_numbers,
        "final_count": len(final_numbers),
        "status": "released" if final_numbers else "withheld_no_number_reached_threshold",
    }


def backtest_two_stage_group_model(draws, windows=(60, 120, 240)):
    results = {}
    release_allowed = True
    for window in windows:
        if len(draws) < 130:
            results[str(window)] = {"rounds": 0, "status": "insufficient_data"}
            release_allowed = False
            continue
        start = max(100, len(draws) - window - 1)
        rounds = 0
        total_hits = 0
        zero_hits = 0
        total_output_count = 0
        for idx in range(start, len(draws) - 1):
            train = draws[:idx + 1]
            actual = set(draws[idx + 1]["numbers"])
            candidates = score_numbers(train)
            model = build_two_stage_group_model(candidates)
            numbers = [item["number"] for item in model.get("final_numbers", [])]
            if not numbers:
                continue
            hits = len(set(numbers) & actual)
            rounds += 1
            total_hits += hits
            total_output_count += len(numbers)
            if hits == 0:
                zero_hits += 1
        if rounds == 0:
            results[str(window)] = {
                "rounds": 0,
                "status": "no_released_samples",
                "passed": False,
            }
            release_allowed = False
            continue
        avg_hits = total_hits / rounds
        avg_output_count = total_output_count / rounds
        random_expectation = 5 * avg_output_count / 39
        edge = avg_hits - random_expectation
        zero_hit_rate = zero_hits / rounds
        passed = edge >= 0.03 and zero_hit_rate <= 0.58 and avg_output_count >= 1
        if not passed:
            release_allowed = False
        results[str(window)] = {
            "rounds": rounds,
            "avg_hits": round(avg_hits, 3),
            "avg_output_count": round(avg_output_count, 3),
            "random_expectation": round(random_expectation, 3),
            "edge_vs_random": round(edge, 3),
            "zero_hit_rate": round(zero_hit_rate, 3),
            "passed": passed,
            "status": "passed" if passed else "failed",
        }
    return {
        "windows": results,
        "release_allowed": release_allowed,
        "policy": "release only if 60/120/360 windows beat random expectation and zero-hit risk gate",
    }


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
        nums = " ".join(f"{n:02d}" for n in pack.get("numbers", []))
        lines.append(f"- {label}：{nums or '\u672a\u767c\u5e03'}，\u72c0\u614b {pack.get('status', 'released')}，\u5e73\u5747\u5206 {pack.get('avg_score', '-')}")
        if key == "nine_hit_three" and pack.get("wheel_tickets"):
            coverage = pack.get("wheel_coverage", {})
            lines.append(f"- 9\u4e2d3\u8f2a\u7d44\u8986\u84cb：{coverage.get('covered')}/{coverage.get('total')}，\u8986\u84cb\u7387 {coverage.get('rate')}")
            for idx, ticket in enumerate(pack.get("wheel_tickets", []), 1):
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


def _candidate_number_list(candidates, limit=None):
    numbers = []
    rows = candidates[:limit] if limit else candidates
    for item in rows:
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 39 and number not in numbers:
            numbers.append(number)
    return numbers


def _counter_rows(counter, limit=15, key_name="number"):
    return [
        {key_name: key, "count": count}
        for key, count in counter.most_common(limit)
    ]


def _avg(values):
    return round(sum(values) / len(values), 3) if values else 0.0


def dual_track_model_comparison(db_path, draws, window_days=31):
    """Compare raw unadjusted model output with saved rolling-adjusted predictions."""
    if not draws:
        return {
            "status": "not_available",
            "reason": "no_draw_data",
            "sample_count": 0,
        }
    latest_date = datetime.strptime(draws[-1]["draw_date"], "%Y-%m-%d").date()
    start_date = latest_date - timedelta(days=window_days)
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT based_on_period, based_on_date, target_period, actual_period, actual_date,
                       actual_numbers_json, candidates_json
                FROM predictions_539
                WHERE status='settled' AND actual_date >= ?
                ORDER BY actual_period
                """,
                (start_date.isoformat(),),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    """
                    SELECT based_on_period, based_on_date, target_period, actual_period, actual_date,
                           actual_numbers_json, candidates_json
                    FROM predictions_539
                    WHERE status='settled'
                    ORDER BY actual_period DESC
                    LIMIT 31
                    """
                ).fetchall()
                rows = list(reversed(rows))
    except sqlite3.OperationalError as exc:
        return {
            "status": "not_available",
            "reason": f"prediction_table_unavailable: {exc}",
            "sample_count": 0,
        }

    if not rows:
        return {
            "status": "not_available",
            "reason": "no_settled_predictions",
            "sample_count": 0,
        }

    period_index = {int(draw["period"]): idx for idx, draw in enumerate(draws)}
    top_sizes = (5, 10, 15)
    raw_hits = {size: [] for size in top_sizes}
    rolling_hits = {size: [] for size in top_sizes}
    raw_model_stats = defaultdict(lambda: {f"top{size}_hits": 0 for size in top_sizes} | {"rounds": 0})
    rescued_numbers = Counter()
    lost_numbers = Counter()
    false_promoted_numbers = Counter()
    raw_only_miss_numbers = Counter()
    period_rows = []
    top10_outcome = Counter()
    top15_outcome = Counter()

    for row in rows:
        based_on_period = int(row[0])
        based_index = period_index.get(based_on_period)
        if based_index is None or based_index < 100:
            continue
        actual_numbers = [int(number) for number in json.loads(row[5] or "[]")]
        if not actual_numbers:
            continue
        actual_set = set(actual_numbers)
        train = draws[: based_index + 1]
        raw_candidates, _ = industrial_score_numbers(train, review=None, include_dependency=True)
        rolling_candidates = json.loads(row[6] or "[]")
        raw_numbers = _candidate_number_list(raw_candidates)
        rolling_numbers = _candidate_number_list(rolling_candidates)

        if not raw_numbers or not rolling_numbers:
            continue

        raw_top10 = raw_numbers[:10]
        rolling_top10 = rolling_numbers[:10]
        raw_top15 = raw_numbers[:15]
        rolling_top15 = rolling_numbers[:15]

        raw_top10_hit_set = set(raw_top10) & actual_set
        rolling_top10_hit_set = set(rolling_top10) & actual_set
        raw_top15_hit_set = set(raw_top15) & actual_set
        rolling_top15_hit_set = set(rolling_top15) & actual_set

        for size in top_sizes:
            raw_count = len(set(raw_numbers[:size]) & actual_set)
            rolling_count = len(set(rolling_numbers[:size]) & actual_set)
            raw_hits[size].append(raw_count)
            rolling_hits[size].append(rolling_count)

        top10_gain = len(rolling_top10_hit_set) - len(raw_top10_hit_set)
        top15_gain = len(rolling_top15_hit_set) - len(raw_top15_hit_set)
        top10_outcome["rolling_win" if top10_gain > 0 else "raw_win" if top10_gain < 0 else "tie"] += 1
        top15_outcome["rolling_win" if top15_gain > 0 else "raw_win" if top15_gain < 0 else "tie"] += 1

        raw_only_top10 = set(raw_top10) - set(rolling_top10)
        rolling_only_top10 = set(rolling_top10) - set(raw_top10)
        rescued = sorted(rolling_only_top10 & actual_set)
        lost = sorted(raw_only_top10 & actual_set)
        false_promoted = sorted(rolling_only_top10 - actual_set)
        raw_only_miss = sorted(raw_only_top10 - actual_set)
        rescued_numbers.update(rescued)
        lost_numbers.update(lost)
        false_promoted_numbers.update(false_promoted)
        raw_only_miss_numbers.update(raw_only_miss)

        for model_name, label in MODEL_SOURCE_LABELS.items():
            ranked = sorted(
                raw_candidates,
                key=lambda item: (
                    float((item.get("feature_scores") or {}).get(model_name, 0.0) or 0.0),
                    -int(item.get("number", 0) or 0),
                ),
                reverse=True,
            )
            model_numbers = _candidate_number_list(ranked)
            if not model_numbers:
                continue
            raw_model_stats[model_name]["rounds"] += 1
            raw_model_stats[model_name]["label"] = label
            for size in top_sizes:
                raw_model_stats[model_name][f"top{size}_hits"] += len(set(model_numbers[:size]) & actual_set)

        period_rows.append({
            "based_on_period": based_on_period,
            "based_on_date": row[1],
            "target_period": int(row[2]) if row[2] is not None else None,
            "actual_period": int(row[3]) if row[3] is not None else None,
            "actual_date": row[4],
            "actual_numbers": actual_numbers,
            "raw_top10": raw_top10,
            "rolling_top10": rolling_top10,
            "raw_top10_hits": len(raw_top10_hit_set),
            "rolling_top10_hits": len(rolling_top10_hit_set),
            "raw_top15_hits": len(raw_top15_hit_set),
            "rolling_top15_hits": len(rolling_top15_hit_set),
            "top10_gain": top10_gain,
            "rescued_hit_numbers": rescued,
            "lost_hit_numbers": lost,
            "false_promoted_miss_numbers": false_promoted,
        })

    sample_count = len(period_rows)
    if not sample_count:
        return {
            "status": "not_available",
            "reason": "no_eligible_comparison_rows",
            "sample_count": 0,
        }

    random_expectation = {size: round(5 * size / 39, 3) for size in top_sizes}
    raw_summary = {
        f"top{size}_avg_hits": _avg(raw_hits[size])
        for size in top_sizes
    }
    rolling_summary = {
        f"top{size}_avg_hits": _avg(rolling_hits[size])
        for size in top_sizes
    }
    delta_summary = {
        f"top{size}_avg_hit_delta": round(rolling_summary[f"top{size}_avg_hits"] - raw_summary[f"top{size}_avg_hits"], 3)
        for size in top_sizes
    }
    top10_delta = delta_summary["top10_avg_hit_delta"]
    if top10_delta >= 0.15 and top10_outcome["rolling_win"] >= top10_outcome["raw_win"]:
        decision = "rolling_adjustment_helpful"
        decision_label = "滾動調整目前有幫助"
    elif top10_delta <= -0.15 and top10_outcome["raw_win"] > top10_outcome["rolling_win"]:
        decision = "rolling_adjustment_harmful"
        decision_label = "滾動調整目前傷害命中"
    else:
        decision = "mixed_or_neutral"
        decision_label = "原始模型與滾動調整暫無明顯勝負"

    raw_model_scorecard = []
    for model_name, stats in raw_model_stats.items():
        rounds = stats["rounds"] or 1
        row = {
            "model": model_name,
            "label": stats.get("label") or MODEL_SOURCE_LABELS.get(model_name, model_name),
            "rounds": stats["rounds"],
        }
        for size in top_sizes:
            avg_hits = round(stats[f"top{size}_hits"] / rounds, 3)
            row[f"top{size}_avg_hits"] = avg_hits
            row[f"top{size}_edge_vs_random"] = round(avg_hits - random_expectation[size], 3)
        raw_model_scorecard.append(row)
    raw_model_scorecard.sort(
        key=lambda item: (
            item.get("top10_edge_vs_random", -99),
            item.get("top5_edge_vs_random", -99),
            item.get("top10_avg_hits", 0),
        ),
        reverse=True,
    )

    return {
        "status": "evaluated",
        "method": "raw_unadjusted_models_vs_saved_rolling_adjusted_predictions",
        "policy": "同一個預測基準日比較原始未調整模型與當時已保存的滾動調整預測，不使用未來資料。",
        "window_days": window_days,
        "sample_count": sample_count,
        "date_range": [period_rows[0]["actual_date"], period_rows[-1]["actual_date"]],
        "random_expectation": random_expectation,
        "summary": {
            "raw_unadjusted": raw_summary,
            "rolling_adjusted": rolling_summary,
            "delta": delta_summary,
            "top10_win_loss": dict(top10_outcome),
            "top15_win_loss": dict(top15_outcome),
            "decision": decision,
            "decision_label": decision_label,
        },
        "adjustment_error_audit": {
            "rescued_hit_numbers": _counter_rows(rescued_numbers, 15),
            "lost_hit_numbers": _counter_rows(lost_numbers, 15),
            "false_promoted_miss_numbers": _counter_rows(false_promoted_numbers, 15),
            "raw_only_miss_numbers": _counter_rows(raw_only_miss_numbers, 15),
        },
        "raw_model_scorecard": raw_model_scorecard[:24],
        "period_rows": period_rows[-31:],
    }


def probability_track_separation(industrial, dual_track):
    unlikely = industrial.get("unlikely_number_analysis") or {}
    avoid_packs = unlikely.get("avoid_packs") or {}
    strong_packs = industrial.get("strong_prediction_packs") or {}
    decision = industrial.get("decisive_battle_decision") or {}
    return {
        "status": "separated",
        "high_probability_track": {
            "purpose": "下期高機率候選、獨隻與強牌組推薦",
            "inputs": ["全歷史開獎資料", "原始模型分數", "滾動命中檢討", "交叉驗證", "強牌回測"],
            "outputs": {
                "primary_single": decision.get("primary_single") or (strong_packs.get("strong_single") or {}).get("numbers", []),
                "attack_core_top9": decision.get("attack_core_top9", []),
                "strong_pack_keys": list(strong_packs.keys()),
            },
            "dual_track_status": dual_track.get("status"),
            "dual_track_decision": (dual_track.get("summary") or {}).get("decision_label"),
        },
        "low_probability_track": {
            "purpose": "5不中、10不中、15不中暫避與誤中檢討",
            "inputs": ["弱訊號", "候選排名落點", "暫避分數", "低機率回測"],
            "outputs": {
                key: (avoid_packs.get(key) or {}).get("numbers", [])
                for key in ["five_miss", "ten_miss", "fifteen_miss"]
            },
            "rule": "低機率只做暫避研究，不參與高機率推薦排序。",
        },
    }


def analyze(db_path=DB_PATH):
    draws = fetch_draws(db_path)
    if len(draws) < 100:
        raise RuntimeError("\u8cc7\u6599\u4e0d\u8db3，\u81f3\u5c11\u9700\u8981 100 \u671f\u624d\u80fd\u7522\u751f\u5b8c\u6574\u5206\u6790。")

    bt = backtest(draws)
    review = failure_review(db_path)
    weights = apply_failure_adjustment(calibrated_weights(bt), review)
    industrial = compute_industrial_analysis(draws, review)
    dual_track = dual_track_model_comparison(db_path, draws)
    industrial["dual_track_model_comparison"] = dual_track
    aerospace = compute_aerospace_assurance(draws, industrial)
    if aerospace["release_assurance"]["status"] == "blocked":
        industrial.setdefault("release_gate", {})["status"] = "aerospace_blocked"
    elif aerospace["release_assurance"]["status"] == "watch_only":
        industrial.setdefault("release_gate", {})["aerospace_status"] = "watch_only"
    analysis = {
        "generated_at": taipei_now().isoformat(timespec="seconds"),
        "prediction_mode": "current_precision_stability_v44_micro_confidence_short_packs",
        "latest_draw": draws[-1],
        "data_freshness": build_data_freshness(draws[-1]["draw_date"]),
        "windows": [window_summary(draws, size) for size in WINDOWS],
        "relationships": relationship_analysis(draws),
        "failure_review": review,
        "industrial_engine": industrial,
        "dual_track_model_comparison": dual_track,
        "probability_track_separation": probability_track_separation(industrial, dual_track),
        "aerospace_assurance": aerospace,
        "backtest": bt,
        "model_weights": weights,
        "candidates": industrial["candidates"],
        "official_candidates": industrial.get("qualified_candidates", industrial["candidates"]),
    }
    analysis["suggested_sets"] = build_sets(analysis["official_candidates"]) if len(analysis["official_candidates"]) >= 18 else []
    analysis["strong_prediction_packs"] = industrial["strong_prediction_packs"]
    two_stage_model = build_two_stage_group_model(analysis["official_candidates"])
    two_stage_backtest = backtest_two_stage_group_model(draws)
    two_stage_model["validation_backtest"] = two_stage_backtest
    if not two_stage_backtest.get("release_allowed"):
        two_stage_model["blocked_final_numbers"] = two_stage_model.get("final_numbers", [])
        two_stage_model["final_numbers"] = []
        two_stage_model["final_count"] = 0
        two_stage_model["status"] = "withheld_backtest_not_passed"
    analysis["two_stage_group_model"] = two_stage_model
    return analysis


def save_analysis(analysis):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(LATEST_JSON, json.dumps(analysis, ensure_ascii=False, indent=2))
    atomic_write_text(LATEST_MD, render_markdown(analysis))
    monthly_review = (analysis.get("failure_review") or {}).get("monthly_review")
    if monthly_review:
        atomic_write_text(MONTHLY_REVIEW_JSON, json.dumps(monthly_review, ensure_ascii=False, indent=2))


def atomic_write_text(path, text):
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def main():
    parser = argparse.ArgumentParser(description="\u4eca\u5f69539\u958b\u734e\u5f8c\u7d71\u8a08\u5206\u6790")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    analysis = analyze(Path(args.db))
    save_analysis(analysis)
    print(f"\u5df2\u7522\u751f\u5206\u6790\u5831\u544a：{LATEST_MD}")
    print("\u5019\u9078 Top 10：" + " ".join(f"{x['number']:02d}" for x in analysis["candidates"][:10]))
    if analysis["suggested_sets"]:
        print("\u53c3\u8003\u7d44\u5408 1：" + " ".join(f"{n:02d}" for n in analysis["suggested_sets"][0]))
    else:
        print("\u53c3\u8003\u7d44\u5408\uff1a\u672c\u671f\u672a\u9054\u6b63\u5f0f\u767c\u5e03\u9580\u6abb\uff0c\u4e0d\u786c\u6e4a\u7522\u51fa")


if __name__ == "__main__":
    main()
