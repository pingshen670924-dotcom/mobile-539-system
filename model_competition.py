import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
COMPETITION_JSON = REPORT_DIR / "model_competition.json"
COMPETITION_MD = REPORT_DIR / "model_competition.md"
NUMBER_MAX = 39
DRAW_SIZE = 5


def fetch_draws(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT period, draw_date, n1, n2, n3, n4, n5
            FROM draws_539
            ORDER BY period
            """
        ).fetchall()
    return [
        {"period": row[0], "draw_date": row[1], "numbers": list(row[2:7])}
        for row in rows
    ]


def latest_failure_set(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT candidates_json, strong_pack_hits_json, actual_numbers_json, top10_hits
            FROM predictions_539
            WHERE status='settled'
            ORDER BY actual_period DESC
            LIMIT 1
            """
        ).fetchone()
    if not row or row[3] != 0:
        return set()
    candidates = [item["number"] for item in json.loads(row[0] or "[]")[:15]]
    actual = set(json.loads(row[2] or "[]"))
    failed = set(candidates)
    for pack in json.loads(row[1] or "{}").values():
        if not pack.get("passed"):
            failed.update(pack.get("numbers", []))
    return failed - actual


def normalize(values):
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {key: 0.0 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def rank(values):
    return sorted(range(1, NUMBER_MAX + 1), key=lambda n: (values.get(n, 0), -n), reverse=True)


def frequency(draws):
    counter = Counter()
    for draw in draws:
        counter.update(draw["numbers"])
    return counter


def omission(draws):
    last_seen = {n: None for n in range(1, NUMBER_MAX + 1)}
    for idx, draw in enumerate(draws):
        for number in draw["numbers"]:
            last_seen[number] = idx
    last_index = len(draws) - 1
    return {
        n: (last_index - last_seen[n] if last_seen[n] is not None else len(draws))
        for n in range(1, NUMBER_MAX + 1)
    }


def zone(number):
    if number <= 10:
        return "01-10"
    if number <= 20:
        return "11-20"
    if number <= 30:
        return "21-30"
    return "31-39"


def next_date_numbers(date_text):
    current = datetime.strptime(date_text, "%Y-%m-%d").date()
    candidate = current + timedelta(days=1)
    while candidate.weekday() == 6:
        candidate += timedelta(days=1)
    roc = candidate.year - 1911
    values = [
        roc,
        candidate.month,
        candidate.day,
        int(f"{candidate.month}{candidate.day:02d}"),
        sum(int(ch) for ch in candidate.strftime("%Y%m%d")),
        roc + candidate.month,
        roc + candidate.day,
        candidate.month + candidate.day,
    ]
    result = set()
    for value in values:
        result.add(((abs(int(value)) - 1) % NUMBER_MAX) + 1 if value else NUMBER_MAX)
    return result


def pair_tail_scores(draws):
    latest = set(draws[-1]["numbers"])
    pair_counter = Counter()
    tail_counter = Counter()
    zone_counter = Counter()
    for draw in draws[-120:]:
        nums = sorted(draw["numbers"])
        for left_idx, left in enumerate(nums):
            tail_counter[left % 10] += 1
            zone_counter[zone(left)] += 1
            for right in nums[left_idx + 1:]:
                pair_counter[tuple(sorted((left, right)))] += 1
    pair_score = {}
    for number in range(1, NUMBER_MAX + 1):
        pair_score[number] = sum(pair_counter.get(tuple(sorted((number, anchor))), 0) for anchor in latest)
    pair_norm = normalize(pair_score)
    tail_norm = normalize({tail: tail_counter.get(tail, 0) for tail in range(10)})
    zone_norm = normalize({label: zone_counter.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    return {
        number: pair_norm[number] * 0.6 + tail_norm[number % 10] * 0.25 + zone_norm[zone(number)] * 0.15
        for number in range(1, NUMBER_MAX + 1)
    }


def model_scores(draws, model_name, failed=None):
    failed = failed or set()
    freq20 = frequency(draws[-20:])
    freq50 = frequency(draws[-50:])
    freq100 = frequency(draws[-100:])
    hot20 = normalize({n: freq20.get(n, 0) for n in range(1, NUMBER_MAX + 1)})
    hot50 = normalize({n: freq50.get(n, 0) for n in range(1, NUMBER_MAX + 1)})
    hot100 = normalize({n: freq100.get(n, 0) for n in range(1, NUMBER_MAX + 1)})
    gaps = normalize({n: math.log1p(v) for n, v in omission(draws).items()})
    inverse_hot20 = normalize({n: 1 - hot20[n] for n in range(1, NUMBER_MAX + 1)})
    pair_tail = pair_tail_scores(draws)
    dates = next_date_numbers(draws[-1]["draw_date"])
    date_score = {n: (1.0 if n in dates else 0.0) for n in range(1, NUMBER_MAX + 1)}
    neighbor_score = {
        n: (1.0 if any(abs(n - anchor) == 1 for anchor in draws[-1]["numbers"]) else 0.0)
        for n in range(1, NUMBER_MAX + 1)
    }

    if model_name == "stable_hot":
        score = {n: hot20[n] * 0.2 + hot50[n] * 0.45 + hot100[n] * 0.35 for n in range(1, NUMBER_MAX + 1)}
    elif model_name == "cold_rebound":
        score = {n: gaps[n] * 0.72 + inverse_hot20[n] * 0.28 for n in range(1, NUMBER_MAX + 1)}
    elif model_name == "pair_tail":
        score = pair_tail
    elif model_name == "date_neighbor":
        score = {n: date_score[n] * 0.58 + neighbor_score[n] * 0.42 for n in range(1, NUMBER_MAX + 1)}
    elif model_name == "anti_failure":
        base = {n: hot50[n] * 0.25 + hot100[n] * 0.25 + gaps[n] * 0.3 + pair_tail[n] * 0.2 for n in range(1, NUMBER_MAX + 1)}
        score = dict(base)
        for n in failed:
            if n in score:
                score[n] *= 0.12
    else:
        score = {
            n: hot50[n] * 0.22 + hot100[n] * 0.2 + gaps[n] * 0.22 + pair_tail[n] * 0.24 + date_score[n] * 0.05 + neighbor_score[n] * 0.07
            for n in range(1, NUMBER_MAX + 1)
        }
    return normalize(score)


def backtest_model(draws, model_name, rounds=240):
    if len(draws) < 140:
        return {"rounds": 0, "top5_avg_hits": 0, "top10_avg_hits": 0, "top15_avg_hits": 0}
    start = max(120, len(draws) - rounds - 1)
    top5 = 0
    top10 = 0
    top15 = 0
    total = 0
    top10_distribution = Counter()
    top15_distribution = Counter()
    recent_hits = []
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        ranked = rank(model_scores(train, model_name))
        hit5 = len(set(ranked[:5]) & actual)
        hit10 = len(set(ranked[:10]) & actual)
        hit15 = len(set(ranked[:15]) & actual)
        top5 += hit5
        top10 += hit10
        top15 += hit15
        top10_distribution[hit10] += 1
        top15_distribution[hit15] += 1
        recent_hits.append({"top5": hit5, "top10": hit10, "top15": hit15})
        total += 1
    random_top5 = DRAW_SIZE * 5 / NUMBER_MAX
    random_top10 = DRAW_SIZE * 10 / NUMBER_MAX
    random_top15 = DRAW_SIZE * 15 / NUMBER_MAX
    return {
        "rounds": total,
        "top5_avg_hits": round(top5 / total, 3) if total else 0,
        "top10_avg_hits": round(top10 / total, 3) if total else 0,
        "top15_avg_hits": round(top15 / total, 3) if total else 0,
        "top5_edge_vs_random": round((top5 / total) - random_top5, 3) if total else 0,
        "top10_edge_vs_random": round((top10 / total) - random_top10, 3) if total else 0,
        "top15_edge_vs_random": round((top15 / total) - random_top15, 3) if total else 0,
        "top10_distribution": {str(hit): top10_distribution.get(hit, 0) for hit in range(6)},
        "top15_distribution": {str(hit): top15_distribution.get(hit, 0) for hit in range(6)},
        "hit_rates": {
            "top10_ge_1": round(sum(count for hit, count in top10_distribution.items() if hit >= 1) / total, 3) if total else 0,
            "top10_ge_2": round(sum(count for hit, count in top10_distribution.items() if hit >= 2) / total, 3) if total else 0,
            "top10_ge_3": round(sum(count for hit, count in top10_distribution.items() if hit >= 3) / total, 3) if total else 0,
            "top15_ge_1": round(sum(count for hit, count in top15_distribution.items() if hit >= 1) / total, 3) if total else 0,
            "top15_ge_2": round(sum(count for hit, count in top15_distribution.items() if hit >= 2) / total, 3) if total else 0,
            "top15_ge_3": round(sum(count for hit, count in top15_distribution.items() if hit >= 3) / total, 3) if total else 0,
        },
        "last_20_avg_top10": round(sum(item["top10"] for item in recent_hits[-20:]) / min(len(recent_hits), 20), 3) if recent_hits else 0,
    }


def segmented_backtest(draws, model_name):
    return {
        "last_60": backtest_model(draws, model_name, 60),
        "last_120": backtest_model(draws, model_name, 120),
        "last_240": backtest_model(draws, model_name, 240),
    }


def model_profile(model_name):
    profiles = {
        "stable_hot": "\u4e2d\u9577\u671f\u983b\u7387\u7a69\u5b9a\u6d3e\uff0c\u964d\u4f4e\u77ed\u7dda\u904e\u71b1\u504f\u8aa4",
        "cold_rebound": "\u51b7\u865f\u8207\u907a\u6f0f\u88dc\u511f\u6d3e\uff0c\u88dc\u5145\u9577\u671f\u672a\u51fa\u98a8\u96aa\u5340",
        "pair_tail": "\u5171\u73fe\u3001\u5c3e\u6578\u8207\u5340\u9593\u7d50\u69cb\u6d3e\uff0c\u91cd\u8996\u724c\u578b\u5206\u6563",
        "date_neighbor": "\u65e5\u671f\u724c\u8207\u912d\u8fd1\u724c\u6d3e\uff0c\u63d0\u4f9b\u7279\u6b8a\u4fe1\u865f\u7684\u8f14\u52a9\u5206",
        "anti_failure": "\u5931\u6557\u9694\u96e2\u6d3e\uff0c\u4e0a\u6b21\u5927\u504f\u6642\u964d\u4f4e\u820a\u932f\u865f\u518d\u5165\u9078",
        "ensemble": "\u7d9c\u5408\u6295\u7968\u6d3e\uff0c\u628a\u591a\u500b\u6a21\u578b\u5f97\u5206\u5408\u4f75\u6210\u4e3b\u7dda\u5224\u65b7",
    }
    return profiles.get(model_name, "")


def run_competition(db_path=DB_PATH):
    draws = fetch_draws(db_path)
    failed = latest_failure_set(db_path)
    model_names = ["stable_hot", "cold_rebound", "pair_tail", "date_neighbor", "anti_failure", "ensemble"]
    models = []
    for model_name in model_names:
        scores = model_scores(draws, model_name, failed)
        ranked = rank(scores)
        result = backtest_model(draws, model_name)
        result["segmented_backtest"] = segmented_backtest(draws, model_name)
        result["profile"] = model_profile(model_name)
        result["model"] = model_name
        result["top15"] = ranked[:15]
        result["top10"] = ranked[:10]
        models.append(result)
    models.sort(key=lambda item: (item["top10_avg_hits"], item["top15_avg_hits"]), reverse=True)
    champion = models[0] if models else {}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "models": models,
        "champion": champion,
        "failed_isolation_numbers": sorted(failed),
        "random_top10_expectation": round(DRAW_SIZE * 10 / NUMBER_MAX, 3),
        "random_top15_expectation": round(DRAW_SIZE * 15 / NUMBER_MAX, 3),
        "research_notes": [
            "\u71b1\u865f\u3001\u51b7\u865f\u8207\u907a\u6f0f\u53ea\u80fd\u7576\u4f5c\u6b77\u53f2\u7d50\u69cb\uff0c\u4e0d\u80fd\u55ae\u7368\u7576\u4f5c\u9810\u6e2c\u4fdd\u8b49",
            "\u591a\u6a21\u578b\u6295\u7968\u8981\u540c\u6642\u5c55\u793a\u56de\u6e2c\u3001\u53ef\u89e3\u91cb\u7406\u7531\u8207\u96a8\u6a5f\u57fa\u6e96",
            "\u8f2a\u7d44\u8207\u5305\u724c\u5c6c\u65bc\u8986\u84cb\u7d50\u69cb\uff0c\u5fc5\u9808\u8aaa\u660e\u7968\u6578\u3001\u8986\u84cb\u7387\u8207\u6210\u672c\u98a8\u96aa",
        ],
    }


def save_competition(result):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    COMPETITION_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 539 \u591a\u6a21\u578b\u7af6\u8cfd", ""]
    lines.append(f"- \u7522\u751f\u6642\u9593\uff1a{result['generated_at']}")
    lines.append(f"- \u51a0\u8ecd\u6a21\u578b\uff1a{result.get('champion', {}).get('model')}")
    lines.append(f"- \u5931\u6557\u9694\u96e2\u865f\uff1a{' '.join(f'{n:02d}' for n in result.get('failed_isolation_numbers', []))}")
    lines.append(f"- \u96a8\u6a5f Top10 \u57fa\u6e96\uff1a{result.get('random_top10_expectation')}")
    lines.append(f"- \u96a8\u6a5f Top15 \u57fa\u6e96\uff1a{result.get('random_top15_expectation')}")
    lines.append("")
    lines.append("## \u5916\u90e8\u65b9\u6cd5\u8f49\u5316")
    for note in result.get("research_notes", []):
        lines.append(f"- {note}")
    lines.append("")
    lines.append("| \u6a21\u578b | Top5 | Top10 | Top15 | Top10\u5dee\u503c | Top15\u5dee\u503c | Top10>=2 | Top15>=3 | \u5019\u9078Top10 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for model in result["models"]:
        rates = model.get("hit_rates", {})
        lines.append(
            f"| {model['model']} | {model.get('top5_avg_hits')} | {model['top10_avg_hits']} | {model['top15_avg_hits']} | "
            f"{model.get('top10_edge_vs_random')} | {model.get('top15_edge_vs_random')} | "
            f"{rates.get('top10_ge_2')} | {rates.get('top15_ge_3')} | "
            + " ".join(f"{n:02d}" for n in model["top10"])
            + " |"
        )
    lines.append("")
    lines.append("## \u6a21\u578b\u8aaa\u660e")
    for model in result["models"]:
        lines.append(f"- {model['model']}\uff1a{model.get('profile', '')}")
    lines.append("")
    lines.append("## \u5206\u6bb5\u56de\u6e2c")
    for model in result["models"]:
        segments = model.get("segmented_backtest", {})
        lines.append(f"### {model['model']}")
        for label, data in segments.items():
            lines.append(
                f"- {label}\uff1aTop10 {data.get('top10_avg_hits')} / Top15 {data.get('top15_avg_hits')} / "
                f"Top10>=2 {data.get('hit_rates', {}).get('top10_ge_2')} / Top15>=3 {data.get('hit_rates', {}).get('top15_ge_3')}"
            )
    COMPETITION_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    result = run_competition(DB_PATH)
    save_competition(result)
    print(f"competition saved: {COMPETITION_JSON}")


if __name__ == "__main__":
    main()
