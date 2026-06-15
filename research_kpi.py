import math


MINIMUM_SETTLED_SAMPLES = 30
TARGET_PASS_RATE = 1.0

KPI_DEFINITIONS = {
    "top15": {"label": "15\u9846\u4e2d3\u81f35\u9846", "minimum_hits": 3, "maximum_hits": 5},
    "nine_hit_three": {"label": "9\u9846\u4e2d3\u81f35\u9846", "minimum_hits": 3, "maximum_hits": 5},
    "five_hit_two": {"label": "5\u9846\u4e2d2\u81f35\u9846", "minimum_hits": 2, "maximum_hits": 5},
    "three_hit_one": {"label": "3\u9846\u4e2d1\u81f33\u9846", "minimum_hits": 1, "maximum_hits": 3},
    "two_hit_one": {"label": "2\u9846\u4e2d1\u81f32\u9846", "minimum_hits": 1, "maximum_hits": 2},
    "strong_single": {"label": "1\u9846\u4e2d1\u9846", "minimum_hits": 1, "maximum_hits": 1},
}


def wilson_lower_bound(successes, total, confidence_z=1.96):
    if total <= 0:
        return 0.0
    rate = successes / total
    denominator = 1 + confidence_z * confidence_z / total
    centre = rate + confidence_z * confidence_z / (2 * total)
    margin = confidence_z * math.sqrt((rate * (1 - rate) + confidence_z * confidence_z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def evaluate_research_kpis(records):
    total = len(records)
    results = {}
    for key, definition in KPI_DEFINITIONS.items():
        minimum = definition["minimum_hits"]
        hits = []
        for record in records:
            if key == "top15":
                value = int(record.get("top15_hits") or 0)
            else:
                value = int((record.get("strong_pack_hits") or {}).get(key, {}).get("hits") or 0)
            hits.append(value)
        target_band_successes = sum(1 for value in hits if minimum <= value <= definition["maximum_hits"])
        over_target_successes = sum(1 for value in hits if value > definition["maximum_hits"])
        successes = target_band_successes + over_target_successes
        pass_rate = successes / total if total else 0.0
        results[key] = {
            **definition,
            "settled_samples": total,
            "successes": successes,
            "target_band_successes": target_band_successes,
            "over_target_successes": over_target_successes,
            "failures": total - successes,
            "pass_rate": round(pass_rate, 4),
            "wilson_lower_95": round(wilson_lower_bound(successes, total), 4),
            "average_hits": round(sum(hits) / total, 4) if total else 0.0,
            "met_in_observed_samples": total > 0 and successes == total,
        }

    enough_samples = total >= MINIMUM_SETTLED_SAMPLES
    all_observed_pass = all(item["met_in_observed_samples"] for item in results.values())
    status = "met" if enough_samples and all_observed_pass else ("insufficient_samples" if not enough_samples else "not_met")
    return {
        "status": status,
        "settled_samples": total,
        "minimum_settled_samples": MINIMUM_SETTLED_SAMPLES,
        "target_pass_rate": TARGET_PASS_RATE,
        "all_observed_pass": all_observed_pass,
        "release_allowed": status == "met",
        "warning": "Research targets are evaluation goals, not guaranteed lottery outcomes.",
        "levels": results,
    }
