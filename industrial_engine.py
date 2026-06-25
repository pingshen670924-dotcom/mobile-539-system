import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations


NUMBER_MIN = 1
NUMBER_MAX = 39
DRAW_SIZE = 5
BASE_PROBABILITY = DRAW_SIZE / NUMBER_MAX
EXPECTED_GAP = NUMBER_MAX / DRAW_SIZE


def zone_label(number):
    if number <= 10:
        return "01-10"
    if number <= 20:
        return "11-20"
    if number <= 30:
        return "21-30"
    return "31-39"


def normalize(values):
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {key: 0.0 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def rank_values(values):
    return sorted(range(NUMBER_MIN, NUMBER_MAX + 1), key=lambda n: (values.get(n, 0), -n), reverse=True)


def frequency(draws):
    counter = Counter()
    for draw in draws:
        counter.update(draw["numbers"])
    return counter


def omission(draws):
    last_seen = {n: None for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for idx, draw in enumerate(draws):
        for number in draw["numbers"]:
            last_seen[number] = idx
    last_index = len(draws) - 1
    return {
        number: (last_index - last_seen[number] if last_seen[number] is not None else len(draws))
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }


def binomial_zscore(count, draws_count):
    expected = draws_count * BASE_PROBABILITY
    variance = max(draws_count * BASE_PROBABILITY * (1 - BASE_PROBABILITY), 1e-9)
    return (count - expected) / math.sqrt(variance)


def ewma_frequency(draws, half_life):
    scores = {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    decay_base = 0.5 ** (1 / half_life)
    for age, draw in enumerate(reversed(draws)):
        weight = decay_base ** age
        for number in draw["numbers"]:
            scores[number] += weight
    return scores


def next_draw_date(date_text):
    current = datetime.strptime(date_text, "%Y-%m-%d").date()
    candidate = current + timedelta(days=1)
    while candidate.weekday() == 6:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def normalize_number(value):
    value = abs(int(value))
    if value == 0:
        return NUMBER_MAX
    return ((value - 1) % NUMBER_MAX) + 1


def date_numbers(date_text):
    date_value = datetime.strptime(date_text, "%Y-%m-%d")
    roc_year = date_value.year - 1911
    raw = [
        roc_year,
        date_value.month,
        date_value.day,
        int(f"{date_value.month}{date_value.day:02d}"),
        sum(int(ch) for ch in date_value.strftime("%Y%m%d")),
        roc_year + date_value.month,
        roc_year + date_value.day,
        date_value.month + date_value.day,
    ]
    result = []
    for value in raw:
        number = normalize_number(value)
        if number not in result:
            result.append(number)
    return result


def transition_scores(draws):
    latest_numbers = set(draws[-1]["numbers"])
    transition = Counter()
    source_map = defaultdict(Counter)
    for idx in range(len(draws) - 1):
        current = set(draws[idx]["numbers"])
        next_numbers = draws[idx + 1]["numbers"]
        anchors = latest_numbers & current
        if not anchors:
            continue
        for anchor in anchors:
            source_map[anchor].update(next_numbers)
        transition.update(next_numbers)
    return normalize({n: transition.get(n, 0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}), source_map


def markov_chain_scores(draws, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    latest = set(draws[-1]["numbers"])
    scores = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    if len(subset) < 3:
        return scores
    target_total = Counter()
    source_total = Counter()
    transition_total = defaultdict(Counter)
    for idx in range(len(subset) - 1):
        current = set(subset[idx]["numbers"])
        following = set(subset[idx + 1]["numbers"])
        target_total.update(following)
        for source in current:
            source_total[source] += 1
            transition_total[source].update(following)
    transitions = max(len(subset) - 1, 1)
    for source in latest:
        support = source_total.get(source, 0)
        if support < 12:
            continue
        for target in range(NUMBER_MIN, NUMBER_MAX + 1):
            conditional = transition_total[source].get(target, 0) / support
            baseline = target_total.get(target, 0) / transitions
            lift = conditional - baseline
            if lift > 0:
                scores[target] += lift
    return normalize(scores)


def time_series_scores(draws, window=240):
    subset = draws[-window:] if len(draws) > window else draws
    scores = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        fast = 0.0
        slow = 0.0
        for age, draw in enumerate(reversed(subset)):
            hit = 1.0 if number in draw["numbers"] else 0.0
            fast += hit * (0.5 ** (age / 18))
            slow += hit * (0.5 ** (age / 72))
        trend = fast - slow * 0.42
        scores[number] = trend
    return normalize(scores)


def neural_network_scores(draws):
    freq20 = normalize({n: frequency(draws[-20:]).get(n, 0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})
    freq100 = normalize({n: frequency(draws[-100:]).get(n, 0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})
    gaps = omission(draws)
    gap_score = normalize({n: math.log1p(gaps[n]) for n in gaps})
    markov = markov_chain_scores(draws, window=900)
    series = time_series_scores(draws, window=180)
    latest = set(draws[-1]["numbers"])
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        x = (
            freq20[number] * 0.58
            + freq100[number] * 0.72
            + gap_score[number] * 0.64
            + markov[number] * 0.82
            + series[number] * 0.74
            - (0.85 if number in latest else 0.0)
        )
        values[number] = 1.0 / (1.0 + math.exp(-(x - 1.15)))
    return normalize(values)


def validated_dependency_scores(draws, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    latest_numbers = sorted(set(draws[-1]["numbers"]))
    score = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    hypotheses = []
    fold_size = max(2, len(subset) // 3)
    segments = [
        subset[:fold_size + 1],
        subset[fold_size:max(fold_size + 2, fold_size * 2 + 1)],
        subset[max(0, fold_size * 2):],
    ]

    def segment_stat(segment, source, target):
        support = 0
        hits = 0
        target_total = 0
        transitions = max(len(segment) - 1, 1)
        for idx in range(len(segment) - 1):
            current = set(segment[idx]["numbers"])
            following = set(segment[idx + 1]["numbers"])
            if target in following:
                target_total += 1
            if source in current:
                support += 1
                if target in following:
                    hits += 1
        conditional = hits / support if support else 0.0
        baseline = target_total / transitions if transitions else BASE_PROBABILITY
        lift = conditional / baseline if baseline else 0.0
        standard_error = math.sqrt(max(baseline * (1 - baseline) / support, 1e-9)) if support else 1.0
        z_value = (conditional - baseline) / standard_error if support else 0.0
        p_value = 0.5 * math.erfc(z_value / math.sqrt(2))
        return support, hits, conditional, baseline, lift, z_value, p_value

    for source in latest_numbers:
        for target in range(NUMBER_MIN, NUMBER_MAX + 1):
            stats = [segment_stat(segment, source, target) for segment in segments]
            if all(item[0] >= 18 and item[4] >= 1.03 and item[5] > 0 for item in stats):
                hypotheses.append({
                    "source": source,
                    "target": target,
                    "stats": stats,
                    "p_value": max(item[6] for item in stats),
                    "conservative_lift": min(item[4] for item in stats),
                })

    links = []
    ordered = sorted(hypotheses, key=lambda item: item["p_value"])
    test_count = max(len(latest_numbers) * NUMBER_MAX, 1)
    accepted = []
    for rank, item in enumerate(ordered, 1):
        if item["p_value"] <= 0.10 * rank / test_count:
            accepted.append(item)
    for item in accepted:
        stats = item["stats"]
        conservative_lift = item["conservative_lift"]
        score[item["target"]] += min(conservative_lift - 1, 0.75)
        links.append({
            "source": item["source"],
            "target": item["target"],
            "fold_support": [fold[0] for fold in stats],
            "fold_hits": [fold[1] for fold in stats],
            "fold_lift": [round(fold[4], 3) for fold in stats],
            "fold_z": [round(fold[5], 3) for fold in stats],
            "p_value": round(item["p_value"], 6),
            "fdr_q": 0.10,
            "conservative_lift": round(conservative_lift, 3),
        })
    links.sort(key=lambda item: (item["conservative_lift"], min(item["fold_support"])), reverse=True)
    return normalize(score), links


def lag_dependency_profile(draws, max_lag=5, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    profile = []
    expected_overlap = DRAW_SIZE * DRAW_SIZE / NUMBER_MAX
    for lag in range(1, max_lag + 1):
        overlaps = []
        for idx in range(lag, len(subset)):
            overlaps.append(len(set(subset[idx]["numbers"]) & set(subset[idx - lag]["numbers"])))
        average = sum(overlaps) / len(overlaps) if overlaps else 0.0
        profile.append({
            "lag": lag,
            "samples": len(overlaps),
            "average_overlap": round(average, 4),
            "random_expectation": round(expected_overlap, 4),
            "edge": round(average - expected_overlap, 4),
        })
    return profile


def pair_scores(draws):
    latest_numbers = set(draws[-1]["numbers"])
    pair_counter = Counter()
    for draw in draws[-300:]:
        for pair in combinations(sorted(draw["numbers"]), 2):
            pair_counter[pair] += 1
    scores = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        scores[number] = sum(pair_counter.get(tuple(sorted((number, anchor))), 0) for anchor in latest_numbers)
    return normalize(scores)


def tail_zone_scores(draws):
    tail = Counter()
    zone = Counter()
    for draw in draws[-80:]:
        for number in draw["numbers"]:
            tail[number % 10] += 1
            zone[zone_label(number)] += 1
    tail_norm = normalize({n: tail.get(n, 0) for n in range(10)})
    zone_norm = normalize({label: zone.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    return {
        number: (tail_norm[number % 10] + zone_norm[zone_label(number)]) / 2
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }


def repeat_guard(draws, window=720):
    baseline = BASE_PROBABILITY
    latest_numbers = set(draws[-1]["numbers"])
    start = max(0, len(draws) - window - 1)
    guard = {}
    for number in latest_numbers:
        sample = 0
        repeated = 0
        for idx in range(start, len(draws) - 1):
            if number in draws[idx]["numbers"]:
                sample += 1
                if number in draws[idx + 1]["numbers"]:
                    repeated += 1
        rate = repeated / sample if sample else 0.0
        historical_support = sample >= 30 and rate >= baseline * 1.18
        guard[number] = {
            "sample": sample,
            "repeat_hits": repeated,
            "repeat_rate": round(rate, 4),
            "baseline": round(baseline, 4),
            "historical_support": historical_support,
            "passed": historical_support,
            "decision": "qualified_repeat_allowed" if historical_support else "repeat_gate_failed",
        }
    return guard


def failed_number_set(review):
    if not review or review.get("severity") != "critical":
        return set()
    settled = review.get("last_settled", {})
    failed = set((settled.get("candidate_numbers") or [])[:15])
    for pack in (settled.get("strong_pack_hits") or {}).values():
        if not pack.get("passed"):
            failed.update(pack.get("numbers", []))
    failed -= set(settled.get("actual_numbers") or [])
    return {n for n in failed if NUMBER_MIN <= n <= NUMBER_MAX}


def previous_prediction_set(review, limit=15):
    if not review or not review.get("has_review"):
        return set()
    settled = review.get("last_settled", {})
    return {
        n for n in (settled.get("candidate_numbers") or [])[:limit]
        if NUMBER_MIN <= n <= NUMBER_MAX
    }


def previous_prediction_guard(number, values, review):
    if number not in previous_prediction_set(review):
        return None
    strong_conditions = [
        values.get("omission", 0) >= 0.85,
        values.get("pair", 0) >= 0.85,
        values.get("tail_zone", 0) >= 0.85,
        values.get("freq_50", 0) >= 0.85,
        values.get("freq_100", 0) >= 0.85,
        values.get("ewma_slow", 0) >= 0.85,
    ]
    recovery_conditions = [
        values.get("rank_error_correction", 0) >= 0.52,
        values.get("missed_hit_recovery", 0) >= 0.52,
        values.get("zone_coverage_recovery", 0) >= 0.56,
        values.get("cross_consensus", 0) >= 0.62,
    ]
    validated_dependency = values.get("validated_dependency", 0) >= 0.7
    strong_count = sum(strong_conditions)
    recovery_count = sum(recovery_conditions)
    passed = (
        (validated_dependency and strong_count >= 2)
        or recovery_count >= 2
        or (strong_count >= 3 and values.get("cross_consensus", 0) >= 0.58)
    )
    return {
        "passed": passed,
        "decision": "qualified_reentry_allowed" if passed else "soft_guard_previous_prediction",
        "validated_dependency": validated_dependency,
        "strong_condition_count": strong_count,
        "recovery_condition_count": recovery_count,
        "required_strong_conditions": 2,
    }


def cycle_timing_scores(omissions):
    values = {}
    for number, gap in omissions.items():
        distance = abs(gap - EXPECTED_GAP) / max(EXPECTED_GAP, 1)
        moderate_overdue = 0.16 if EXPECTED_GAP * 0.9 <= gap <= EXPECTED_GAP * 2.8 else 0.0
        extreme_penalty = 0.18 if gap > EXPECTED_GAP * 5 else 0.0
        values[number] = max(0.0, math.exp(-distance) + moderate_overdue - extreme_penalty)
    return normalize(values)


def trend_alignment_scores(ewma_fast, ewma_slow, time_series_score):
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        balanced_trend = min(ewma_fast[number], ewma_slow[number])
        values[number] = balanced_trend * 0.52 + time_series_score[number] * 0.48
    return normalize(values)


def cross_model_consensus_scores(model_scores):
    votes = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for scores in model_scores:
        ranked = rank_values(scores)
        for rank, number in enumerate(ranked[:18], 1):
            if rank <= 5:
                votes[number] += 1.0
            elif rank <= 10:
                votes[number] += 0.64
            else:
                votes[number] += 0.34
            votes[number] += max(0.0, scores.get(number, 0.0)) * 0.18
    return normalize(votes)


def bayesian_posterior_scores(draws, window=720):
    subset = draws[-window:] if len(draws) > window else draws
    counts = frequency(subset)
    draws_count = max(len(subset), 1)
    prior_strength = 24
    prior_hits = BASE_PROBABILITY * prior_strength
    posterior = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        mean = (counts.get(number, 0) + prior_hits) / (draws_count + prior_strength)
        shrink = mean / BASE_PROBABILITY if BASE_PROBABILITY else 0
        posterior[number] = max(0.0, min(2.0, shrink))
    return normalize(posterior)


def monte_carlo_stability_scores(model_scores, simulations=240):
    ranked_models = [rank_values(scores)[:15] for scores in model_scores]
    votes = Counter()
    for step in range(simulations):
        for index, ranked in enumerate(ranked_models):
            rotation = (step + index * 3) % max(len(ranked), 1)
            pool = ranked[rotation:] + ranked[:rotation]
            for rank, number in enumerate(pool[:9], 1):
                votes[number] += max(0.05, 1.0 - rank * 0.085)
    return normalize({number: votes.get(number, 0.0) for number in range(NUMBER_MIN, NUMBER_MAX + 1)})


def distribution_balance_scores(draws):
    recent = draws[-120:] if len(draws) >= 120 else draws
    zone_counts = Counter()
    tail_counts = Counter()
    for draw in recent:
        for number in draw["numbers"]:
            zone_counts[zone_label(number)] += 1
            tail_counts[number % 10] += 1
    zone_norm = normalize({label: zone_counts.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    tail_norm = normalize({tail: tail_counts.get(tail, 0) for tail in range(10)})
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        zone_pressure = 1 - zone_norm[zone_label(number)]
        tail_pressure = 1 - tail_norm[number % 10]
        values[number] = zone_pressure * 0.54 + tail_pressure * 0.46
    return normalize(values)


def regime_switch_scores(draws):
    if len(draws) < 80:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest = draw_signature(draws[-1])
    recent = [draw_signature(draw) for draw in draws[-120:]]
    sums = [item["sum"] for item in recent]
    spans = [item["span"] for item in recent]
    latest_sum_z = zscore(latest["sum"], sums)
    latest_span_z = zscore(latest["span"], spans)
    latest_odd = int(str(latest["odd_even"]).split(":")[0])
    latest_big = int(str(latest["small_big"]).split(":")[1])
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if abs(latest_sum_z) >= 1.2:
            if latest_sum_z > 0 and number <= 19:
                score += 0.32
            if latest_sum_z < 0 and number >= 20:
                score += 0.32
        else:
            score += 0.12 if 11 <= number <= 30 else 0.04
        if abs(latest_span_z) >= 1.2:
            if latest_span_z > 0 and 11 <= number <= 30:
                score += 0.22
            if latest_span_z < 0 and (number <= 10 or number >= 31):
                score += 0.22
        if latest_odd >= 4 and number % 2 == 0:
            score += 0.20
        elif latest_odd <= 1 and number % 2 == 1:
            score += 0.20
        if latest_big >= 4 and number <= 19:
            score += 0.18
        elif latest_big <= 1 and number >= 20:
            score += 0.18
        values[number] = score
    return normalize(values)


def zone_coverage_recovery_scores(draws, review=None):
    rolling = ((review or {}).get("rolling_adjustment") or {})
    missed_zones = {
        str(item.get("zone")): int(item.get("missed_count", 0))
        for item in rolling.get("missed_actual_zones", [])
        if item.get("zone")
    }
    recent = draws[-30:] if len(draws) >= 30 else draws
    recent_zone_counts = Counter()
    for draw in recent:
        for number in draw["numbers"]:
            recent_zone_counts[zone_label(number)] += 1
    zone_pressure = {}
    for label in ["01-10", "11-20", "21-30", "31-39"]:
        zone_pressure[label] = missed_zones.get(label, 0) * 0.7 - recent_zone_counts.get(label, 0) * 0.08
    zone_norm = normalize(zone_pressure)
    return normalize({number: zone_norm[zone_label(number)] for number in range(NUMBER_MIN, NUMBER_MAX + 1)})


def draw_profile(numbers):
    ordered = sorted(numbers)
    zones = Counter(zone_label(number) for number in ordered)
    return {
        "odd": sum(number % 2 for number in ordered),
        "big": sum(1 for number in ordered if number >= 20),
        "zones": [zones.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]],
        "sum_bucket": sum(ordered) // 12,
        "span_bucket": (ordered[-1] - ordered[0]) // 5,
        "tail_diversity": len({number % 10 for number in ordered}),
    }


def profile_similarity(left, right):
    zone_gap = sum(abs(a - b) for a, b in zip(left["zones"], right["zones"])) / 10
    gap = (
        abs(left["odd"] - right["odd"]) / 5 * 0.20
        + abs(left["big"] - right["big"]) / 5 * 0.18
        + zone_gap * 0.26
        + abs(left["sum_bucket"] - right["sum_bucket"]) / 16 * 0.18
        + abs(left["span_bucket"] - right["span_bucket"]) / 8 * 0.12
        + abs(left["tail_diversity"] - right["tail_diversity"]) / 5 * 0.06
    )
    return max(0.0, 1.0 - gap)


def shape_follow_scores(draws, lookback=1500):
    if len(draws) < 80:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_profile = draw_profile(draws[-1]["numbers"])
    values = Counter()
    start = max(0, len(draws) - lookback - 1)
    for idx in range(start, len(draws) - 1):
        similarity = profile_similarity(draw_profile(draws[idx]["numbers"]), latest_profile)
        if similarity < 0.52:
            continue
        weight = similarity ** 2
        for number in draws[idx + 1]["numbers"]:
            values[number] += weight
    return normalize({n: values.get(n, 0.0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})


def zone_parity_pressure_scores(draws, lookback=720):
    if len(draws) < 80:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_profile = draw_profile(draws[-1]["numbers"])
    zone_votes = Counter()
    parity_votes = Counter()
    start = max(0, len(draws) - lookback - 1)
    for idx in range(start, len(draws) - 1):
        similarity = profile_similarity(draw_profile(draws[idx]["numbers"]), latest_profile)
        if similarity < 0.48:
            continue
        for number in draws[idx + 1]["numbers"]:
            zone_votes[zone_label(number)] += similarity
            parity_votes[number % 2] += similarity
    zone_norm = normalize({label: zone_votes.get(label, 0.0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    parity_norm = normalize({parity: parity_votes.get(parity, 0.0) for parity in [0, 1]})
    return normalize({
        number: zone_norm[zone_label(number)] * 0.58 + parity_norm[number % 2] * 0.42
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    })


def missed_hit_recovery_scores(review):
    if not review or not review.get("has_review"):
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    settled = review.get("last_settled", {})
    actual = set(settled.get("actual_numbers") or [])
    predicted = set((settled.get("candidate_numbers") or [])[:15])
    missed_actual = {n for n in actual - predicted if NUMBER_MIN <= n <= NUMBER_MAX}
    if not missed_actual:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    values = {}
    missed_tails = {n % 10 for n in missed_actual}
    missed_zones = {zone_label(n) for n in missed_actual}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if number % 10 in missed_tails:
            score += 0.42
        if zone_label(number) in missed_zones:
            score += 0.34
        if any(1 <= abs(number - anchor) <= 2 for anchor in missed_actual):
            score += 0.24
        values[number] = score
    return normalize(values)


def rank_error_correction_scores(review):
    if not review or not review.get("has_review"):
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    rolling = review.get("rolling_adjustment", {})
    late_hits = {
        int(item.get("number")): int(item.get("late_hit_count", 0))
        for item in rolling.get("late_hit_numbers", [])
        if item.get("number")
    }
    repeated_misses = {
        int(item.get("number")): int(item.get("miss_count", 0))
        for item in rolling.get("repeated_failed_numbers", [])
        if item.get("number")
    }
    missed_actual = {
        int(item.get("number")): int(item.get("missed_count", 0))
        for item in rolling.get("missed_actual_numbers", [])
        if item.get("number")
    }
    missed_actual_tails = {
        int(item.get("tail")): int(item.get("missed_count", 0))
        for item in rolling.get("missed_actual_tails", [])
        if item.get("tail") is not None
    }
    missed_actual_zones = {
        str(item.get("zone")): int(item.get("missed_count", 0))
        for item in rolling.get("missed_actual_zones", [])
        if item.get("zone")
    }
    monthly_recall = {
        int(item.get("number")): int(item.get("missed_count", 0))
        for item in rolling.get("monthly_recall_numbers", [])
        if item.get("number")
    }
    monthly_tails = {
        int(item.get("tail")): int(item.get("missed_count", 0))
        for item in rolling.get("monthly_recall_tails", [])
        if item.get("tail") is not None
    }
    monthly_zones = {
        str(item.get("zone")): int(item.get("missed_count", 0))
        for item in rolling.get("monthly_recall_zones", [])
        if item.get("zone")
    }
    recent = rolling.get("recent_performance", {})
    slump_multiplier = 1.35 if recent.get("critical_slump") else 1.18 if recent.get("recent_slump") else 1.0
    settled = review.get("last_settled", {})
    actual = {int(n) for n in settled.get("actual_numbers", []) if NUMBER_MIN <= int(n) <= NUMBER_MAX}
    top10 = {
        int(n)
        for n in (settled.get("candidate_numbers") or [])[:10]
        if NUMBER_MIN <= int(n) <= NUMBER_MAX
    }
    last_top10_misses = actual - top10
    late_tails = {number % 10 for number in late_hits}
    late_zones = {zone_label(number) for number in late_hits}
    missed_tails = {number % 10 for number in last_top10_misses}
    missed_zones = {zone_label(number) for number in last_top10_misses}
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if number in late_hits:
            score += min(1.0, late_hits[number] / 5) * 0.85
        if number in missed_actual:
            score += min(1.0, missed_actual[number] / 5) * 0.72
        if number in monthly_recall:
            score += min(1.0, monthly_recall[number] / 4) * 0.54
        if number in last_top10_misses:
            score += 0.42
        if number % 10 in late_tails:
            score += 0.16
        if zone_label(number) in late_zones:
            score += 0.12
        if number % 10 in missed_tails:
            score += 0.18
        if zone_label(number) in missed_zones:
            score += 0.12
        if number % 10 in missed_actual_tails:
            score += min(0.32, missed_actual_tails[number % 10] * 0.055)
        if zone_label(number) in missed_actual_zones:
            score += min(0.24, missed_actual_zones[zone_label(number)] * 0.035)
        if number % 10 in monthly_tails:
            score += min(0.22, monthly_tails[number % 10] * 0.032)
        if zone_label(number) in monthly_zones:
            score += min(0.18, monthly_zones[zone_label(number)] * 0.026)
        if any(1 <= abs(number - anchor) <= 2 for anchor in late_hits):
            score += 0.14
        if any(1 <= abs(number - anchor) <= 2 for anchor in missed_actual):
            score += 0.14
        if any(1 <= abs(number - anchor) <= 2 for anchor in last_top10_misses):
            score += 0.12
        if number in repeated_misses:
            score -= min(0.72, repeated_misses[number] * 0.16)
        values[number] = score * slump_multiplier
    return normalize(values)


def slump_mode(review):
    recent = ((review or {}).get("rolling_adjustment") or {}).get("recent_performance", {})
    if recent.get("critical_slump"):
        return "critical"
    if recent.get("recent_slump"):
        return "warning"
    return "normal"


def build_feature_matrix(draws, review=None, include_dependency=True):
    windows = [5, 10, 20, 50, 100, 300]
    feature_scores = {n: defaultdict(float) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    window_scores = {}

    for window in windows:
        subset = draws[-window:] if len(draws) >= window else draws
        freq = frequency(subset)
        zscores = {n: binomial_zscore(freq.get(n, 0), len(subset)) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
        normalized = normalize(zscores)
        window_scores[window] = normalized
        for number, value in normalized.items():
            feature_scores[number][f"freq_{window}"] = value

    ewma_fast = normalize(ewma_frequency(draws[-160:], 16))
    ewma_slow = normalize(ewma_frequency(draws[-360:], 60))
    omissions = omission(draws)
    omission_score = normalize({n: math.log1p(omissions[n]) / math.log1p(EXPECTED_GAP * 4) for n in omissions})
    transition_score, _ = transition_scores(draws)
    dependency_score = validated_dependency_scores(draws)[0] if include_dependency else {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    markov_score = markov_chain_scores(draws)
    time_series_score = time_series_scores(draws)
    neural_score = neural_network_scores(draws)
    pair_score = pair_scores(draws)
    tail_zone = tail_zone_scores(draws)
    cycle_timing = cycle_timing_scores(omissions)
    trend_alignment = trend_alignment_scores(ewma_fast, ewma_slow, time_series_score)
    bayesian_posterior = bayesian_posterior_scores(draws)
    distribution_balance = distribution_balance_scores(draws)
    shape_follow = shape_follow_scores(draws)
    zone_parity_pressure = zone_parity_pressure_scores(draws)
    missed_hit_recovery = missed_hit_recovery_scores(review)
    rank_error_correction = rank_error_correction_scores(review)
    regime_switch = regime_switch_scores(draws)
    zone_coverage_recovery = zone_coverage_recovery_scores(draws, review)
    cross_consensus = cross_model_consensus_scores([
        window_scores[20],
        window_scores[50],
        window_scores[100],
        omission_score,
        transition_score,
        dependency_score,
        markov_score,
        time_series_score,
        neural_score,
        pair_score,
        tail_zone,
        cycle_timing,
        trend_alignment,
        bayesian_posterior,
        distribution_balance,
        shape_follow,
        zone_parity_pressure,
        missed_hit_recovery,
        rank_error_correction,
        regime_switch,
        zone_coverage_recovery,
    ])
    monte_carlo_stability = monte_carlo_stability_scores([
        cross_consensus,
        markov_score,
        time_series_score,
        neural_score,
        pair_score,
        bayesian_posterior,
        distribution_balance,
        shape_follow,
        zone_parity_pressure,
        rank_error_correction,
        regime_switch,
        zone_coverage_recovery,
    ])
    next_date = next_draw_date(draws[-1]["draw_date"])
    date_set = set(date_numbers(next_date))
    date_score = {n: (1.0 if n in date_set else 0.0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_set = set(draws[-1]["numbers"])

    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        feature_scores[number]["ewma_fast"] = ewma_fast[number]
        feature_scores[number]["ewma_slow"] = ewma_slow[number]
        feature_scores[number]["omission"] = omission_score[number]
        feature_scores[number]["transition"] = transition_score[number]
        feature_scores[number]["validated_dependency"] = dependency_score[number]
        feature_scores[number]["markov_chain"] = markov_score[number]
        feature_scores[number]["time_series"] = time_series_score[number]
        feature_scores[number]["neural_network"] = neural_score[number]
        feature_scores[number]["pair"] = pair_score[number]
        feature_scores[number]["tail_zone"] = tail_zone[number]
        feature_scores[number]["cycle_timing"] = cycle_timing[number]
        feature_scores[number]["trend_alignment"] = trend_alignment[number]
        feature_scores[number]["cross_consensus"] = cross_consensus[number]
        feature_scores[number]["bayesian_posterior"] = bayesian_posterior[number]
        feature_scores[number]["monte_carlo_stability"] = monte_carlo_stability[number]
        feature_scores[number]["distribution_balance"] = distribution_balance[number]
        feature_scores[number]["shape_follow"] = shape_follow[number]
        feature_scores[number]["zone_parity_pressure"] = zone_parity_pressure[number]
        feature_scores[number]["missed_hit_recovery"] = missed_hit_recovery[number]
        feature_scores[number]["rank_error_correction"] = rank_error_correction[number]
        feature_scores[number]["regime_switch"] = regime_switch[number]
        feature_scores[number]["zone_coverage_recovery"] = zone_coverage_recovery[number]
        feature_scores[number]["date"] = date_score[number]
        feature_scores[number]["repeat"] = 1.0 if number in latest_set else 0.0
        feature_scores[number]["neighbor"] = 1.0 if any(abs(number - anchor) == 1 for anchor in latest_set) else 0.0

    return feature_scores


def industrial_weights(review=None):
    weights = {
        "freq_5": 0.025,
        "freq_10": 0.045,
        "freq_20": 0.078,
        "freq_50": 0.112,
        "freq_100": 0.118,
        "freq_300": 0.055,
        "ewma_fast": 0.052,
        "ewma_slow": 0.072,
        "omission": 0.112,
        "transition": 0.064,
        "validated_dependency": 0.062,
        "markov_chain": 0.055,
        "time_series": 0.044,
        "neural_network": 0.052,
        "pair": 0.082,
        "tail_zone": 0.078,
        "cycle_timing": 0.052,
        "trend_alignment": 0.058,
        "cross_consensus": 0.098,
        "bayesian_posterior": 0.052,
        "monte_carlo_stability": 0.064,
        "distribution_balance": 0.046,
        "shape_follow": 0.072,
        "zone_parity_pressure": 0.062,
        "missed_hit_recovery": 0.054,
        "rank_error_correction": 0.075,
        "regime_switch": 0.052,
        "zone_coverage_recovery": 0.058,
        "date": 0.025,
        "repeat": 0.015,
        "neighbor": 0.025,
    }
    if review and review.get("severity") == "critical":
        weights.update(
            {
                "freq_5": 0.01,
                "freq_10": 0.02,
                "freq_20": 0.06,
                "transition": 0.045,
                "markov_chain": 0.04,
                "time_series": 0.04,
                "neural_network": 0.045,
                "cross_consensus": 0.135,
                "cycle_timing": 0.066,
                "trend_alignment": 0.07,
                "bayesian_posterior": 0.064,
                "monte_carlo_stability": 0.078,
                "distribution_balance": 0.055,
                "shape_follow": 0.096,
                "zone_parity_pressure": 0.082,
                "missed_hit_recovery": 0.074,
                "rank_error_correction": 0.105,
                "regime_switch": 0.074,
                "zone_coverage_recovery": 0.088,
                "repeat": 0.005,
                "neighbor": 0.01,
                "freq_50": 0.15,
                "freq_100": 0.145,
                "omission": 0.16,
                "tail_zone": 0.115,
                "pair": 0.11,
            }
        )
    mode = slump_mode(review)
    if mode in {"warning", "critical"}:
        intensity = 1.0 if mode == "warning" else 1.35
        for key in ["freq_5", "freq_10", "date", "repeat", "time_series", "neural_network", "tail_zone"]:
            if key in weights:
                weights[key] *= 0.74 if mode == "warning" else 0.58
        for key in [
            "rank_error_correction",
            "missed_hit_recovery",
            "omission",
            "bayesian_posterior",
            "validated_dependency",
            "distribution_balance",
            "regime_switch",
            "zone_coverage_recovery",
            "cycle_timing",
            "pair",
        ]:
            if key in weights:
                weights[key] *= 1.0 + 0.34 * intensity
    total = sum(weights.values()) or 1
    return {key: value / total for key, value in weights.items()}


MODEL_SOURCE_LABELS = {
    "freq_5": "\u8fd15\u671f\u71b1\u5ea6",
    "freq_10": "\u8fd110\u671f\u71b1\u5ea6",
    "freq_20": "\u8fd120\u671f\u71b1\u5ea6",
    "freq_50": "\u8fd150\u671f\u71b1\u5ea6",
    "freq_100": "\u8fd1100\u671f\u71b1\u5ea6",
    "freq_300": "\u8fd1300\u671f\u7a69\u5b9a",
    "ewma_fast": "\u5feb\u901f\u52a0\u6b0a\u8da8\u52e2",
    "ewma_slow": "\u6162\u901f\u52a0\u6b0a\u8da8\u52e2",
    "omission": "\u907a\u6f0f\u9031\u671f",
    "transition": "\u62d6\u724c\u8f49\u79fb",
    "validated_dependency": "\u6a23\u672c\u5916\u9023\u52d5",
    "markov_chain": "\u99ac\u53ef\u592b",
    "time_series": "\u6642\u9593\u5e8f\u5217",
    "neural_network": "\u795e\u7d93\u7db2\u8def",
    "pair": "\u5171\u73fe\u914d\u5c0d",
    "tail_zone": "\u5c3e\u6578\u5340\u9593",
    "cycle_timing": "\u9031\u671f\u4f4d\u7f6e",
    "trend_alignment": "\u5feb\u6162\u8da8\u52e2\u4e00\u81f4",
    "cross_consensus": "\u591a\u6a21\u578b\u5171\u8b58",
    "bayesian_posterior": "\u8c9d\u6c0f\u4fdd\u5b88\u6821\u6e96",
    "monte_carlo_stability": "\u8499\u5730\u5361\u7f85\u7a69\u5b9a",
    "distribution_balance": "\u5206\u5e03\u5e73\u8861",
    "shape_follow": "\u724c\u578b\u76f8\u4f3c\u8ddf\u96a8",
    "zone_parity_pressure": "\u5340\u9593\u5947\u5076\u58d3\u529b",
    "missed_hit_recovery": "\u6f0f\u547d\u4e2d\u56de\u6536",
    "rank_error_correction": "\u6392\u540d\u932f\u4f4d\u4fee\u6b63",
    "regime_switch": "\u958b\u734e\u578b\u614b\u5207\u63db",
    "zone_coverage_recovery": "\u5206\u5340\u8986\u84cb\u56de\u88dc",
    "date": "\u65e5\u671f\u724c",
    "repeat": "\u9023\u838a\u56de\u6e2c",
    "neighbor": "\u9130\u865f\u9023\u52d5",
}


def conservative_probability_percent(score, rank=None):
    baseline_percent = BASE_PROBABILITY * 100
    calibrated = baseline_percent * (0.72 + max(0.0, min(score, 1.0)) * 0.74)
    if rank is not None and rank > 9:
        calibrated *= 0.72 if rank <= 15 else 0.58
    return round(max(0.0, min(38.0, calibrated)), 2)


def number_model_sources(values, weights, limit=8):
    rows = []
    for name, weight in weights.items():
        value = values.get(name, 0.0)
        contribution = value * weight
        if value >= 0.42 or contribution >= 0.018:
            rows.append({
                "model": name,
                "label": MODEL_SOURCE_LABELS.get(name, name),
                "signal": round(value, 4),
                "weight": round(weight, 5),
                "contribution": round(contribution, 5),
            })
    rows.sort(key=lambda item: (item["contribution"], item["signal"]), reverse=True)
    return rows[:limit]


def number_cross_validation(values):
    checks = [
        ("multi_model_consensus", "\u591a\u6a21\u578b\u5171\u8b58", values.get("cross_consensus", 0) >= 0.58),
        ("monte_carlo_stability", "\u8499\u5730\u5361\u7f85\u7a69\u5b9a", values.get("monte_carlo_stability", 0) >= 0.58),
        ("bayesian_calibration", "\u8c9d\u6c0f\u6821\u6e96", values.get("bayesian_posterior", 0) >= 0.52),
        ("trend_alignment", "\u8da8\u52e2\u4e00\u81f4", values.get("trend_alignment", 0) >= 0.52),
        ("cycle_timing", "\u9031\u671f\u4f4d\u7f6e", values.get("cycle_timing", 0) >= 0.52),
        ("distribution_balance", "\u5206\u5e03\u5e73\u8861", values.get("distribution_balance", 0) >= 0.52),
        ("shape_follow", "\u724c\u578b\u76f8\u4f3c\u8ddf\u96a8", values.get("shape_follow", 0) >= 0.52),
        ("zone_parity_pressure", "\u5340\u9593\u5947\u5076\u58d3\u529b", values.get("zone_parity_pressure", 0) >= 0.52),
        ("missed_hit_recovery", "\u6f0f\u547d\u4e2d\u56de\u6536", values.get("missed_hit_recovery", 0) >= 0.52),
        ("rank_error_correction", "\u6392\u540d\u932f\u4f4d\u4fee\u6b63", values.get("rank_error_correction", 0) >= 0.52),
        ("regime_switch", "\u958b\u734e\u578b\u614b\u5207\u63db", values.get("regime_switch", 0) >= 0.52),
        ("zone_coverage_recovery", "\u5206\u5340\u8986\u84cb\u56de\u88dc", values.get("zone_coverage_recovery", 0) >= 0.52),
    ]
    passed = [{"key": key, "label": label} for key, label, ok in checks if ok]
    failed = [{"key": key, "label": label} for key, label, ok in checks if not ok]
    return {
        "passed_count": len(passed),
        "total_count": len(checks),
        "passed": passed,
        "failed": failed,
        "status": "passed" if len(passed) >= 4 else "watch",
    }


def confidence_profile(score, confidence, probability, model_sources, cross_validation, rank):
    source_count = len(model_sources)
    passed_count = int(cross_validation.get("passed_count") or 0)
    total_count = int(cross_validation.get("total_count") or 0)
    ratio = (passed_count / total_count) if total_count else 0

    if score >= 0.92 and confidence >= 95 and probability >= 17.0 and source_count >= 6 and passed_count >= 6 and rank <= 5:
        return {
            "level": "very_high",
            "label": "\u672c\u65e5\u9ad8\u6a5f\u7387\u5f37\u8abf",
            "badges": ["\u672c\u65e5\u9ad8\u6a5f\u7387", "\u9ad8\u4fe1\u5fc3", "\u591a\u6a21\u578b\u5171\u632f"],
            "is_high_confidence": True,
            "risk_note": "\u5206\u6578\u3001\u6a5f\u7387\u3001\u4fe1\u5fc3\u3001\u4f86\u6e90\u6a21\u578b\u8207\u4ea4\u53c9\u9a57\u8b49\u540c\u6642\u9054\u6a19",
        }
    if score >= 0.84 and confidence >= 91 and probability >= 16.0 and source_count >= 5 and passed_count >= 5 and rank <= 9:
        return {
            "level": "high",
            "label": "\u9ad8\u4fe1\u5fc3\u95dc\u6ce8",
            "badges": ["\u9ad8\u4fe1\u5fc3", "\u4ea4\u53c9\u9a57\u8b49\u901a\u904e"],
            "is_high_confidence": True,
            "risk_note": "\u689d\u4ef6\u9054\u5230\u4e3b\u63a8\u89c0\u5bdf\uff0c\u4f46\u672a\u9054\u672c\u65e5\u9ad8\u6a5f\u7387\u5f37\u8abf\u7d1a",
        }
    if score >= 0.76 and confidence >= 87 and probability >= 15.0 and source_count >= 4 and ratio >= 0.33 and rank <= 15:
        return {
            "level": "watch",
            "label": "\u5f37\u70c8\u95dc\u6ce8",
            "badges": ["\u5f37\u70c8\u95dc\u6ce8"],
            "is_high_confidence": False,
            "risk_note": "\u90e8\u5206\u689d\u4ef6\u9054\u6a19\uff0c\u9700\u8207\u5206\u5340\u8207\u724c\u578b\u98a8\u63a7\u4e00\u8d77\u89c0\u5bdf",
        }
    return {
        "level": "normal",
        "label": "\u4e00\u822c\u89c0\u5bdf",
        "badges": [],
        "is_high_confidence": False,
        "risk_note": "\u672a\u9054\u9ad8\u4fe1\u5fc3\u6a19\u8a18\u9580\u6abb",
    }


def _count_map(rows, key_name="number", value_name="miss_count"):
    result = {}
    for row in rows or []:
        value = row.get(key_name)
        if value is None:
            continue
        try:
            result[int(value)] = int(row.get(value_name, 0) or 0)
        except (TypeError, ValueError):
            continue
    return result


def _string_set(rows, key_name):
    return {
        str(row.get(key_name))
        for row in rows or []
        if row.get(key_name) is not None
    }


def _label_count_map(rows, key_name, value_name):
    result = {}
    for row in rows or []:
        value = row.get(key_name)
        if value is None:
            continue
        try:
            result[str(value)] = int(row.get(value_name, 0) or 0)
        except (TypeError, ValueError):
            continue
    return result


def live_precision_calibration(candidates, review=None):
    rolling = (review or {}).get("rolling_adjustment", {})
    recent = rolling.get("recent_performance", {})
    mode = slump_mode(review)
    late_hits = _count_map(rolling.get("late_hit_numbers", []), "number", "late_hit_count")
    missed_actual = _count_map(rolling.get("missed_actual_numbers", []), "number", "missed_count")
    repeated_failed = _count_map(rolling.get("repeated_failed_numbers", []), "number", "miss_count")
    repeated_failed_numbers = {int(number) for number in repeated_failed}
    missed_tails = _count_map(rolling.get("missed_actual_tails", []), "tail", "missed_count")
    missed_zones = _label_count_map(rolling.get("missed_actual_zones", []), "zone", "missed_count")
    monthly_recall = _count_map(rolling.get("monthly_recall_numbers", []), "number", "missed_count")
    monthly_tails = _count_map(rolling.get("monthly_recall_tails", []), "tail", "missed_count")
    monthly_zones = _label_count_map(rolling.get("monthly_recall_zones", []), "zone", "missed_count")
    boosted_reasons = _string_set(rolling.get("boosted_reasons", []), "reason")
    penalized_reasons = _string_set(rolling.get("penalized_reasons", []), "reason")
    slump_intensity = 1.0 if mode == "warning" else 1.35 if mode == "critical" else 0.65
    recent_top5 = recent.get("last5_top5_avg", 1.0) or 0
    recent_top10 = recent.get("last5_top10_avg", 1.8) or 0
    top5_slump = recent_top5 < 0.85
    top10_slump = recent_top10 < 1.75
    calibrated = []
    promotions = []
    demotions = []

    for original_rank, item in enumerate(candidates, 1):
        row = dict(item)
        number = int(row["number"])
        base_score = float(row.get("score", 0) or 0)
        reasons = set(str(reason) for reason in row.get("reasons", []))
        model_names = {source.get("model") for source in row.get("model_sources", [])}
        cross = row.get("cross_validation", {})
        passed = int(cross.get("passed_count") or 0)
        total = int(cross.get("total_count") or 0) or 1
        stability = int(row.get("stability_count", 0) or 0)
        guard = row.get("previous_prediction_guard")
        repeat_info = row.get("repeat_guard")

        adjustment = 0.0
        tags = []

        if top5_slump and original_rank <= 5 and stability < 5 and passed < 8:
            adjustment -= 0.055 * slump_intensity
            tags.append("recent_top5_slump_penalty")
        if top5_slump and original_rank <= 3 and number not in late_hits and number not in missed_actual and number not in monthly_recall:
            adjustment -= 0.022 * slump_intensity
            tags.append("front_rank_overconfidence_penalty")
        if top10_slump and 6 <= original_rank <= 20:
            boundary_factor = 1.0 if original_rank <= 15 else 0.72
            adjustment += 0.024 * boundary_factor * slump_intensity
            tags.append("top10_boundary_recovery")
        if 11 <= original_rank <= 25 and (
            number not in repeated_failed_numbers or number in monthly_recall or number in missed_actual
        ) and (number in late_hits or number in missed_actual or number in monthly_recall or stability >= 4):
            depth_factor = 1.0 if original_rank <= 15 else 0.68
            adjustment += 0.064 * depth_factor * slump_intensity
            tags.append("late_band_front_pull")

        if number in late_hits:
            adjustment += min(0.135, 0.028 * late_hits[number]) * slump_intensity
            tags.append("late_hit_number_recovered")
        if number in missed_actual:
            adjustment += min(0.145, 0.026 * missed_actual[number]) * slump_intensity
            tags.append("missed_actual_number_recovered")
        if number in monthly_recall:
            adjustment += min(0.118, 0.022 * monthly_recall[number]) * slump_intensity
            tags.append("monthly_recall_number_recovered")
        if number % 10 in missed_tails:
            adjustment += min(0.040, 0.006 * missed_tails[number % 10]) * slump_intensity
            tags.append("missed_tail_recovered")
        if zone_label(number) in missed_zones:
            adjustment += min(0.034, 0.004 * missed_zones[zone_label(number)]) * slump_intensity
            tags.append("missed_zone_recovered")
        if number % 10 in monthly_tails:
            adjustment += min(0.030, 0.004 * monthly_tails[number % 10]) * slump_intensity
            tags.append("monthly_tail_recovered")
        if zone_label(number) in monthly_zones:
            adjustment += min(0.026, 0.0035 * monthly_zones[zone_label(number)]) * slump_intensity
            tags.append("monthly_zone_recovered")

        if number in repeated_failed:
            if number in late_hits or number in missed_actual or number in monthly_recall:
                adjustment -= min(0.110, 0.014 * repeated_failed[number]) * (1.10 if top10_slump else 0.92)
                tags.append("repeated_failed_softened_by_recovery")
            else:
                adjustment -= min(0.245, 0.032 * repeated_failed[number]) * (1.22 if top10_slump else 1.0)
                tags.append("repeated_failed_number_penalty")
            if original_rank <= 10:
                adjustment -= 0.030 * slump_intensity
                tags.append("failed_number_top10_escape")
        if guard and not guard.get("passed"):
            recovery_count = int(guard.get("recovery_condition_count") or 0)
            strong_count = int(guard.get("strong_condition_count") or 0)
            if recovery_count >= 1 or strong_count >= 2 or number in late_hits or number in missed_actual:
                adjustment -= 0.022
                tags.append("previous_prediction_soft_guard")
            else:
                adjustment -= 0.060
                tags.append("previous_prediction_reentry_blocked")
        if repeat_info and not repeat_info.get("passed"):
            adjustment -= 0.115
            tags.append("repeat_gate_blocked")

        if reasons & boosted_reasons:
            adjustment += 0.024 * slump_intensity
            tags.append("winning_source_boost")
        if reasons & penalized_reasons and not (reasons & boosted_reasons):
            adjustment -= 0.022 * slump_intensity
            tags.append("losing_source_penalty")

        if {"pair", "rank_error_correction", "missed_hit_recovery"} & model_names:
            adjustment += 0.028 if mode != "normal" else 0.014
            tags.append("practical_model_support")
        if {"date", "time_series"} <= model_names and passed < 5:
            adjustment -= 0.018
            tags.append("weak_short_signal_penalty")

        adjustment += min(stability, 5) * 0.006
        adjustment += max(0.0, (passed / total) - 0.45) * 0.040

        calibrated_score = max(0.0, min(1.0, base_score + adjustment))
        row["pre_calibration_rank"] = original_rank
        row["pre_calibration_score"] = round(base_score, 4)
        row["precision_calibration"] = {
            "mode": mode,
            "adjustment": round(adjustment, 4),
            "tags": tags[:8],
            "recent_top5_avg": recent_top5,
            "recent_top10_avg": recent_top10,
        }
        row["score"] = round(calibrated_score, 4)
        row["confidence_index"] = round(50 + calibrated_score * 49, 1)
        if adjustment >= 0.05:
            row["reasons"] = (row.get("reasons", []) + ["\u5be6\u6230\u6821\u6e96\u5347\u6b0a"])[:4]
            promotions.append({
                "number": number,
                "from_rank": original_rank,
                "adjustment": round(adjustment, 4),
                "tags": tags[:6],
            })
        elif adjustment <= -0.05:
            row["reasons"] = (row.get("reasons", []) + ["\u5be6\u6230\u6821\u6e96\u964d\u6b0a"])[:4]
            demotions.append({
                "number": number,
                "from_rank": original_rank,
                "adjustment": round(adjustment, 4),
                "tags": tags[:6],
            })
        calibrated.append(row)

    calibrated.sort(
        key=lambda row: (
            row.get("score", 0),
            row.get("stability_count", 0),
            row.get("cross_validation", {}).get("passed_count", 0),
            -row["number"],
        ),
        reverse=True,
    )
    for rank, row in enumerate(calibrated, 1):
        row["rank"] = rank
        probability_value = conservative_probability_percent(row["score"], rank)
        row["model_probability_percent"] = probability_value
        confidence = confidence_profile(
            row["score"],
            row["confidence_index"],
            probability_value,
            row.get("model_sources", []),
            row.get("cross_validation", {}),
            rank,
        )
        row["confidence_profile"] = confidence
        row["confidence_badges"] = confidence["badges"]
        row["confidence_level"] = confidence["level"]
        row["confidence_label"] = confidence["label"]
        row["high_confidence"] = confidence["is_high_confidence"]

    return calibrated, {
        "status": "evaluated",
        "method": "settled_prediction_live_precision_calibration",
        "mode": mode,
        "recent_top5_avg": recent_top5,
        "recent_top10_avg": recent_top10,
        "top5_slump": top5_slump,
        "top10_slump": top10_slump,
        "promotion_count": len(promotions),
        "demotion_count": len(demotions),
        "promotions": promotions[:12],
        "demotions": demotions[:12],
    }


def _posterior_rate(hits, exposure, prior_strength=24):
    prior_hits = BASE_PROBABILITY * prior_strength
    return (hits + prior_hits) / (exposure + prior_strength) if exposure + prior_strength else BASE_PROBABILITY


def fast_hit_through_candidates(train):
    windows = [5, 10, 20, 50, 100]
    latest_numbers = set(train[-1]["numbers"])
    latest_tails = Counter(number % 10 for number in latest_numbers)
    latest_zones = Counter(zone_label(number) for number in latest_numbers)
    recent_counts = {}
    for window in windows:
        counter = Counter()
        for draw in train[-window:]:
            counter.update(draw["numbers"])
        recent_counts[window] = counter
    rows = []
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        omission_count = 120
        for offset, draw in enumerate(reversed(train[-140:]), 0):
            if number in draw["numbers"]:
                omission_count = offset
                break
        score = (
            recent_counts[5][number] * 0.095
            + recent_counts[10][number] * 0.070
            + recent_counts[20][number] * 0.046
            + recent_counts[50][number] * 0.021
            + recent_counts[100][number] * 0.010
            + min(1.0, math.log1p(omission_count) / math.log1p(120)) * 0.105
            + latest_tails.get(number % 10, 0) * 0.035
            + latest_zones.get(zone_label(number), 0) * 0.025
            + (0.052 if any(abs(number - anchor) == 1 for anchor in latest_numbers) else 0.0)
            + (0.028 if any(abs(number - anchor) == 2 for anchor in latest_numbers) else 0.0)
            - (0.035 if number in latest_numbers else 0.0)
        )
        rows.append({"number": number, "score": round(score, 6)})
    rows.sort(key=lambda row: (row["score"], -row["number"]), reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def historical_hit_through_table(draws, rounds=220):
    if len(draws) < 180:
        return {
            "status": "insufficient_data",
            "rounds": 0,
            "numbers": {},
            "rank_bands": {},
        }
    start = max(140, len(draws) - rounds - 1)
    number_stats = {
        number: {
            "top5_exposure": 0,
            "top5_hits": 0,
            "top10_exposure": 0,
            "top10_hits": 0,
            "top15_exposure": 0,
            "top15_hits": 0,
        }
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }
    rank_bands = {
        "1-5": {"exposure": 0, "hits": 0},
        "6-10": {"exposure": 0, "hits": 0},
        "11-15": {"exposure": 0, "hits": 0},
    }
    total = 0

    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        historical_candidates = fast_hit_through_candidates(train)
        for rank, item in enumerate(historical_candidates[:15], 1):
            number = item["number"]
            hit = 1 if number in actual else 0
            if rank <= 5:
                number_stats[number]["top5_exposure"] += 1
                number_stats[number]["top5_hits"] += hit
                rank_bands["1-5"]["exposure"] += 1
                rank_bands["1-5"]["hits"] += hit
            if rank <= 10:
                number_stats[number]["top10_exposure"] += 1
                number_stats[number]["top10_hits"] += hit
            if rank <= 15:
                number_stats[number]["top15_exposure"] += 1
                number_stats[number]["top15_hits"] += hit
            if 6 <= rank <= 10:
                rank_bands["6-10"]["exposure"] += 1
                rank_bands["6-10"]["hits"] += hit
            elif 11 <= rank <= 15:
                rank_bands["11-15"]["exposure"] += 1
                rank_bands["11-15"]["hits"] += hit
        total += 1

    calibrated_numbers = {}
    for number, stat in number_stats.items():
        top5_rate = _posterior_rate(stat["top5_hits"], stat["top5_exposure"])
        top10_rate = _posterior_rate(stat["top10_hits"], stat["top10_exposure"])
        top15_rate = _posterior_rate(stat["top15_hits"], stat["top15_exposure"])
        blended = top5_rate * 0.42 + top10_rate * 0.38 + top15_rate * 0.20
        calibrated_numbers[number] = {
            **stat,
            "top5_posterior_rate": round(top5_rate, 4),
            "top10_posterior_rate": round(top10_rate, 4),
            "top15_posterior_rate": round(top15_rate, 4),
            "posterior_hit_rate": round(blended, 4),
            "edge_vs_baseline": round(blended - BASE_PROBABILITY, 4),
        }

    band_report = {}
    for band, stat in rank_bands.items():
        exposure = stat["exposure"]
        rate = stat["hits"] / exposure if exposure else 0.0
        band_report[band] = {
            **stat,
            "hit_rate": round(rate, 4),
            "edge_vs_baseline": round(rate - BASE_PROBABILITY, 4),
        }

    return {
        "status": "evaluated",
        "rounds": total,
        "method": "fast_number_level_hit_through_walk_forward",
        "baseline_probability": round(BASE_PROBABILITY, 4),
        "numbers": calibrated_numbers,
        "rank_bands": band_report,
    }


def apply_hit_through_calibration(draws, candidates, review=None, rounds=120):
    table = historical_hit_through_table(draws, rounds=min(rounds, 120))
    if table.get("status") != "evaluated":
        return candidates, table
    mode = slump_mode(review)
    intensity = 1.28 if mode == "critical" else 1.12 if mode == "warning" else 0.92
    baseline = BASE_PROBABILITY
    adjusted = []
    promotions = []
    demotions = []

    for item in candidates:
        row = dict(item)
        number = row["number"]
        stats = table["numbers"].get(number, {})
        exposure = (
            stats.get("top5_exposure", 0)
            + stats.get("top10_exposure", 0)
            + stats.get("top15_exposure", 0)
        )
        reliability = min(1.0, exposure / 42)
        hit_rate = float(stats.get("posterior_hit_rate", baseline))
        edge = hit_rate - baseline
        adjustment = max(-0.105, min(0.105, edge * 1.85 * intensity * max(0.35, reliability)))
        if row.get("repeat_guard") and not row["repeat_guard"].get("passed"):
            adjustment = min(adjustment, 0.0)
        if previous_guard_blocks_item(row):
            adjustment = min(adjustment, -0.035)

        base_score = float(row.get("score", 0) or 0)
        new_score = max(0.0, min(1.0, base_score + adjustment))
        evidence_index = 50 + max(0.0, min(1.0, (hit_rate - 0.075) / 0.13)) * 49
        blended_confidence = (50 + new_score * 49) * 0.72 + evidence_index * 0.28
        row["score"] = round(new_score, 4)
        row["confidence_index"] = round(max(50.0, min(99.0, blended_confidence)), 1)
        row["hit_through_calibration"] = {
            "status": "evaluated",
            "posterior_hit_rate": round(hit_rate, 4),
            "baseline_probability": round(baseline, 4),
            "edge_vs_baseline": round(edge, 4),
            "exposure": exposure,
            "reliability": round(reliability, 3),
            "score_adjustment": round(adjustment, 4),
            "mode": mode,
        }
        if adjustment >= 0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u5be6\u6230\u547d\u4e2d\u7a7f\u900f\u7387\u5347\u6b0a"])[:4]
            promotions.append({
                "number": number,
                "adjustment": round(adjustment, 4),
                "posterior_hit_rate": round(hit_rate, 4),
                "exposure": exposure,
            })
        elif adjustment <= -0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u5be6\u6230\u547d\u4e2d\u7a7f\u900f\u7387\u964d\u6b0a"])[:4]
            demotions.append({
                "number": number,
                "adjustment": round(adjustment, 4),
                "posterior_hit_rate": round(hit_rate, 4),
                "exposure": exposure,
            })
        adjusted.append(row)

    adjusted.sort(
        key=lambda row: (
            row.get("score", 0),
            row.get("hit_through_calibration", {}).get("posterior_hit_rate", BASE_PROBABILITY),
            row.get("stability_count", 0),
            row.get("cross_validation", {}).get("passed_count", 0),
            -row["number"],
        ),
        reverse=True,
    )
    for rank, row in enumerate(adjusted, 1):
        row["rank"] = rank
        probability_value = conservative_probability_percent(row["score"], rank)
        row["model_probability_percent"] = probability_value
        confidence = confidence_profile(
            row["score"],
            row["confidence_index"],
            probability_value,
            row.get("model_sources", []),
            row.get("cross_validation", {}),
            rank,
        )
        row["confidence_profile"] = confidence
        row["confidence_badges"] = confidence["badges"]
        row["confidence_level"] = confidence["level"]
        row["confidence_label"] = confidence["label"]
        row["high_confidence"] = confidence["is_high_confidence"]

    return adjusted, {
        "status": "evaluated",
        "method": "hit_through_calibration_after_live_precision",
        "rounds": table.get("rounds", 0),
        "rank_bands": table.get("rank_bands", {}),
        "promotion_count": len(promotions),
        "demotion_count": len(demotions),
        "promotions": promotions[:12],
        "demotions": demotions[:12],
        "baseline_probability": round(BASE_PROBABILITY, 4),
    }


def zero_hit_failure_mode(review):
    if not review or not review.get("has_review"):
        return False
    settled = review.get("last_settled", {})
    return int(settled.get("top15_hits") or 0) == 0


def zero_hit_recovery_scores(draws, review=None):
    if not zero_hit_failure_mode(review):
        return {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_numbers = set(draws[-1]["numbers"])
    latest_tails = Counter(number % 10 for number in latest_numbers)
    latest_zones = Counter(zone_label(number) for number in latest_numbers)
    omissions = omission(draws)
    omission_norm = normalize({number: math.log1p(omissions[number]) for number in omissions})
    transition_score = transition_scores(draws)[0]
    shape_score = shape_follow_scores(draws)
    previous_failed = failed_number_set(review)
    previous_top15 = previous_prediction_set(review)
    repeat_policy = repeat_guard(draws)
    values = {}

    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if latest_tails.get(number % 10, 0):
            score += 0.24 + min(0.16, latest_tails[number % 10] * 0.06)
        if latest_zones.get(zone_label(number), 0):
            score += 0.10 + min(0.12, latest_zones[zone_label(number)] * 0.025)
        if any(abs(number - anchor) == 1 for anchor in latest_numbers):
            score += 0.20
        elif any(abs(number - anchor) == 2 for anchor in latest_numbers):
            score += 0.13
        score += transition_score.get(number, 0.0) * 0.20
        score += shape_score.get(number, 0.0) * 0.14
        score += omission_norm.get(number, 0.0) * 0.10
        if number not in previous_top15:
            score += 0.10
        if number in previous_failed:
            score -= 0.28
        if number in latest_numbers:
            if repeat_policy.get(number, {}).get("passed"):
                score += 0.06
            else:
                score -= 0.20
        values[number] = score
    return normalize(values)


def apply_zero_hit_recovery_mode(draws, candidates, review=None):
    if not zero_hit_failure_mode(review):
        return candidates, {
            "status": "not_triggered",
            "reason": "last settled prediction did not have Top15 zero hit",
        }
    recovery = zero_hit_recovery_scores(draws, review)
    adjusted = []
    promotions = []
    demotions = []
    previous_failed = failed_number_set(review)
    latest_numbers = set(draws[-1]["numbers"])

    for item in candidates:
        row = dict(item)
        number = row["number"]
        recovery_score = recovery.get(number, 0.0)
        adjustment = (recovery_score - 0.48) * 0.26
        if number in previous_failed:
            adjustment -= 0.06
        if number in latest_numbers and row.get("repeat_guard") and not row["repeat_guard"].get("passed"):
            adjustment = min(adjustment, -0.03)
        if previous_guard_blocks_item(row):
            adjustment = min(adjustment, -0.04)
        adjustment = max(-0.16, min(0.16, adjustment))
        base_score = float(row.get("score", 0) or 0)
        new_score = max(0.0, min(1.0, base_score + adjustment))
        row["score"] = round(new_score, 4)
        row["confidence_index"] = round(max(50.0, min(99.0, 50 + new_score * 45)), 1)
        row["zero_hit_recovery"] = {
            "triggered": True,
            "recovery_score": round(recovery_score, 4),
            "score_adjustment": round(adjustment, 4),
            "policy": "after_top15_zero_hit_switch_to_tail_neighbor_zone_drag_coverage",
        }
        if adjustment >= 0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u639b\u96f6\u5f8c\u8986\u84cb\u5347\u6b0a"])[:4]
            promotions.append({
                "number": number,
                "recovery_score": round(recovery_score, 4),
                "adjustment": round(adjustment, 4),
            })
        elif adjustment <= -0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u639b\u96f6\u5f8c\u5931\u6557\u9694\u96e2"])[:4]
            demotions.append({
                "number": number,
                "recovery_score": round(recovery_score, 4),
                "adjustment": round(adjustment, 4),
            })
        adjusted.append(row)

    adjusted.sort(
        key=lambda row: (
            row.get("score", 0),
            row.get("zero_hit_recovery", {}).get("recovery_score", 0),
            row.get("hit_through_calibration", {}).get("posterior_hit_rate", BASE_PROBABILITY),
            row.get("stability_count", 0),
            -row["number"],
        ),
        reverse=True,
    )
    for rank, row in enumerate(adjusted, 1):
        row["rank"] = rank
        probability_value = conservative_probability_percent(row["score"], rank)
        row["model_probability_percent"] = probability_value
        confidence = confidence_profile(
            row["score"],
            row["confidence_index"],
            probability_value,
            row.get("model_sources", []),
            row.get("cross_validation", {}),
            rank,
        )
        row["confidence_profile"] = confidence
        row["confidence_badges"] = confidence["badges"]
        row["confidence_level"] = confidence["level"]
        row["confidence_label"] = confidence["label"]
        row["high_confidence"] = confidence["is_high_confidence"]

    return adjusted, {
        "status": "triggered",
        "method": "top15_zero_hit_emergency_coverage_switch",
        "last_actual_numbers": sorted(latest_numbers),
        "promotion_count": len(promotions),
        "demotion_count": len(demotions),
        "promotions": promotions[:12],
        "demotions": demotions[:12],
        "policy": "do not reuse failed ranking after zero hit; rebalance by latest tails, neighbor numbers, zones, drag links, shape follow and omission",
    }


def recall_emergency_active(review=None):
    if not review or not review.get("has_review"):
        return False
    rolling = review.get("rolling_adjustment", {}) or {}
    recent = rolling.get("recent_performance", {}) or {}
    monthly = rolling.get("monthly_review", {}) or review.get("monthly_review", {}) or {}
    last5_top5 = float(recent.get("last5_top5_avg", 9) or 0)
    last5_top10 = float(recent.get("last5_top10_avg", 9) or 0)
    late_or_missing = float(monthly.get("late_or_missing_rate", 0) or 0)
    return bool(
        recent.get("critical_slump")
        or last5_top5 < 0.55
        or last5_top10 < 1.15
        or late_or_missing >= 0.55
    )


def critical_front_nine_active(review=None):
    if not review:
        return False
    rolling = review.get("rolling_adjustment", {}) or {}
    monthly = rolling.get("monthly_review", {}) or review.get("monthly_review", {}) or {}
    monthly_late_rate = float(monthly.get("late_or_missing_rate") or 0)
    monthly_front_rate = float(monthly.get("front_hit_rate") or 1)
    return bool(
        monthly.get("status") == "critical_recall_gap"
        or monthly_late_rate >= 0.50
        or monthly_front_rate <= 0.34
    )


def recall_signal_maps(review=None):
    rolling = (review or {}).get("rolling_adjustment", {}) or {}
    return {
        "late_numbers": _count_map(rolling.get("late_hit_numbers", []), "number", "late_hit_count"),
        "missed_numbers": _count_map(rolling.get("missed_actual_numbers", []), "number", "missed_count"),
        "monthly_numbers": _count_map(rolling.get("monthly_recall_numbers", []), "number", "missed_count"),
        "repeated_failed": _count_map(rolling.get("repeated_failed_numbers", []), "number", "miss_count"),
        "missed_tails": _count_map(rolling.get("missed_actual_tails", []), "tail", "missed_count"),
        "monthly_tails": _count_map(rolling.get("monthly_recall_tails", []), "tail", "missed_count"),
        "missed_zones": _label_count_map(rolling.get("missed_actual_zones", []), "zone", "missed_count"),
        "monthly_zones": _label_count_map(rolling.get("monthly_recall_zones", []), "zone", "missed_count"),
    }


def recall_priority_score(item, review=None):
    maps = recall_signal_maps(review)
    number = int(item["number"])
    tail = number % 10
    zone = zone_label(number)
    number_signal = (
        maps["late_numbers"].get(number, 0) * 1.55
        + maps["missed_numbers"].get(number, 0) * 1.35
        + maps["monthly_numbers"].get(number, 0) * 1.05
    )
    tail_signal = maps["missed_tails"].get(tail, 0) + maps["monthly_tails"].get(tail, 0) * 0.72
    zone_signal = maps["missed_zones"].get(zone, 0) + maps["monthly_zones"].get(zone, 0) * 0.72
    number_score = min(1.0, number_signal / 13.0)
    tail_score = min(1.0, tail_signal / 22.0)
    zone_score = min(1.0, zone_signal / 42.0)
    hit_rate = float((item.get("hit_through_calibration") or {}).get("posterior_hit_rate", BASE_PROBABILITY) or BASE_PROBABILITY)
    hit_score = max(0.0, min(1.0, (hit_rate - 0.075) / 0.13))
    cross = item.get("cross_validation", {})
    cross_score = (int(cross.get("passed_count") or 0) / max(int(cross.get("total_count") or 0), 1))
    stability_score = min(int(item.get("stability_count", 0) or 0), 5) / 5
    base_score = float(item.get("score", 0) or 0)
    priority = (
        base_score * 0.34
        + number_score * 0.26
        + tail_score * 0.09
        + zone_score * 0.09
        + hit_score * 0.10
        + cross_score * 0.07
        + stability_score * 0.05
    )
    repeated_count = maps["repeated_failed"].get(number, 0)
    if repeated_count >= 6 and number_score < 0.35:
        priority -= min(0.18, repeated_count * 0.018)
    if item.get("repeat_guard") and not item["repeat_guard"].get("passed"):
        priority -= 0.22
    if previous_guard_blocks_item(item) and number_score < 0.40:
        priority -= 0.16
    return max(0.0, min(1.0, priority))


def apply_slump_recall_coverage_mode(draws, candidates, review=None):
    if not recall_emergency_active(review):
        return candidates, {
            "status": "not_triggered",
            "reason": "recent prediction maturity is not in emergency recall mode",
        }
    rolling = (review or {}).get("rolling_adjustment", {}) or {}
    recent = rolling.get("recent_performance", {}) or {}
    maps = recall_signal_maps(review)
    adjusted = []
    promotions = []
    demotions = []
    intensity = 1.42 if recent.get("critical_slump") else 1.18
    for item in candidates:
        row = dict(item)
        number = int(row["number"])
        priority = recall_priority_score(row, review)
        adjustment = (priority - 0.50) * 0.24 * intensity
        if row.get("rank", 99) <= 5 and priority < 0.52:
            adjustment -= 0.035 * intensity
        if maps["repeated_failed"].get(number, 0) >= 6 and priority < 0.55:
            adjustment -= 0.045 * intensity
        if number in maps["missed_numbers"] or number in maps["monthly_numbers"] or number in maps["late_numbers"]:
            adjustment += 0.026 * intensity
        adjustment = max(-0.17, min(0.18, adjustment))
        base_score = float(row.get("score", 0) or 0)
        new_score = max(0.0, min(1.0, base_score + adjustment))
        row["score"] = round(new_score, 4)
        row["confidence_index"] = round(max(50.0, min(99.0, 50 + new_score * 47)), 1)
        row["slump_recall_coverage"] = {
            "status": "triggered",
            "priority_score": round(priority, 4),
            "score_adjustment": round(adjustment, 4),
            "mode": "critical" if recent.get("critical_slump") else "warning",
        }
        if adjustment >= 0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u4f4e\u8ff7\u53ec\u56de\u8986\u84cb"])[:4]
            promotions.append({
                "number": number,
                "priority_score": round(priority, 4),
                "adjustment": round(adjustment, 4),
            })
        elif adjustment <= -0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u4f4e\u8ff7\u5931\u6548\u964d\u6b0a"])[:4]
            demotions.append({
                "number": number,
                "priority_score": round(priority, 4),
                "adjustment": round(adjustment, 4),
            })
        adjusted.append(row)

    adjusted.sort(
        key=lambda row: (
            row.get("score", 0),
            row.get("slump_recall_coverage", {}).get("priority_score", 0),
            row.get("hit_through_calibration", {}).get("posterior_hit_rate", BASE_PROBABILITY),
            row.get("cross_validation", {}).get("passed_count", 0),
            -row["number"],
        ),
        reverse=True,
    )

    priority_zones = [
        zone for zone, _ in sorted(
            {
                **maps["missed_zones"],
                **{zone: maps["missed_zones"].get(zone, 0) + maps["monthly_zones"].get(zone, 0) for zone in maps["monthly_zones"]},
            }.items(),
            key=lambda pair: pair[1],
            reverse=True,
        )
    ]
    coverage_swaps = []
    for zone in priority_zones[:4]:
        top10 = adjusted[:10]
        if any(zone_label(item["number"]) == zone for item in top10):
            continue
        candidate_index = next(
            (
                index for index, item in enumerate(adjusted[10:30], 10)
                if zone_label(item["number"]) == zone
                and recall_priority_score(item, review) >= 0.46
                and not previous_guard_blocks_item(item)
                and not (item.get("repeat_guard") and not item["repeat_guard"].get("passed"))
            ),
            None,
        )
        if candidate_index is None:
            continue
        replace_index = min(
            range(6, min(10, len(adjusted))),
            key=lambda index: (
                recall_priority_score(adjusted[index], review),
                adjusted[index].get("score", 0),
            ),
        )
        coverage_swaps.append({
            "zone": zone,
            "promoted": adjusted[candidate_index]["number"],
            "replaced": adjusted[replace_index]["number"],
        })
        adjusted[replace_index], adjusted[candidate_index] = adjusted[candidate_index], adjusted[replace_index]

    front_swaps = []
    if float(recent.get("last5_top5_avg") or 0) < 0.85 and len(adjusted) >= 8:
        max_front_swaps = 2 if float(recent.get("last5_top10_avg") or 0) >= 1.2 else 1
        for zone in priority_zones[:4]:
            if len(front_swaps) >= max_front_swaps:
                break
            top5 = adjusted[:5]
            if any(zone_label(item["number"]) == zone for item in top5):
                continue
            candidate_index = next(
                (
                    index for index, item in enumerate(adjusted[5:25], 5)
                    if zone_label(item["number"]) == zone
                    and recall_priority_score(item, review) >= 0.44
                    and not previous_guard_blocks_item(item)
                    and not (item.get("repeat_guard") and not item["repeat_guard"].get("passed"))
                ),
                None,
            )
            if candidate_index is None:
                continue
            replace_index = min(
                range(2, min(5, len(adjusted))),
                key=lambda index: (
                    zone_label(adjusted[index]["number"]) not in priority_zones[:2],
                    recall_priority_score(adjusted[index], review),
                    adjusted[index].get("score", 0),
                ),
            )
            candidate = adjusted[candidate_index]
            replace = adjusted[replace_index]
            candidate_score = float(candidate.get("score", 0) or 0)
            replace_score = float(replace.get("score", 0) or 0)
            candidate_priority = recall_priority_score(candidate, review)
            replace_priority = recall_priority_score(replace, review)
            candidate_cross = int((candidate.get("cross_validation") or {}).get("passed_count") or 0)
            if (
                candidate_score >= replace_score * 0.72
                or candidate_priority >= replace_priority + 0.06
                or candidate_cross >= 4
            ):
                candidate["reasons"] = (candidate.get("reasons", []) + ["\u524d\u4e94\u53ec\u56de\u4fee\u6b63"])[:4]
                front_swaps.append({
                    "zone": zone,
                    "promoted": candidate["number"],
                    "replaced": replace["number"],
                    "promoted_priority": round(candidate_priority, 4),
                    "replaced_priority": round(replace_priority, 4),
                    "reason": "top5_recent_slump_zone_recall",
                })
                adjusted[replace_index], adjusted[candidate_index] = adjusted[candidate_index], adjusted[replace_index]

    for rank, row in enumerate(adjusted, 1):
        row["rank"] = rank
        probability_value = conservative_probability_percent(row["score"], rank)
        row["model_probability_percent"] = probability_value
        confidence = confidence_profile(
            row["score"],
            row["confidence_index"],
            probability_value,
            row.get("model_sources", []),
            row.get("cross_validation", {}),
            rank,
        )
        row["confidence_profile"] = confidence
        row["confidence_badges"] = confidence["badges"]
        row["confidence_level"] = confidence["level"]
        row["confidence_label"] = confidence["label"]
        row["high_confidence"] = confidence["is_high_confidence"]

    return adjusted, {
        "status": "triggered",
        "method": "recent_slump_recall_coverage_switch",
        "recent_top5_avg": recent.get("last5_top5_avg"),
        "recent_top10_avg": recent.get("last5_top10_avg"),
        "promotion_count": len(promotions),
        "demotion_count": len(demotions),
        "coverage_swaps": coverage_swaps,
        "front_swaps": front_swaps,
        "promotions": promotions[:12],
        "demotions": demotions[:12],
        "policy": "when recent Top5/Top10 maturity collapses, rebalance by missed numbers, missed tails, missed zones, verified recall and top5 zone coverage instead of trusting stale front-rank signals",
    }


def adaptive_feature_weights(draws, review=None, rounds=120):
    base_weights = industrial_weights(review)
    if len(draws) < 160:
        return base_weights, {
            "status": "insufficient_data",
            "rounds": 0,
            "method": "fallback_base_weights",
        }
    feature_names = list(base_weights)
    stats = {
        name: {
            "rounds": 0,
            "top5_hits": 0,
            "top10_hits": 0,
            "top15_hits": 0,
            "recent_rounds": 0,
            "recent_top5_hits": 0,
            "recent_top10_hits": 0,
            "recent_top15_hits": 0,
        }
        for name in feature_names
    }
    start = max(120, len(draws) - rounds - 1)
    recent_start = max(start, len(draws) - 91)
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        features = build_feature_matrix(train, review=None, include_dependency=False)
        for name in feature_names:
            ranked = sorted(
                range(NUMBER_MIN, NUMBER_MAX + 1),
                key=lambda number: (features[number].get(name, 0.0), -number),
                reverse=True,
            )
            stats[name]["rounds"] += 1
            top5_hits = len(set(ranked[:5]) & actual)
            top10_hits = len(set(ranked[:10]) & actual)
            top15_hits = len(set(ranked[:15]) & actual)
            stats[name]["top5_hits"] += top5_hits
            stats[name]["top10_hits"] += top10_hits
            stats[name]["top15_hits"] += top15_hits
            if idx >= recent_start:
                stats[name]["recent_rounds"] += 1
                stats[name]["recent_top5_hits"] += top5_hits
                stats[name]["recent_top10_hits"] += top10_hits
                stats[name]["recent_top15_hits"] += top15_hits

    baseline = {
        5: DRAW_SIZE * 5 / NUMBER_MAX,
        10: DRAW_SIZE * 10 / NUMBER_MAX,
        15: DRAW_SIZE * 15 / NUMBER_MAX,
    }
    multipliers = {}
    feature_report = {}
    for name, item in stats.items():
        rounds_done = item["rounds"] or 1
        top5_avg = item["top5_hits"] / rounds_done
        top10_avg = item["top10_hits"] / rounds_done
        top15_avg = item["top15_hits"] / rounds_done
        recent_rounds = item["recent_rounds"] or 1
        recent_top5_avg = item["recent_top5_hits"] / recent_rounds
        recent_top10_avg = item["recent_top10_hits"] / recent_rounds
        recent_top15_avg = item["recent_top15_hits"] / recent_rounds
        full_edge = (
            (top5_avg - baseline[5]) * 0.48
            + (top10_avg - baseline[10]) * 0.34
            + (top15_avg - baseline[15]) * 0.18
        )
        recent_edge = (
            (recent_top5_avg - baseline[5]) * 0.42
            + (recent_top10_avg - baseline[10]) * 0.43
            + (recent_top15_avg - baseline[15]) * 0.15
        )
        edge = full_edge * 0.42 + recent_edge * 0.58
        multiplier = max(0.45, min(1.65, 1 + edge * 0.72))
        multipliers[name] = multiplier
        feature_report[name] = {
            "rounds": item["rounds"],
            "recent_rounds": item["recent_rounds"],
            "top5_avg_hits": round(top5_avg, 3),
            "top10_avg_hits": round(top10_avg, 3),
            "top15_avg_hits": round(top15_avg, 3),
            "recent_top5_avg_hits": round(recent_top5_avg, 3),
            "recent_top10_avg_hits": round(recent_top10_avg, 3),
            "recent_top15_avg_hits": round(recent_top15_avg, 3),
            "full_weighted_edge": round(full_edge, 4),
            "recent_weighted_edge": round(recent_edge, 4),
            "weighted_edge": round(edge, 4),
            "multiplier": round(multiplier, 3),
        }
    adjusted = {name: base_weights[name] * multipliers[name] for name in feature_names}
    total = sum(adjusted.values()) or 1
    calibrated = {name: adjusted[name] / total for name in feature_names}
    ranked_features = sorted(feature_report.items(), key=lambda pair: pair[1]["weighted_edge"], reverse=True)
    return calibrated, {
        "status": "evaluated",
        "method": "recent_fast_walk_forward_feature_weight_calibration",
        "rounds": max((item["rounds"] for item in stats.values()), default=0),
        "feature_report": feature_report,
        "top_boosted_features": [
            {"feature": name, **report}
            for name, report in ranked_features[:6]
        ],
        "top_penalized_features": [
            {"feature": name, **report}
            for name, report in ranked_features[-6:]
        ],
        "base_weights": {name: round(value, 5) for name, value in base_weights.items()},
        "calibrated_weights": {name: round(value, 5) for name, value in calibrated.items()},
    }


def model_lifecycle_policy(weight_calibration):
    rows = []
    for item in weight_calibration.get("top_boosted_features", []) + weight_calibration.get("top_penalized_features", []):
        feature = item.get("feature")
        if not feature or any(row["feature"] == feature for row in rows):
            continue
        recent_edge = item.get("recent_weighted_edge", item.get("weighted_edge", 0)) or 0
        full_edge = item.get("full_weighted_edge", item.get("weighted_edge", 0)) or 0
        multiplier = item.get("multiplier", 1) or 1
        if recent_edge >= 0.08 and multiplier >= 1.04:
            action = "upgrade"
            label = "\u5347\u7d1a"
            reason = "\u8fd1\u671f\u8207\u9577\u671f\u56de\u6e2c\u5747\u6709\u6b63\u5411\u512a\u52e2"
        elif recent_edge <= -0.10 and multiplier <= 0.94:
            action = "quarantine"
            label = "\u89c0\u5bdf\u505c\u7528"
            reason = "\u8fd1\u671f\u56de\u6e2c\u660e\u986f\u62d6\u7d2f\uff0c\u4e0b\u671f\u964d\u4f4e\u8a72\u6a21\u578b\u5f71\u97ff"
        elif recent_edge < -0.04 or multiplier < 0.99:
            action = "downgrade"
            label = "\u964d\u7d1a"
            reason = "\u8fd1\u671f\u8868\u73fe\u4f4e\u65bc\u57fa\u6e96\uff0c\u9700\u964d\u6b0a"
        else:
            action = "keep"
            label = "\u4fdd\u7559"
            reason = "\u8868\u73fe\u63a5\u8fd1\u57fa\u6e96\uff0c\u4fdd\u7559\u4f46\u4e0d\u653e\u5927"
        rows.append(
            {
                "feature": feature,
                "label": MODEL_SOURCE_LABELS.get(feature, feature),
                "action": action,
                "action_label": label,
                "reason": reason,
                "recent_edge": round(recent_edge, 4),
                "full_edge": round(full_edge, 4),
                "multiplier": round(multiplier, 3),
                "recent_top10_avg_hits": item.get("recent_top10_avg_hits"),
                "top10_avg_hits": item.get("top10_avg_hits"),
            }
        )
    priority = {"upgrade": 0, "quarantine": 1, "downgrade": 2, "keep": 3}
    rows.sort(key=lambda row: (priority.get(row["action"], 9), -abs(row["recent_edge"])))
    return {
        "status": "evaluated",
        "policy": "recent_model_upgrade_downgrade_quarantine",
        "upgrade_count": sum(1 for row in rows if row["action"] == "upgrade"),
        "downgrade_count": sum(1 for row in rows if row["action"] == "downgrade"),
        "quarantine_count": sum(1 for row in rows if row["action"] == "quarantine"),
        "models": rows,
    }


def apply_lifecycle_weight_policy(weights, lifecycle):
    adjusted = dict(weights)
    for row in lifecycle.get("models", []):
        feature = row.get("feature")
        action = row.get("action")
        if feature not in adjusted:
            continue
        if action == "upgrade":
            adjusted[feature] *= 1.12
        elif action == "downgrade":
            adjusted[feature] *= 0.82
        elif action == "quarantine":
            adjusted[feature] *= 0.45
    total = sum(adjusted.values()) or 1.0
    return {name: value / total for name, value in adjusted.items()}


def apply_objective_feature_calibration(candidates, weight_calibration, review=None):
    feature_report = weight_calibration.get("feature_report", {}) if weight_calibration else {}
    if not feature_report:
        return candidates, {
            "status": "not_available",
            "reason": "feature walk-forward report is missing",
        }

    baseline = {
        5: DRAW_SIZE * 5 / NUMBER_MAX,
        10: DRAW_SIZE * 10 / NUMBER_MAX,
        15: DRAW_SIZE * 15 / NUMBER_MAX,
    }
    mode = slump_mode(review)
    zero_hit_mode = zero_hit_failure_mode(review)
    intensity = 1.28 if zero_hit_mode else 1.12 if mode == "critical" else 1.0 if mode == "warning" else 0.86
    calibrated = []
    promotions = []
    demotions = []

    for item in candidates:
        row = dict(item)
        sources = row.get("model_sources", [])
        total_strength = 0.0
        positive_strength = 0.0
        negative_strength = 0.0
        edge_sum = 0.0
        source_edges = []

        for source in sources:
            feature = source.get("model")
            if feature not in feature_report:
                continue
            report = feature_report[feature]
            signal = float(source.get("signal", 0.0) or 0.0)
            contribution = float(source.get("contribution", 0.0) or 0.0)
            strength = max(0.02, signal * 0.58 + contribution * 9.0)
            recent_edge = float(report.get("recent_weighted_edge", 0.0) or 0.0)
            full_edge = float(report.get("full_weighted_edge", 0.0) or 0.0)
            top5_edge = float(report.get("recent_top5_avg_hits", baseline[5]) or 0.0) - baseline[5]
            top10_edge = float(report.get("recent_top10_avg_hits", baseline[10]) or 0.0) - baseline[10]
            objective_edge = recent_edge * 0.46 + full_edge * 0.22 + top5_edge * 0.18 + top10_edge * 0.14
            total_strength += strength
            edge_sum += objective_edge * strength
            if objective_edge > 0:
                positive_strength += strength
            else:
                negative_strength += strength
            source_edges.append({
                "feature": feature,
                "label": MODEL_SOURCE_LABELS.get(feature, feature),
                "objective_edge": round(objective_edge, 4),
                "recent_top5_avg_hits": report.get("recent_top5_avg_hits"),
                "recent_top10_avg_hits": report.get("recent_top10_avg_hits"),
                "strength": round(strength, 4),
            })

        if total_strength <= 0:
            adjustment = -0.055
            positive_ratio = 0.0
            objective_edge = -0.03
        else:
            objective_edge = edge_sum / total_strength
            positive_ratio = positive_strength / total_strength
            adjustment = objective_edge * 1.85 * intensity
            if positive_ratio < 0.34:
                adjustment -= 0.052 * intensity
            elif positive_ratio >= 0.72:
                adjustment += 0.030 * intensity
            if negative_strength > positive_strength * 1.35:
                adjustment -= 0.030 * intensity

        if row.get("repeat_guard") and not row["repeat_guard"].get("passed"):
            adjustment = min(adjustment, -0.035)
        if previous_guard_blocks_item(row):
            adjustment = min(adjustment, -0.045)
        adjustment = max(-0.18, min(0.16, adjustment))

        base_score = float(row.get("score", 0.0) or 0.0)
        new_score = max(0.0, min(1.0, base_score + adjustment))
        objective_index = 50 + max(0.0, min(1.0, (objective_edge + 0.08) / 0.18)) * 49
        blended_confidence = (50 + new_score * 45) * 0.72 + objective_index * 0.28
        row["score"] = round(new_score, 4)
        row["confidence_index"] = round(max(50.0, min(99.0, blended_confidence)), 1)
        row["objective_feature_calibration"] = {
            "status": "evaluated",
            "objective_edge": round(objective_edge, 4),
            "positive_source_ratio": round(positive_ratio, 3),
            "positive_strength": round(positive_strength, 4),
            "negative_strength": round(negative_strength, 4),
            "score_adjustment": round(adjustment, 4),
            "mode": mode,
            "zero_hit_mode": zero_hit_mode,
            "top_sources": sorted(source_edges, key=lambda x: (x["objective_edge"], x["strength"]), reverse=True)[:6],
            "weak_sources": sorted(source_edges, key=lambda x: (x["objective_edge"], -x["strength"]))[:6],
        }
        if adjustment >= 0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u5be6\u6230\u6709\u6548\u6a21\u578b\u5347\u6b0a"])[:4]
            promotions.append({
                "number": row["number"],
                "adjustment": round(adjustment, 4),
                "objective_edge": round(objective_edge, 4),
                "positive_source_ratio": round(positive_ratio, 3),
            })
        elif adjustment <= -0.035:
            row["reasons"] = (row.get("reasons", []) + ["\u5be6\u6230\u7121\u6548\u6a21\u578b\u964d\u6b0a"])[:4]
            demotions.append({
                "number": row["number"],
                "adjustment": round(adjustment, 4),
                "objective_edge": round(objective_edge, 4),
                "positive_source_ratio": round(positive_ratio, 3),
            })
        calibrated.append(row)

    calibrated.sort(
        key=lambda row: (
            row.get("score", 0),
            row.get("objective_feature_calibration", {}).get("objective_edge", -1),
            row.get("hit_through_calibration", {}).get("posterior_hit_rate", BASE_PROBABILITY),
            row.get("cross_validation", {}).get("passed_count", 0),
            -row["number"],
        ),
        reverse=True,
    )
    for rank, row in enumerate(calibrated, 1):
        row["rank"] = rank
        probability_value = conservative_probability_percent(row["score"], rank)
        row["model_probability_percent"] = probability_value
        confidence = confidence_profile(
            row["score"],
            row["confidence_index"],
            probability_value,
            row.get("model_sources", []),
            row.get("cross_validation", {}),
            rank,
        )
        row["confidence_profile"] = confidence
        row["confidence_badges"] = confidence["badges"]
        row["confidence_level"] = confidence["level"]
        row["confidence_label"] = confidence["label"]
        row["high_confidence"] = confidence["is_high_confidence"]

    return calibrated, {
        "status": "evaluated",
        "method": "candidate_level_objective_feature_walk_forward_calibration",
        "feature_count": len(feature_report),
        "mode": mode,
        "zero_hit_mode": zero_hit_mode,
        "promotion_count": len(promotions),
        "demotion_count": len(demotions),
        "promotions": promotions[:12],
        "demotions": demotions[:12],
        "policy": "a number must be supported by features that recently beat baseline; weak feature consensus is penalized",
    }


def score_numbers(draws, review=None, include_dependency=True, weights_override=None):
    features = build_feature_matrix(draws, review, include_dependency=include_dependency)
    weights = weights_override or industrial_weights(review)
    failed = failed_number_set(review)
    rolling = (review or {}).get("rolling_adjustment", {})
    penalized_reasons = {item.get("reason") for item in rolling.get("penalized_reasons", [])}
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    missed_actual_numbers = {int(item.get("number")) for item in rolling.get("missed_actual_numbers", []) if item.get("number")}
    missed_actual_tails = {int(item.get("tail")) for item in rolling.get("missed_actual_tails", []) if item.get("tail") is not None}
    missed_actual_zones = {str(item.get("zone")) for item in rolling.get("missed_actual_zones", []) if item.get("zone")}
    monthly_recall_numbers = {int(item.get("number")) for item in rolling.get("monthly_recall_numbers", []) if item.get("number")}
    monthly_recall_tails = {int(item.get("tail")) for item in rolling.get("monthly_recall_tails", []) if item.get("tail") is not None}
    monthly_recall_zones = {str(item.get("zone")) for item in rolling.get("monthly_recall_zones", []) if item.get("zone")}
    mode = slump_mode(review)
    latest_set = set(draws[-1]["numbers"])
    repeat_policy = repeat_guard(draws)
    score = {}
    reasons = defaultdict(list)

    for number, values in features.items():
        raw = sum(values.get(name, 0) * weight for name, weight in weights.items())
        previous_policy = previous_prediction_guard(number, values, review)
        if previous_policy and not previous_policy["passed"]:
            recovery_count = int(previous_policy.get("recovery_condition_count") or 0)
            strong_count = int(previous_policy.get("strong_condition_count") or 0)
            if recovery_count >= 1 or strong_count >= 2:
                raw *= 0.68 if mode == "critical" else 0.62
                reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u8edf\u5b88\u9580\u89c0\u5bdf")
            else:
                raw *= 0.42 if mode == "critical" else 0.36
                reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u672a\u9054\u91cd\u5165\u9580\u6abb")
        elif previous_policy and previous_policy["passed"]:
            reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u901a\u904e\u91cd\u5165\u9a57\u7b97")
        if number in failed:
            reentry_signal = (
                number in late_hit_numbers
                or number in missed_actual_numbers
                or values.get("rank_error_correction", 0) >= 0.58
                or values.get("missed_hit_recovery", 0) >= 0.58
                or values.get("zone_coverage_recovery", 0) >= 0.62
            )
            if reentry_signal:
                raw *= 0.76 if mode == "critical" else 0.70
                reasons[number].append("\u5931\u6557\u865f\u56de\u88dc\u9a57\u7b97")
            else:
                raw *= 0.34 if mode == "critical" else 0.30
                reasons[number].append("\u4e0a\u671f\u5931\u6557\u6838\u5fc3\u865f\u78bc\u8edf\u9694\u96e2")
        if values["omission"] >= 0.7:
            reasons[number].append("\u907a\u6f0f\u88dc\u511f")
        if values["pair"] >= 0.7:
            reasons[number].append("\u5171\u73fe\u95dc\u806f")
        if values["validated_dependency"] >= 0.7:
            reasons[number].append("\u6a23\u672c\u5916\u9023\u52d5")
        if values["markov_chain"] >= 0.7:
            reasons[number].append("\u99ac\u53ef\u592b\u8f49\u79fb")
        if values["time_series"] >= 0.7:
            reasons[number].append("\u6642\u9593\u5e8f\u5217\u52d5\u80fd")
        if values["neural_network"] >= 0.7:
            reasons[number].append("\u795e\u7d93\u7db2\u8def\u7d9c\u5408")
        if values["tail_zone"] >= 0.7:
            reasons[number].append("\u5c3e\u6578\u5340\u9593")
        if values["cross_consensus"] >= 0.7:
            reasons[number].append("\u591a\u6a21\u578b\u5171\u8b58")
        if values["cycle_timing"] >= 0.7:
            reasons[number].append("\u9031\u671f\u4f4d\u7f6e")
        if values["trend_alignment"] >= 0.7:
            reasons[number].append("\u5feb\u6162\u8da8\u52e2\u4e00\u81f4")
        if values["bayesian_posterior"] >= 0.7:
            reasons[number].append("\u8c9d\u6c0f\u4fdd\u5b88\u6821\u6e96")
        if values["monte_carlo_stability"] >= 0.7:
            reasons[number].append("\u8499\u5730\u5361\u7f85\u7a69\u5b9a")
        if values["distribution_balance"] >= 0.7:
            reasons[number].append("\u5206\u5e03\u5e73\u8861\u98a8\u63a7")
        if values["shape_follow"] >= 0.7:
            reasons[number].append("\u724c\u578b\u76f8\u4f3c\u8ddf\u96a8")
        if values["zone_parity_pressure"] >= 0.7:
            reasons[number].append("\u5340\u9593\u5947\u5076\u58d3\u529b")
        if values["missed_hit_recovery"] >= 0.7:
            reasons[number].append("\u6f0f\u547d\u4e2d\u56de\u6536")
        if values["rank_error_correction"] >= 0.7:
            reasons[number].append("\u6392\u540d\u932f\u4f4d\u4fee\u6b63")
        if values["regime_switch"] >= 0.7:
            reasons[number].append("\u958b\u734e\u578b\u614b\u5207\u63db")
        if values["zone_coverage_recovery"] >= 0.7:
            reasons[number].append("\u5206\u5340\u8986\u84cb\u56de\u88dc")
        if values["freq_50"] >= 0.7 or values["freq_100"] >= 0.7:
            reasons[number].append("\u4e2d\u671f\u7a69\u5b9a")
        if values["date"] > 0:
            reasons[number].append("\u65e5\u671f\u724c")
        if number in latest_set:
            policy = repeat_policy.get(number, {})
            if policy.get("passed"):
                raw *= 0.78
                reasons[number].append("\u9023\u838a\u5408\u683c\u9a57\u7b97")
            else:
                raw *= 0.05
                reasons[number].append("\u9023\u838a\u5b88\u9580\u672a\u901a\u904e")
        reason_set = set(reasons[number])
        if number in repeated_failed_numbers:
            raw *= 0.62 if mode == "critical" else 0.68 if mode == "warning" else 0.72
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u9023\u7e8c\u672a\u547d\u4e2d\u964d\u6b0a")
        if number in late_hit_numbers and values["rank_error_correction"] >= 0.55:
            raw *= 1.28 if mode == "critical" else 1.22 if mode == "warning" else 1.16
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u5f8c\u6bb5\u547d\u4e2d\u524d\u79fb")
        if number in missed_actual_numbers and values["rank_error_correction"] >= 0.52:
            raw *= 1.26 if mode == "critical" else 1.18
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u6f0f\u6293\u5be6\u958b\u865f\u88dc\u4f4d")
        if number in monthly_recall_numbers and values["rank_error_correction"] >= 0.45:
            raw *= 1.18 if mode == "critical" else 1.12
            reasons[number].append("\u6708\u5ea6\u6f0f\u6293\u865f\u56de\u62c9")
        elif (number % 10 in missed_actual_tails or zone_label(number) in missed_actual_zones) and mode in {"warning", "critical"}:
            raw *= 1.08
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u6f0f\u6293\u5c3e\u6578\u5340\u9593\u88dc\u4f4d")
        if (number % 10 in monthly_recall_tails or zone_label(number) in monthly_recall_zones) and mode in {"warning", "critical"}:
            raw *= 1.055
            reasons[number].append("\u6708\u5ea6\u5c3e\u6578\u5340\u9593\u56de\u62c9")
        if reason_set & penalized_reasons:
            raw *= 0.76 if mode == "critical" else 0.8 if mode == "warning" else 0.84
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u672a\u547d\u4e2d\u4f86\u6e90\u964d\u6b0a")
        if reason_set & boosted_reasons:
            raw *= 1.2 if mode == "critical" else 1.16 if mode == "warning" else 1.12
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u547d\u4e2d\u4f86\u6e90\u5347\u6b0a")
        score[number] = raw

    normalized_score = normalize(score)
    omissions = omission(draws)
    ranked = rank_values(normalized_score)
    candidates = []
    for rank, number in enumerate(ranked, 1):
        model_sources = number_model_sources(features[number], weights)
        cross_validation = number_cross_validation(features[number])
        score_value = round(normalized_score[number], 4)
        confidence_value = round(50 + normalized_score[number] * 49, 1)
        probability_value = conservative_probability_percent(normalized_score[number], rank)
        confidence = confidence_profile(
            score_value,
            confidence_value,
            probability_value,
            model_sources,
            cross_validation,
            rank,
        )
        candidates.append(
            {
                "number": number,
                "rank": rank,
                "score": score_value,
                "confidence_index": confidence_value,
                "model_probability_percent": probability_value,
                "omission": omissions[number],
                "repeat_guard": repeat_policy.get(number),
                "previous_prediction_guard": previous_prediction_guard(number, features[number], review),
                "model_sources": model_sources,
                "source_model_count": len(model_sources),
                "cross_validation": cross_validation,
                "confidence_profile": confidence,
                "confidence_badges": confidence["badges"],
                "confidence_level": confidence["level"],
                "confidence_label": confidence["label"],
                "high_confidence": confidence["is_high_confidence"],
                "reasons": reasons[number][:4] or ["\u5de5\u696d\u7d1a\u7d9c\u5408\u5206\u6578"],
            }
        )
    return candidates, weights


def diversity_penalty(selected, candidate):
    penalty = 0.0
    if any(n % 10 == candidate % 10 for n in selected):
        penalty += 0.06
    if sum(1 for n in selected if zone_label(n) == zone_label(candidate)) >= 2:
        penalty += 0.08
    if any(abs(n - candidate) == 1 for n in selected):
        penalty += 0.035
    return penalty


def previous_guard_blocks_item(item):
    guard = item.get("previous_prediction_guard")
    if not guard or guard.get("passed"):
        return False
    recovery_count = int(guard.get("recovery_condition_count") or 0)
    strong_count = int(guard.get("strong_condition_count") or 0)
    return recovery_count == 0 and strong_count < 2


def failed_number_reentry_allowed(item, review=None):
    number = int(item.get("number"))
    rolling = (review or {}).get("rolling_adjustment", {})
    late_hit_numbers = {
        int(row.get("number"))
        for row in rolling.get("late_hit_numbers", [])
        if row.get("number")
    }
    missed_actual_numbers = {
        int(row.get("number"))
        for row in rolling.get("missed_actual_numbers", [])
        if row.get("number")
    }
    monthly_recall_numbers = {
        int(row.get("number"))
        for row in rolling.get("monthly_recall_numbers", [])
        if row.get("number")
    }
    repeated_failed = {
        int(row.get("number")): int(row.get("miss_count", 0))
        for row in rolling.get("repeated_failed_numbers", [])
        if row.get("number")
    }
    if number in missed_actual_numbers or number in late_hit_numbers or number in monthly_recall_numbers:
        return True
    reasons = set(item.get("reasons", []))
    recovery_reasons = {"\u6392\u540d\u932f\u4f4d\u4fee\u6b63", "\u6f0f\u547d\u4e2d\u56de\u6536", "\u7a69\u5b9a\u5171\u8b58", "\u5171\u73fe\u95dc\u806f", "\u5206\u5340\u8986\u84cb\u56de\u88dc"}
    objective_edge = float((item.get("objective_feature_calibration") or {}).get("objective_edge", 0.0) or 0.0)
    hit_rate = float((item.get("hit_through_calibration") or {}).get("posterior_hit_rate", BASE_PROBABILITY) or BASE_PROBABILITY)
    guard = item.get("previous_prediction_guard") or {}
    recovery_count = int(guard.get("recovery_condition_count") or 0)
    strong_count = int(guard.get("strong_condition_count") or 0)
    repeated_count = repeated_failed.get(number, 0)
    strong_reentry = (
        item.get("score", 0) >= 0.62
        and (
            objective_edge >= 0.035
            or hit_rate >= BASE_PROBABILITY + 0.025
            or item.get("stability_count", 0) >= 4
            or bool(reasons & recovery_reasons)
            or recovery_count >= 1
            or strong_count >= 2
        )
    )
    if repeated_count >= 8 and not (objective_edge >= 0.06 or hit_rate >= BASE_PROBABILITY + 0.04):
        return False
    return strong_reentry


def optimized_group(candidates, size, review=None):
    score_map = {item["number"]: item["score"] for item in candidates}
    failed = failed_number_set(review)
    selected = []
    pool = [item["number"] for item in candidates[:30]]
    while len(selected) < size and pool:
        best = max(
            pool,
            key=lambda n: score_map[n] - diversity_penalty(selected, n) - (0.35 if n in failed else 0),
        )
        selected.append(best)
        pool.remove(best)
    return sorted(selected)


def strong_single_group(candidates, review=None):
    rolling = (review or {}).get("rolling_adjustment", {})
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    for item in candidates[:12]:
        number = item["number"]
        reasons = set(item.get("reasons", []))
        if number in repeated_failed_numbers:
            continue
        if previous_guard_blocks_item(item):
            continue
        score = item.get("score", 0)
        confidence = item.get("confidence_index", 0)
        stability = item.get("stability_count", 0)
        boosted = bool(reasons & boosted_reasons)
        if score >= 0.9 and confidence >= 94:
            return [number]
        if score >= 0.84 and confidence >= 90 and (stability >= 3 or boosted):
            return [number]
    return []


def single_precision_group(candidates, review=None):
    failed = failed_number_set(review)
    rolling = (review or {}).get("rolling_adjustment", {})
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    missed_actual_numbers = {int(item.get("number")) for item in rolling.get("missed_actual_numbers", []) if item.get("number")}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    ranked = []
    for original_rank, item in enumerate(candidates[:24], 1):
        number = item["number"]
        if number in failed and not failed_number_reentry_allowed(item, review):
            continue
        if number in repeated_failed_numbers and not failed_number_reentry_allowed(item, review):
            continue
        if previous_guard_blocks_item(item):
            continue
        reasons = set(item.get("reasons", []))
        precision_score = (
            item.get("score", 0) * 0.58
            + ((item.get("confidence_index", 50) - 50) / 49) * 0.22
            + min(item.get("stability_count", 0), 5) * 0.028
            + (0.045 if reasons & boosted_reasons else 0)
            + (0.055 if number in late_hit_numbers else 0)
            + (0.045 if number in missed_actual_numbers else 0)
            + (0.030 if 11 <= original_rank <= 24 and item.get("stability_count", 0) >= 4 else 0)
        )
        ranked.append((precision_score, item))
    ranked.sort(key=lambda pair: (pair[0], pair[1].get("score", 0), pair[1].get("confidence_index", 0), -pair[1]["number"]), reverse=True)
    return [ranked[0][1]["number"]] if ranked else []


def five_hit_two_group(candidates, review=None):
    failed = failed_number_set(review)
    rolling = (review or {}).get("rolling_adjustment", {})
    priority_zones = [
        str(item.get("zone"))
        for item in rolling.get("missed_actual_zones", [])
        if item.get("zone")
    ]
    selected = []
    pool = [
        item for item in candidates[:30]
        if not (item["number"] in failed and not failed_number_reentry_allowed(item, review))
        and not previous_guard_blocks_item(item)
    ]
    score_map = {item["number"]: item["score"] for item in candidates}
    for item in pool:
        if len(selected) >= 5:
            break
        number = item["number"]
        if sum(1 for selected_number in selected if zone_label(selected_number) == zone_label(number)) >= 2:
            continue
        if sum(1 for selected_number in selected if selected_number % 10 == number % 10) >= 2:
            continue
        selected.append(number)
    for zone in priority_zones:
        if any(zone_label(number) == zone for number in selected):
            continue
        zone_item = next((item for item in pool if zone_label(item["number"]) == zone and item["number"] not in selected), None)
        if not zone_item:
            continue
        if len(selected) < 5:
            selected.append(zone_item["number"])
            continue
        replacement_pool = [
            number for number in selected
            if sum(1 for selected_number in selected if zone_label(selected_number) == zone_label(number)) >= 2
        ] or selected
        replace_number = min(replacement_pool, key=lambda number: score_map.get(number, 0))
        add_number = zone_item["number"]
        if score_map.get(add_number, 0) >= score_map.get(replace_number, 0) * 0.82:
            selected.remove(replace_number)
            selected.append(add_number)
    if len(selected) < 5:
        for item in pool:
            if item["number"] not in selected:
                selected.append(item["number"])
            if len(selected) >= 5:
                break
    return sorted(selected[:5])


def nine_hit_three_group(candidates, review=None):
    failed = failed_number_set(review)
    rolling = (review or {}).get("rolling_adjustment", {})
    if critical_front_nine_active(review):
        return top_rank_group(candidates, 9, review)
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    priority_zones = [
        str(item.get("zone"))
        for item in rolling.get("missed_actual_zones", [])
        if item.get("zone")
    ]
    score_map = {item["number"]: item["score"] for item in candidates}
    pool = [
        item["number"] for item in candidates[:30]
        if not (item["number"] in failed and not failed_number_reentry_allowed(item, review))
        and not previous_guard_blocks_item(item)
    ]
    selected = []
    while len(selected) < 9 and pool:
        best = max(
            pool,
            key=lambda number: (
                score_map[number]
                + (0.08 if number in late_hit_numbers else 0)
                - diversity_penalty(selected, number) * 1.35
                - (0.08 if sum(1 for n in selected if zone_label(n) == zone_label(number)) >= 3 else 0)
            ),
        )
        selected.append(best)
        pool.remove(best)
    for zone in priority_zones:
        if any(zone_label(number) == zone for number in selected):
            continue
        zone_candidates = [number for number in pool if zone_label(number) == zone]
        if not zone_candidates:
            continue
        replacement_pool = [
            number for number in selected
            if sum(1 for selected_number in selected if zone_label(selected_number) == zone_label(number)) >= 3
        ] or selected
        replace_number = min(replacement_pool, key=lambda number: score_map.get(number, 0))
        add_number = max(zone_candidates, key=lambda number: score_map.get(number, 0))
        if score_map.get(add_number, 0) >= score_map.get(replace_number, 0) * 0.82:
            selected.remove(replace_number)
            selected.append(add_number)
    return sorted(selected[:9])


def top_rank_group(candidates, size, review=None):
    failed = failed_number_set(review)
    selected = []
    for item in candidates:
        number = item["number"]
        if number in failed and not failed_number_reentry_allowed(item, review):
            continue
        if previous_guard_blocks_item(item):
            continue
        selected.append(number)
        if len(selected) >= size:
            break
    return sorted(selected)


def micro_confidence_score(item, review=None, selected=None):
    selected = selected or []
    rank = int(item.get("rank") or 99)
    cross = item.get("cross_validation", {}) or {}
    passed = int(cross.get("passed_count") or 0)
    total = int(cross.get("total_count") or 0) or 1
    probability = float(item.get("model_probability_percent", 0) or 0)
    recall_score = recall_priority_score(item, review)
    stability = min(int(item.get("stability_count", 0) or 0), 5) / 5
    rank_score = max(0.0, (10 - rank) / 9) if rank <= 9 else max(0.0, (16 - rank) / 18)
    top9_bonus = 0.055 if rank <= 9 else -0.090
    high_conf_bonus = 0.060 if item.get("high_confidence") else 0.0
    leakage_bonus = 0.045 if (item.get("top9_leakage_lock") or {}).get("status") == "promoted" else 0.0
    score = (
        float(item.get("score", 0) or 0) * 0.26
        + (probability / 18.72) * 0.16
        + (passed / total) * 0.20
        + recall_score * 0.18
        + stability * 0.12
        + rank_score * 0.08
        + top9_bonus
        + high_conf_bonus
        + leakage_bonus
    )
    if item.get("repeat_guard") and not item["repeat_guard"].get("passed"):
        score -= 0.22
    if previous_guard_blocks_item(item):
        score -= 0.18
    if item["number"] in failed_number_set(review) and not failed_number_reentry_allowed(item, review):
        score -= 0.16
    if any(number % 10 == item["number"] % 10 for number in selected):
        score -= 0.035
    if sum(1 for number in selected if zone_label(number) == zone_label(item["number"])) >= 2:
        score -= 0.045
    return max(0.0, min(1.35, score))


def micro_confidence_group(candidates, size, review=None):
    pool = [
        item for item in candidates[:15]
        if not previous_guard_blocks_item(item)
        and not (item.get("repeat_guard") and not item["repeat_guard"].get("passed"))
        and not (item["number"] in failed_number_set(review) and not failed_number_reentry_allowed(item, review))
    ]
    selected = []
    while len(selected) < size and pool:
        best = max(
            pool,
            key=lambda item: (
                micro_confidence_score(item, review, selected),
                int((item.get("cross_validation") or {}).get("passed_count") or 0),
                float(item.get("model_probability_percent", 0) or 0),
                -int(item["number"]),
            ),
        )
        selected.append(best["number"])
        pool.remove(best)
    return sorted(selected)


def short_pack_precision_components(item, review=None, selected=None):
    selected = selected or []
    number = int(item["number"])
    rank = int(item.get("rank") or 99)
    cross = item.get("cross_validation", {}) or {}
    passed = int(cross.get("passed_count") or 0)
    total = int(cross.get("total_count") or 0) or 1
    posterior = float((item.get("hit_through_calibration") or {}).get("posterior_hit_rate", BASE_PROBABILITY) or BASE_PROBABILITY)
    objective_edge = float((item.get("objective_feature_calibration") or {}).get("objective_edge", 0.0) or 0.0)
    probability = float(item.get("model_probability_percent", 0) or 0)
    recall_score = recall_priority_score(item, review)
    stability_count = int(item.get("stability_count", 0) or 0)
    source_count = int(item.get("source_model_count", 0) or len(item.get("model_sources", [])))
    rank_score = max(0.0, (12 - rank) / 11) if rank <= 12 else max(0.0, (25 - rank) / 26)
    posterior_score = max(0.0, min(1.0, (posterior - 0.075) / 0.115))
    objective_score = max(0.0, min(1.0, (objective_edge + 0.060) / 0.150))
    probability_score = max(0.0, min(1.0, probability / 18.72))
    cross_score = max(0.0, min(1.0, passed / total))
    stability_score = max(0.0, min(1.0, stability_count / 5))
    source_score = max(0.0, min(1.0, source_count / 8))
    base_score = float(item.get("score", 0) or 0)
    live_adjustment = float((item.get("precision_calibration") or {}).get("adjustment", 0.0) or 0.0)
    leakage_bonus = 0.055 if (item.get("top9_leakage_lock") or {}).get("status") == "promoted" else 0.0
    high_confidence_bonus = 0.045 if item.get("high_confidence") else 0.0
    front9_bonus = 0.030 if rank <= 9 else 0.0
    recall_bonus = 0.030 if recall_score >= 0.55 else 0.0
    score = (
        base_score * 0.22
        + probability_score * 0.13
        + posterior_score * 0.17
        + objective_score * 0.14
        + cross_score * 0.15
        + stability_score * 0.08
        + recall_score * 0.07
        + rank_score * 0.07
        + source_score * 0.05
        + live_adjustment * 0.70
        + leakage_bonus
        + high_confidence_bonus
        + front9_bonus
        + recall_bonus
    )
    penalty = diversity_penalty(selected, number) * 0.85
    if item.get("repeat_guard") and not item["repeat_guard"].get("passed"):
        penalty += 0.20
    if previous_guard_blocks_item(item):
        penalty += 0.22
    if number in failed_number_set(review) and not failed_number_reentry_allowed(item, review):
        penalty += 0.20
    condition_count = sum(
        1 for passed_condition in [
            base_score >= 0.68,
            probability_score >= 0.84,
            posterior >= BASE_PROBABILITY + 0.006,
            objective_edge >= -0.005,
            cross_score >= 0.45,
            stability_count >= 2,
            recall_score >= 0.46,
            source_count >= 4,
            rank <= 9,
            item.get("high_confidence"),
        ]
        if passed_condition
    )
    final_score = max(0.0, min(1.45, score - penalty))
    return {
        "short_pack_precision_score": round(final_score, 4),
        "base_score": round(base_score, 4),
        "probability_score": round(probability_score, 4),
        "posterior_hit_rate": round(posterior, 4),
        "posterior_score": round(posterior_score, 4),
        "objective_edge": round(objective_edge, 4),
        "objective_score": round(objective_score, 4),
        "cross_validation_ratio": round(cross_score, 4),
        "cross_validation_passed": passed,
        "stability_count": stability_count,
        "recall_priority": round(recall_score, 4),
        "source_model_count": source_count,
        "rank_score": round(rank_score, 4),
        "condition_count": condition_count,
        "selection_penalty": round(penalty, 4),
        "model": "short_pack_multi_model_arbitration_v1",
    }


def short_pack_precision_score(item, review=None, selected=None):
    return short_pack_precision_components(item, review, selected)["short_pack_precision_score"]


def short_pack_precision_group(candidates, size, review=None):
    pool = candidates[:24] or candidates[:39]
    selected = []
    while len(selected) < size and pool:
        best = max(
            pool,
            key=lambda item: (
                short_pack_precision_score(item, review, selected),
                int((item.get("cross_validation") or {}).get("passed_count") or 0),
                float((item.get("hit_through_calibration") or {}).get("posterior_hit_rate", BASE_PROBABILITY) or BASE_PROBABILITY),
                float(item.get("score", 0) or 0),
                -int(item["number"]),
            ),
        )
        selected.append(best["number"])
        pool.remove(best)
    if len(selected) < size:
        for item in candidates:
            if item["number"] not in selected:
                selected.append(item["number"])
            if len(selected) >= size:
                break
    return sorted(selected[:size])


def short_pack_precision_audit(candidates, review=None, limit=10):
    rows = []
    for item in candidates[:24]:
        components = short_pack_precision_components(item, review, [])
        rows.append({
            "number": item["number"],
            "rank": item.get("rank"),
            "short_pack_precision_score": components["short_pack_precision_score"],
            "micro_confidence_score": round(micro_confidence_score(item, review), 4),
            "score": item.get("score"),
            "probability_percent": item.get("model_probability_percent"),
            "posterior_hit_rate": components["posterior_hit_rate"],
            "objective_edge": components["objective_edge"],
            "cross_validation_passed": components["cross_validation_passed"],
            "stability_count": components["stability_count"],
            "recall_priority": components["recall_priority"],
            "source_model_count": components["source_model_count"],
            "condition_count": components["condition_count"],
            "selection_penalty": components["selection_penalty"],
            "model": components["model"],
        })
    rows.sort(
        key=lambda row: (
            row["short_pack_precision_score"],
            row["condition_count"],
            row["cross_validation_passed"],
            row["posterior_hit_rate"],
            -int(row["number"]),
        ),
        reverse=True,
    )
    return rows[:limit]


def stability_group(candidates, size, review=None):
    failed = failed_number_set(review)
    ranked = sorted(
        candidates[:24],
        key=lambda item: (
            item.get("stability_count", 0),
            item.get("score", 0),
            item.get("confidence_index", 0),
            -item["number"],
        ),
        reverse=True,
    )
    selected = []
    for item in ranked:
        number = item["number"]
        if number in failed:
            continue
        if previous_guard_blocks_item(item):
            continue
        selected.append(number)
        if len(selected) >= size:
            break
    return sorted(selected)


def target_precision_score(item, selected=None, size=9, goal=3):
    selected = selected or []
    hit = item.get("hit_through_calibration", {})
    hit_rate = float(hit.get("posterior_hit_rate", BASE_PROBABILITY))
    edge_ratio = max(-1.0, min(1.0, (hit_rate - BASE_PROBABILITY) / BASE_PROBABILITY))
    zero_hit = item.get("zero_hit_recovery", {})
    zero_hit_score = float(zero_hit.get("recovery_score", 0.0) or 0.0)
    objective = item.get("objective_feature_calibration", {})
    objective_edge = float(objective.get("objective_edge", 0.0) or 0.0)
    objective_score = max(0.0, min(1.0, (objective_edge + 0.08) / 0.18))
    cross = item.get("cross_validation", {})
    passed = int(cross.get("passed_count") or 0)
    total = int(cross.get("total_count") or 0) or 1
    stability = min(int(item.get("stability_count", 0) or 0), 5) / 5
    source_count = min(int(item.get("source_model_count", 0) or len(item.get("model_sources", []))), 8) / 8
    base = (
        float(item.get("score", 0) or 0) * 0.34
        + ((edge_ratio + 1.0) / 2.0) * 0.18
        + objective_score * 0.18
        + zero_hit_score * 0.14
        + (passed / total) * 0.12
        + stability * 0.08
        + source_count * 0.06
    )
    penalty = diversity_penalty(selected, item["number"])
    zone_count = sum(1 for number in selected if zone_label(number) == zone_label(item["number"]))
    tail_count = sum(1 for number in selected if number % 10 == item["number"] % 10)
    if size <= 5:
        penalty += max(0, zone_count - 1) * 0.075
        penalty += max(0, tail_count) * 0.055
    else:
        penalty += max(0, zone_count - 2) * 0.055
        penalty += max(0, tail_count - 1) * 0.040
    if item.get("repeat_guard") and not item["repeat_guard"].get("passed"):
        penalty += 0.18
    if previous_guard_blocks_item(item):
        penalty += 0.22
    if goal >= 3 and zone_count == 0:
        base += 0.020
    return base - penalty


def target_precision_group(candidates, size, goal, review=None):
    failed = failed_number_set(review)
    pool = [
        item for item in candidates[:30]
        if not (item["number"] in failed and not failed_number_reentry_allowed(item, review))
        and not previous_guard_blocks_item(item)
    ]
    if not pool:
        return []
    selected = []
    while len(selected) < size and pool:
        best = max(
            pool,
            key=lambda item: (
                target_precision_score(item, selected, size=size, goal=goal),
                item.get("score", 0),
                item.get("hit_through_calibration", {}).get("posterior_hit_rate", BASE_PROBABILITY),
                -item["number"],
            ),
        )
        selected.append(best["number"])
        pool.remove(best)
    return sorted(selected)


def slump_recall_group(candidates, size, goal, review=None):
    failed = failed_number_set(review)
    pool = [
        item for item in candidates[:39]
        if not (item["number"] in failed and not failed_number_reentry_allowed(item, review))
        and not previous_guard_blocks_item(item)
        and not (item.get("repeat_guard") and not item["repeat_guard"].get("passed"))
    ]
    if not pool:
        return []
    selected = []
    max_zone = 2 if size <= 5 else 3
    max_tail = 1 if size <= 5 else 2
    while len(selected) < size and pool:
        best = max(
            pool,
            key=lambda item: (
                recall_priority_score(item, review)
                + float(item.get("score", 0) or 0) * 0.28
                + float((item.get("hit_through_calibration") or {}).get("posterior_hit_rate", BASE_PROBABILITY)) * 0.18
                - diversity_penalty(selected, item["number"]) * (1.55 if goal >= 2 else 1.05)
                - (0.09 if sum(1 for n in selected if zone_label(n) == zone_label(item["number"])) >= max_zone else 0)
                - (0.07 if sum(1 for n in selected if n % 10 == item["number"] % 10) >= max_tail else 0),
                item.get("cross_validation", {}).get("passed_count", 0),
                -item["number"],
            ),
        )
        selected.append(best["number"])
        pool.remove(best)

    maps = recall_signal_maps(review)
    priority_zones = [
        zone for zone, _ in sorted(
            {
                **maps["missed_zones"],
                **{zone: maps["missed_zones"].get(zone, 0) + maps["monthly_zones"].get(zone, 0) for zone in maps["monthly_zones"]},
            }.items(),
            key=lambda pair: pair[1],
            reverse=True,
        )
    ]
    score_map = {item["number"]: recall_priority_score(item, review) + float(item.get("score", 0) or 0) * 0.25 for item in candidates}
    for zone in priority_zones[:4]:
        if len(selected) < min(size, 4):
            break
        if any(zone_label(number) == zone for number in selected):
            continue
        zone_item = next(
            (
                item for item in candidates[:39]
                if zone_label(item["number"]) == zone
                and item["number"] not in selected
                and recall_priority_score(item, review) >= 0.42
                and not previous_guard_blocks_item(item)
            ),
            None,
        )
        if not zone_item:
            continue
        replace_number = min(selected, key=lambda number: score_map.get(number, 0))
        if score_map.get(zone_item["number"], 0) >= score_map.get(replace_number, 0) * 0.72:
            selected.remove(replace_number)
            selected.append(zone_item["number"])
    return sorted(selected[:size])


def group_by_variant(key, candidates, review=None, variant=None):
    if key == "strong_single":
        if variant == "short_pack_precision":
            return short_pack_precision_group(candidates, 1, review)
        if variant == "micro_confidence":
            return micro_confidence_group(candidates, 1, review)
        if variant == "slump_recall":
            return slump_recall_group(candidates, 1, 1, review)
        if variant == "target_precision":
            return target_precision_group(candidates, 1, 1, review)
        if variant == "single_precision":
            return single_precision_group(candidates, review)
        if variant == "top_rank":
            return top_rank_group(candidates, 1, review)
        if variant == "stability":
            return stability_group(candidates, 1, review)
        return strong_single_group(candidates, review)
    if key == "five_hit_two":
        if variant == "slump_recall":
            return slump_recall_group(candidates, 5, 2, review)
        if variant == "target_precision":
            return target_precision_group(candidates, 5, 2, review)
        if variant == "dedicated":
            return five_hit_two_group(candidates, review)
        if variant == "top_rank":
            return top_rank_group(candidates, 5, review)
        if variant == "stability":
            return stability_group(candidates, 5, review)
        return target_precision_group(candidates, 5, 2, review)
    if key == "nine_hit_three":
        if variant == "slump_recall":
            return slump_recall_group(candidates, 9, 3, review)
        if variant == "target_precision":
            return target_precision_group(candidates, 9, 3, review)
        if variant == "dedicated":
            return nine_hit_three_group(candidates, review)
        if variant == "top_rank":
            return top_rank_group(candidates, 9, review)
        if variant == "stability":
            return stability_group(candidates, 9, review)
        return target_precision_group(candidates, 9, 3, review)
    size_by_key = {"two_hit_one": 2, "three_hit_one": 3}
    goal_by_key = {"two_hit_one": 1, "three_hit_one": 1}
    if variant == "short_pack_precision":
        return short_pack_precision_group(candidates, size_by_key.get(key, 5), review)
    if variant == "micro_confidence":
        return micro_confidence_group(candidates, size_by_key.get(key, 5), review)
    if variant == "slump_recall":
        return slump_recall_group(candidates, size_by_key.get(key, 5), goal_by_key.get(key, 1), review)
    if variant == "target_precision":
        return target_precision_group(candidates, size_by_key.get(key, 5), goal_by_key.get(key, 1), review)
    return optimized_group(candidates, size_by_key.get(key, 5), review)


def top10_promotion_audit(candidates, review=None):
    rolling = (review or {}).get("rolling_adjustment", {})
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    missed_actual_numbers = {int(item.get("number")) for item in rolling.get("missed_actual_numbers", []) if item.get("number")}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    promotions = []
    blocked_by_repeat_guard = []
    for rank, item in enumerate(candidates[10:25], 11):
        reasons = set(item.get("reasons", []))
        if item["number"] in repeated_failed_numbers:
            continue
        repeat_info = item.get("repeat_guard")
        if repeat_info and not repeat_info.get("passed"):
            blocked_by_repeat_guard.append(
                {
                    "number": item["number"],
                    "current_rank": rank,
                    "score": item.get("score"),
                    "reason": "latest-draw repeat did not pass repeat guard",
                }
            )
            continue
        should_promote = (
            bool(reasons & boosted_reasons)
            or item["number"] in late_hit_numbers
            or item["number"] in missed_actual_numbers
            or item.get("stability_count", 0) >= 4
        )
        if should_promote:
            promotions.append(
                {
                    "number": item["number"],
                    "current_rank": rank,
                    "score": item.get("score"),
                    "confidence_index": item.get("confidence_index"),
                    "stability_count": item.get("stability_count", 0),
                    "reasons": item.get("reasons", []),
                    "action": "promote_watch_to_top10_boundary",
                }
            )
    return {
        "policy": "promote_11_to_25_when_late_hit_missed_actual_or_stability_is_detected_and_repeat_guard_passes",
        "promotion_candidates": promotions,
        "promotion_count": len(promotions),
        "blocked_by_repeat_guard": blocked_by_repeat_guard[:12],
    }


def apply_top10_boundary_promotion(candidates, review=None):
    if len(candidates) < 11:
        return candidates
    rolling = (review or {}).get("rolling_adjustment", {})
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    missed_actual_numbers = {int(item.get("number")) for item in rolling.get("missed_actual_numbers", []) if item.get("number")}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    promoted = list(candidates)
    for source_index in range(10, min(25, len(promoted))):
        item = promoted[source_index]
        if item["number"] in repeated_failed_numbers and not failed_number_reentry_allowed(item, review):
            continue
        if previous_guard_blocks_item(item):
            continue
        if item.get("repeat_guard") and not item["repeat_guard"].get("passed"):
            continue
        reasons = set(item.get("reasons", []))
        should_promote = (
            bool(reasons & boosted_reasons)
            or item["number"] in late_hit_numbers
            or item["number"] in missed_actual_numbers
            or item.get("stability_count", 0) >= 4
        )
        if not should_promote:
            continue
        replace_index = min(
            range(5, min(10, len(promoted))),
            key=lambda index: (
                promoted[index].get("score", 0),
                promoted[index].get("confidence_index", 0),
            ),
        )
        replace_score = promoted[replace_index].get("score", 0) or 0
        item_score = item.get("score", 0) or 0
        recall_priority = recall_priority_score(item, review)
        if (item["number"] in late_hit_numbers or item["number"] in missed_actual_numbers) and recall_priority >= 0.55:
            threshold = 0.82
        elif item["number"] in late_hit_numbers or item["number"] in missed_actual_numbers:
            threshold = 0.88
        elif item.get("stability_count", 0) >= 4:
            threshold = 0.94
        else:
            threshold = 1.0
        if replace_score and item_score >= replace_score * threshold:
            promoted[replace_index], promoted[source_index] = promoted[source_index], promoted[replace_index]
    for rank, item in enumerate(promoted, 1):
        item["rank"] = rank
    return promoted


def top9_leakage_score(item, review=None):
    maps = recall_signal_maps(review)
    rolling = (review or {}).get("rolling_adjustment", {}) or {}
    boosted_reasons = {row.get("reason") for row in rolling.get("boosted_reasons", [])}
    number = int(item["number"])
    reasons = set(item.get("reasons", []))
    cross = item.get("cross_validation", {}) or {}
    passed = int(cross.get("passed_count") or 0)
    total = int(cross.get("total_count") or 0) or 1
    posterior = float((item.get("hit_through_calibration") or {}).get("posterior_hit_rate", BASE_PROBABILITY) or BASE_PROBABILITY)
    posterior_score = max(0.0, min(1.0, (posterior - 0.075) / 0.13))
    recall_score = recall_priority_score(item, review)
    stability_score = min(int(item.get("stability_count", 0) or 0), 5) / 5
    signal_bonus = 0.0
    if number in maps["late_numbers"]:
        signal_bonus += 0.145
    if number in maps["missed_numbers"]:
        signal_bonus += 0.125
    if number in maps["monthly_numbers"]:
        signal_bonus += 0.095
    if number % 10 in maps["missed_tails"] or number % 10 in maps["monthly_tails"]:
        signal_bonus += 0.035
    if zone_label(number) in maps["missed_zones"] or zone_label(number) in maps["monthly_zones"]:
        signal_bonus += 0.045
    if reasons & boosted_reasons:
        signal_bonus += 0.060
    penalty = 0.0
    repeated_count = maps["repeated_failed"].get(number, 0)
    if repeated_count >= 5 and not failed_number_reentry_allowed(item, review):
        penalty += min(0.16, repeated_count * 0.018)
    if item.get("repeat_guard") and not item["repeat_guard"].get("passed"):
        penalty += 0.20
    if previous_guard_blocks_item(item):
        penalty += 0.18
    return max(0.0, min(1.35, (
        float(item.get("score", 0) or 0) * 0.34
        + recall_score * 0.28
        + posterior_score * 0.12
        + (passed / total) * 0.10
        + stability_score * 0.06
        + signal_bonus
        - penalty
    )))


def apply_top9_leakage_lock(candidates, review=None):
    if len(candidates) < 10:
        return candidates, {
            "status": "not_available",
            "reason": "candidate_count_below_top9_boundary",
            "swaps": [],
        }
    rolling = (review or {}).get("rolling_adjustment", {}) or {}
    recent = rolling.get("recent_performance", {}) or {}
    monthly = rolling.get("monthly_review", {}) or (review or {}).get("monthly_review", {}) or {}
    rank_buckets = monthly.get("rank_buckets", {}) or {}
    top15_gap = max(0.0, float(recent.get("last5_top15_avg") or 0) - float(recent.get("last5_top10_avg") or 0))
    top10_gap = max(0.0, float(recent.get("last5_top10_avg") or 0) - float(recent.get("last5_top5_avg") or 0))
    late_bucket_pressure = int(rank_buckets.get("11-15", 0) or 0)
    monthly_late_rate = float(monthly.get("late_or_missing_rate") or 0)
    monthly_front_rate = float(monthly.get("front_hit_rate") or 0)
    critical_recall = (
        monthly.get("status") == "critical_recall_gap"
        or monthly_late_rate >= 0.50
        or (monthly_front_rate and monthly_front_rate <= 0.34)
    )
    status = "critical" if critical_recall else "triggered" if (top15_gap >= 0.25 or top10_gap >= 0.45 or late_bucket_pressure >= 4) else "watch"
    promoted = list(candidates)
    swaps = []
    max_swaps = 4 if status == "critical" else 3 if status == "triggered" else 1
    source_end = 25 if status == "critical" else 18

    for source_index in range(9, min(source_end, len(promoted))):
        if len(swaps) >= max_swaps:
            break
        item = promoted[source_index]
        if item.get("repeat_guard") and not item["repeat_guard"].get("passed"):
            continue
        if previous_guard_blocks_item(item):
            continue
        if item["number"] in failed_number_set(review) and not failed_number_reentry_allowed(item, review):
            continue
        candidate_score = top9_leakage_score(item, review)
        minimum_score = 0.50 if status == "critical" else 0.58 if status == "triggered" else 0.66
        if candidate_score < minimum_score:
            continue

        replace_index = min(
            range(3, min(9, len(promoted))),
            key=lambda index: (
                top9_leakage_score(promoted[index], review),
                recall_priority_score(promoted[index], review),
                promoted[index].get("score", 0),
            ),
        )
        replace = promoted[replace_index]
        replace_score = top9_leakage_score(replace, review)
        source_rank = source_index + 1
        score_ratio_floor = 0.58 if status == "critical" else 0.70
        score_ratio_ok = float(item.get("score", 0) or 0) >= float(replace.get("score", 0) or 0) * score_ratio_floor
        leakage_edge_ok = candidate_score >= replace_score + (0.015 if status == "critical" else 0.030 if status == "triggered" else 0.055)
        recall_edge_ok = recall_priority_score(item, review) >= recall_priority_score(replace, review) + (0.020 if status == "critical" else 0.040)
        cross_ok = int((item.get("cross_validation") or {}).get("passed_count") or 0) >= 4
        leakage_floor_ok = candidate_score >= replace_score * (0.88 if status == "critical" else 0.94 if status == "triggered" else 0.98)
        if not (score_ratio_ok and leakage_floor_ok and (leakage_edge_ok or recall_edge_ok or cross_ok)):
            continue

        item["reasons"] = (item.get("reasons", []) + ["\u4e5d\u78bc\u5167\u547d\u4e2d\u6821\u6b63"])[:4]
        item["top9_leakage_lock"] = {
            "status": "promoted",
            "from_rank": source_rank,
            "to_rank": replace_index + 1,
            "leakage_score": round(candidate_score, 4),
            "replaced_number": replace["number"],
            "replaced_leakage_score": round(replace_score, 4),
        }
        swaps.append({
            "promoted": item["number"],
            "from_rank": source_rank,
            "to_rank": replace_index + 1,
            "replaced": replace["number"],
            "promoted_leakage_score": round(candidate_score, 4),
            "replaced_leakage_score": round(replace_score, 4),
            "reason": "pull_rank_10_to_15_signal_inside_top9",
        })
        promoted[replace_index], promoted[source_index] = promoted[source_index], promoted[replace_index]

    for rank, item in enumerate(promoted, 1):
        item["rank"] = rank
        probability_value = conservative_probability_percent(item["score"], rank)
        item["model_probability_percent"] = probability_value
        confidence = confidence_profile(
            item["score"],
            item["confidence_index"],
            probability_value,
            item.get("model_sources", []),
            item.get("cross_validation", {}),
            rank,
        )
        item["confidence_profile"] = confidence
        item["confidence_badges"] = confidence["badges"]
        item["confidence_level"] = confidence["level"]
        item["confidence_label"] = confidence["label"]
        item["high_confidence"] = confidence["is_high_confidence"]

    return promoted, {
        "status": status,
        "method": "top9_late_hit_leakage_lock",
        "target": "keep validated high-hit signals inside rank 1-9 instead of leaking to rank 10-15",
        "last5_top10_minus_top5_gap": round(top10_gap, 3),
        "last5_top15_minus_top10_gap": round(top15_gap, 3),
        "monthly_front_hit_rate": round(monthly_front_rate, 3),
        "monthly_late_or_missing_rate": round(monthly_late_rate, 3),
        "monthly_rank_11_15_hits": late_bucket_pressure,
        "swap_count": len(swaps),
        "swaps": swaps,
        "policy": "critical month mode pulls validated rank 10-25 recall signals into the front nine; normal mode pulls rank 10-15 only",
    }


def empty_pack(name, goal, reason):
    return {
        "name": name,
        "hit_goal": goal,
        "numbers": [],
        "score_sum": 0,
        "avg_score": 0,
        "status": "withheld",
        "withheld_reason": reason,
        "theoretical_probability": pack_probability(0, goal),
        "zones": {},
        "tails": {},
    }


def watch_pack(name, goal, numbers, score_map, reason):
    if not numbers:
        return empty_pack(name, goal, reason)
    probability = pack_probability(len(numbers), goal)
    return {
        "name": name,
        "hit_goal": goal,
        "numbers": sorted(numbers),
        "score_sum": round(sum(score_map[n] for n in numbers), 4),
        "avg_score": round(sum(score_map[n] for n in numbers) / len(numbers), 4),
        "status": "research_prediction",
        "official_release": False,
        "withheld_reason": reason,
        "release_note": "daily research prediction is always provided, but official confidence gate did not pass",
        "theoretical_probability": probability,
        "zones": Counter(zone_label(n) for n in numbers),
        "tails": Counter(n % 10 for n in numbers),
        "governance": {},
    }


def pack_recent_governance(draws, rounds=120):
    if len(draws) < 150:
        return {
            "status": "insufficient_data",
            "rounds": 0,
            "release_light": "red",
            "message": "historical sample is not enough for strict pack release",
            "pack_stats": {},
        }

    pack_specs = {
        "strong_single": {"size": 1, "goal": 1, "min_pass_rate": 0.14, "min_avg_hits": 0.14},
        "two_hit_one": {"size": 2, "goal": 1, "min_pass_rate": 0.25, "min_avg_hits": 0.25},
        "three_hit_one": {"size": 3, "goal": 1, "min_pass_rate": 0.34, "min_avg_hits": 0.34},
        "five_hit_two": {"size": 5, "goal": 2, "min_pass_rate": 0.14, "min_avg_hits": 0.72},
        "nine_hit_three": {"size": 9, "goal": 3, "min_pass_rate": 0.12, "min_avg_hits": 1.16},
    }
    pack_variants = {
        "strong_single": ["short_pack_precision", "micro_confidence", "target_precision", "single_precision", "slump_recall", "dedicated", "top_rank", "stability"],
        "two_hit_one": ["short_pack_precision", "micro_confidence", "target_precision", "slump_recall", "dedicated"],
        "three_hit_one": ["short_pack_precision", "micro_confidence", "target_precision", "slump_recall", "dedicated"],
        "five_hit_two": ["target_precision", "slump_recall", "dedicated", "top_rank", "stability"],
        "nine_hit_three": ["target_precision", "slump_recall", "dedicated", "top_rank", "stability"],
    }
    start = max(120, len(draws) - rounds - 1)
    stats = {
        key: {
            variant: {"rounds": 0, "passes": 0, "hits": 0, "zero_hits": 0}
            for variant in pack_variants.get(key, ["dedicated"])
        }
        for key in pack_specs
    }

    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        historical_candidates, _ = score_numbers(train, None, include_dependency=False)
        for key, spec in pack_specs.items():
            for variant in stats[key]:
                numbers = group_by_variant(key, historical_candidates, None, variant)
                hits = len(set(numbers) & actual)
                stats[key][variant]["rounds"] += 1
                stats[key][variant]["hits"] += hits
                stats[key][variant]["passes"] += 1 if hits >= spec["goal"] else 0
                stats[key][variant]["zero_hits"] += 1 if hits == 0 else 0

    pack_stats = {}
    allowed_count = 0
    for key, spec in pack_specs.items():
        variant_results = {}
        for variant, item in stats[key].items():
            rounds_done = item["rounds"] or 1
            pass_rate = item["passes"] / rounds_done
            avg_hits = item["hits"] / rounds_done
            zero_rate = item["zero_hits"] / rounds_done
            variant_results[variant] = {
                "rounds": item["rounds"],
                "pass_rate": round(pass_rate, 3),
                "avg_hits": round(avg_hits, 3),
                "zero_hit_rate": round(zero_rate, 3),
            }
        best_variant, best_result = max(
            variant_results.items(),
            key=lambda pair: (pair[1]["pass_rate"], pair[1]["avg_hits"], -pair[1]["zero_hit_rate"]),
        )
        pass_rate = best_result["pass_rate"]
        avg_hits = best_result["avg_hits"]
        zero_rate = best_result["zero_hit_rate"]
        passed = pass_rate >= spec["min_pass_rate"] and avg_hits >= spec["min_avg_hits"]
        allowed_count += 1 if passed else 0
        pack_stats[key] = {
            "rounds": best_result["rounds"],
            "goal": spec["goal"],
            "pass_rate": pass_rate,
            "avg_hits": avg_hits,
            "zero_hit_rate": zero_rate,
            "min_pass_rate": spec["min_pass_rate"],
            "min_avg_hits": spec["min_avg_hits"],
            "passed": passed,
            "best_variant": best_variant,
            "variant_results": variant_results,
        }

    release_light = "green" if allowed_count >= 4 else "yellow" if allowed_count >= 2 else "red"
    governance_rounds = max((item.get("rounds", 0) for item in pack_stats.values()), default=0)
    return {
        "status": "evaluated",
        "rounds": governance_rounds,
        "release_light": release_light,
        "allowed_pack_count": allowed_count,
        "pack_stats": pack_stats,
        "message": "strict walk-forward governance with daily variant tournament; lower confidence packs are still output as research predictions",
    }


def strict_candidate_pool(candidates, min_score=0.64, min_confidence=81.0, min_stability=1):
    return [
        item for item in candidates
        if item.get("score", 0) >= min_score
        and item.get("confidence_index", 0) >= min_confidence
        and item.get("stability_count", 0) >= min_stability
    ]


def strong_packs(candidates, review=None, governance=None):
    score_map = {item["number"]: item["score"] for item in candidates}
    candidate_map = {item["number"]: item for item in candidates}
    strict_pool = strict_candidate_pool(candidates)
    qualified_numbers = {item["number"] for item in strict_pool}
    governance = governance or {"pack_stats": {}}
    pack_stats = governance.get("pack_stats", {})
    variant_labels = {
        "short_pack_precision": "short_pack_multi_model_arbitration",
        "micro_confidence": "micro_confidence_short_pack",
        "target_precision": "target_precision_gate",
        "single_precision": "single_precision_gate",
        "slump_recall": "slump_recall_coverage",
        "dedicated": "dedicated_goal_model",
        "top_rank": "top_rank_baseline",
        "stability": "stability_consensus",
    }

    def pack(name, goal, numbers):
        if not numbers:
            return empty_pack(name, goal, "no candidate passed strict confidence gate")
        probability = pack_probability(len(numbers), goal)
        avg_score = sum(score_map[n] for n in numbers) / len(numbers)
        return {
            "name": name,
            "hit_goal": goal,
            "numbers": numbers,
            "score_sum": round(sum(score_map[n] for n in numbers), 4),
            "avg_score": round(avg_score, 4),
            "status": "released",
            "official_release": True,
            "theoretical_probability": probability,
            "zones": Counter(zone_label(n) for n in numbers),
            "tails": Counter(n % 10 for n in numbers),
            "governance": {},
        }

    specs = {
        "strong_single": ("\u6700\u5f37\u55ae\u652f", 1, 1, 0.78, 1),
        "two_hit_one": ("\u6700\u5f372\u4e2d1", 1, 2, 0.76, 2),
        "three_hit_one": ("\u6700\u5f373\u4e2d1", 1, 3, 0.72, 1),
        "five_hit_two": ("\u6700\u5f375\u4e2d2", 2, 5, 0.68, 1),
        "nine_hit_three": ("\u6700\u5f379\u4e2d3", 3, 9, 0.62, 0),
    }
    packs = {}
    short_pack_keys = {"strong_single", "two_hit_one", "three_hit_one"}
    for key, (name, goal, size, min_avg_score, min_stability) in specs.items():
        recent_stat = pack_stats.get(key, {})
        variant = recent_stat.get("best_variant", "dedicated")
        if key in short_pack_keys:
            variant = "short_pack_precision"
        elif key == "nine_hit_three" and critical_front_nine_active(review):
            variant = "top_rank"
        elif recall_emergency_active(review) and key in {"five_hit_two", "nine_hit_three"}:
            variant = "slump_recall"
        allowed_pool = [
            item for item in candidates[:30]
            if item["number"] in qualified_numbers or (
                item.get("score", 0) >= min_avg_score and item.get("stability_count", 0) >= min_stability
            )
        ]
        selection_pool = candidates[:30] if key in short_pack_keys else allowed_pool
        if len(allowed_pool) < size and key not in short_pack_keys:
            fallback_pool = candidates[: max(size, 12)]
            fallback_numbers = group_by_variant(key, fallback_pool, review, variant)
            if len(fallback_numbers) < size and fallback_pool:
                fallback_numbers = top_rank_group(fallback_pool, size, review)
            packs[key] = watch_pack(name, goal, fallback_numbers, score_map, "strict confidence pool failed; output as daily research prediction")
            packs[key]["governance"] = recent_stat
            packs[key]["selection_variant"] = variant
            packs[key]["selection_model"] = variant_labels.get(variant, variant)
            continue
        numbers = group_by_variant(key, selection_pool, review, variant)
        if not numbers and selection_pool:
            numbers = [selection_pool[0]["number"]] if size == 1 else optimized_group(selection_pool, size, review)
        avg_score = sum(score_map[n] for n in numbers) / len(numbers) if numbers else 0
        weak_numbers = [
            n for n in numbers
            if previous_guard_blocks_item(candidate_map[n])
        ]
        if key in short_pack_keys:
            packs[key] = pack(name, goal, sorted(numbers))
            packs[key]["release_note"] = "short pack is always calculated every fresh draw by multi-model arbitration"
        elif recent_stat and not recent_stat.get("passed"):
            packs[key] = watch_pack(name, goal, numbers, score_map, "recent walk-forward pack performance did not pass official gate; output as daily research prediction")
        elif avg_score < min_avg_score:
            packs[key] = watch_pack(name, goal, numbers, score_map, "average score is below strict release threshold; output as daily research prediction")
        elif weak_numbers:
            packs[key] = watch_pack(name, goal, numbers, score_map, "contains previous prediction re-entry numbers that failed the strict gate; output as daily research prediction")
        else:
            packs[key] = pack(name, goal, sorted(numbers))
        packs[key]["governance"] = recent_stat
        packs[key]["selection_variant"] = variant
        packs[key]["selection_model"] = variant_labels.get(variant, variant)
        if key in short_pack_keys:
            audit_rows = short_pack_precision_audit(candidates, review, limit=10)
            selected_set = set(int(number) for number in packs[key].get("numbers", []))
            packs[key]["short_pack_precision_audit"] = audit_rows
            packs[key]["micro_confidence_audit"] = audit_rows[:8]
            packs[key]["selected_number_audit"] = [
                row for row in audit_rows if int(row.get("number")) in selected_set
            ]
            packs[key]["daily_output_required"] = True
            packs[key]["selection_rule"] = "short_pack_multi_model_arbitration_v1"

    wheel = build_covering_wheel(packs["nine_hit_three"].get("numbers", []), ticket_size=5, cover_size=3, max_tickets=12)
    packs["nine_hit_three"]["wheel_tickets"] = wheel["tickets"]
    packs["nine_hit_three"]["wheel_coverage"] = wheel["coverage"]
    return packs


def combinations_count(n, r):
    if r < 0 or r > n:
        return 0
    return math.comb(n, r)


def pack_probability(pool_size, hit_goal):
    total = combinations_count(NUMBER_MAX, DRAW_SIZE)
    favorable = 0
    for hits in range(hit_goal, min(pool_size, DRAW_SIZE) + 1):
        favorable += combinations_count(pool_size, hits) * combinations_count(NUMBER_MAX - pool_size, DRAW_SIZE - hits)
    return {
        "hit_goal": hit_goal,
        "pool_size": pool_size,
        "probability": round(favorable / total, 6) if total else 0,
        "odds_1_in": round(total / favorable, 2) if favorable else None,
    }


def decisive_battle_decision(candidates, packs, release_gate, slump_recall, unlikely):
    def pack_numbers(key, fallback_size):
        numbers = list((packs.get(key, {}) or {}).get("numbers") or [])
        if numbers:
            return sorted(int(number) for number in numbers)
        return sorted(int(item["number"]) for item in candidates[:fallback_size])

    def number_profile(number):
        item = next((row for row in candidates if int(row["number"]) == int(number)), {})
        return {
            "number": int(number),
            "rank": item.get("rank"),
            "score": item.get("score"),
            "probability_percent": item.get("model_probability_percent"),
            "confidence": item.get("confidence_index"),
            "sources": item.get("model_sources", []),
            "selection_model": (packs.get("strong_single", {}) or {}).get("selection_model"),
        }

    front9 = [int(item["number"]) for item in candidates[:9]]
    top10 = [int(item["number"]) for item in candidates[:10]]
    top15 = [int(item["number"]) for item in candidates[:15]]
    avoid_numbers = [int(item["number"]) for item in (unlikely.get("numbers", []) or [])[:10]]
    status = release_gate.get("status")
    main_targets_passed = bool(release_gate.get("main_targets_passed"))
    recent_passed = bool(release_gate.get("recent_performance_passed"))
    slump_triggered = slump_recall.get("status") == "triggered"
    release_light = release_gate.get("precision_governor_release_light")
    if status == "official" and main_targets_passed and recent_passed:
        grade = "A"
        action = "execute_primary_plan"
    elif slump_triggered or release_light in {"yellow", "green"}:
        grade = "B"
        action = "execute_slump_recall_control_plan"
    else:
        grade = "C"
        action = "execute_defensive_control_plan"

    primary_single = pack_numbers("strong_single", 1)[:1]
    primary_two = pack_numbers("two_hit_one", 2)[:2]
    primary_three = pack_numbers("three_hit_one", 3)[:3]
    primary_five = pack_numbers("five_hit_two", 5)[:5]
    primary_nine = pack_numbers("nine_hit_three", 9)[:9]
    if slump_triggered or release_light in {"yellow", "green"}:
        primary_nine = front9
    attack_core = []
    attack_core_target = 9
    for group in [primary_single, primary_two, primary_three, primary_five, primary_nine, front9, top10]:
        for number in group:
            if number not in attack_core and number not in avoid_numbers[:5]:
                attack_core.append(number)
    attack_core = attack_core[:attack_core_target]
    if len(attack_core) < attack_core_target:
        for number in top15:
            if number not in attack_core and number not in avoid_numbers[:5]:
                attack_core.append(number)
            if len(attack_core) >= attack_core_target:
                break
    high_confidence_numbers = []
    for item in candidates[:15]:
        number = int(item["number"])
        recall_score = item.get("slump_recall_coverage", {}).get("priority_score", 0)
        cross_passed = item.get("cross_validation", {}).get("passed_count", 0)
        if number in avoid_numbers[:5]:
            continue
        if (
            number in attack_core[:attack_core_target]
            and (
                item.get("high_confidence")
                or float(item.get("score", 0) or 0) >= 0.78
                or float(recall_score or 0) >= 0.62
                or int(cross_passed or 0) >= 3
            )
        ):
            high_confidence_numbers.append({
                "number": number,
                "rank": item.get("rank"),
                "score": item.get("score"),
                "probability_percent": item.get("model_probability_percent"),
                "confidence": item.get("confidence_index"),
                "recall_priority": round(float(recall_score or 0), 4),
                "cross_validation_passed": cross_passed,
                "reason": "high_score_or_recall_or_cross_validation",
        })
        if len(high_confidence_numbers) >= 5:
            break
    if not high_confidence_numbers:
        for number in attack_core[:3]:
            item = next((row for row in candidates if int(row["number"]) == int(number)), {})
            high_confidence_numbers.append({
                "number": int(number),
                "rank": item.get("rank"),
                "score": item.get("score"),
                "probability_percent": item.get("model_probability_percent"),
                "confidence": item.get("confidence_index"),
                "recall_priority": round(float(item.get("slump_recall_coverage", {}).get("priority_score", 0) or 0), 4),
                "cross_validation_passed": item.get("cross_validation", {}).get("passed_count", 0),
                "reason": "decisive_attack_core_fallback",
            })

    return {
        "status": "decisive",
        "action": action,
        "grade": grade,
        "policy": "always_output_model_decision_when_data_is_fresh",
        "primary_single": primary_single,
        "two_hit_one": primary_two,
        "three_hit_one": primary_three,
        "five_hit_two": primary_five,
        "nine_hit_three": primary_nine,
        "front9_precision_core": attack_core[:9],
        "attack_core_top9": attack_core[:9],
        "attack_core_top10": (attack_core[:9] + [number for number in top10 if number not in attack_core[:9]])[:10],
        "precision_target_size": 9,
        "backup_top15": top15,
        "defensive_avoid": avoid_numbers[:10],
        "high_confidence_numbers": high_confidence_numbers,
        "slump_recall_triggered": slump_triggered,
        "main_targets_passed": main_targets_passed,
        "recent_performance_passed": recent_passed,
        "release_gate_status": status,
        "number_profiles": [number_profile(number) for number in attack_core[:9]],
    }


def draw_signature(draw):
    numbers = sorted(draw["numbers"])
    odd = sum(1 for number in numbers if number % 2)
    small = sum(1 for number in numbers if number <= 19)
    zones = Counter(zone_label(number) for number in numbers)
    tails = Counter(number % 10 for number in numbers)
    return {
        "sum": sum(numbers),
        "odd_even": f"{odd}:{DRAW_SIZE - odd}",
        "small_big": f"{small}:{DRAW_SIZE - small}",
        "zones": dict(zones),
        "tails": dict(tails),
        "span": numbers[-1] - numbers[0],
        "consecutive_pairs": sum(1 for left, right in zip(numbers, numbers[1:]) if right - left == 1),
    }


def regime_analysis(draws):
    latest = draw_signature(draws[-1])
    recent = [draw_signature(draw) for draw in draws[-50:]]
    sums = [item["sum"] for item in recent]
    spans = [item["span"] for item in recent]
    latest_sum_z = zscore(latest["sum"], sums)
    latest_span_z = zscore(latest["span"], spans)
    messages = []
    if abs(latest_sum_z) >= 1.5:
        messages.append("\u548c\u503c\u504f\u96e2\u8fd150\u671f\u5e38\u614b")
    if abs(latest_span_z) >= 1.5:
        messages.append("\u8de8\u5ea6\u504f\u96e2\u8fd150\u671f\u5e38\u614b")
    if latest["consecutive_pairs"] >= 2:
        messages.append("\u9023\u865f\u504f\u591a")
    if not messages:
        messages.append("\u672a\u898b\u660e\u986f\u7570\u5e38\u578b\u614b")
    return {
        "latest_signature": latest,
        "sum_zscore": round(latest_sum_z, 3),
        "span_zscore": round(latest_span_z, 3),
        "messages": messages,
    }


def zscore(value, values):
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / max(len(values) - 1, 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (value - mean) / std


def model_audit(backtest_result, review=None):
    top10 = backtest_result.get("top10_avg_hits", 0)
    random_expectation = backtest_result.get("random_top10_expectation", DRAW_SIZE * 10 / NUMBER_MAX)
    edge = top10 - random_expectation
    if review and review.get("severity") == "critical":
        risk = "\u9ad8"
        verdict = "\u6700\u8fd1\u771f\u5be6\u9810\u6e2c\u51fa\u73fe\u91cd\u5927\u5931\u6557\uff0c\u5df2\u555f\u7528\u5931\u6557\u9694\u96e2\u8207\u5206\u6563\u6a21\u5f0f"
    elif edge > 0.08:
        risk = "\u4e2d"
        verdict = "\u56de\u6e2c\u7565\u512a\u65bc\u96a8\u6a5f\uff0c\u4f46\u4ecd\u9700\u6301\u7e8c\u8ffd\u8e64\u771f\u5be6\u7e3e\u6548"
    else:
        risk = "\u9ad8"
        verdict = "\u56de\u6e2c\u512a\u52e2\u5f88\u5c0f\uff0c\u4e0d\u53ef\u904e\u5ea6\u653e\u5927\u4fe1\u5fc3"
    return {
        "risk_level": risk,
        "edge_vs_random": round(edge, 4),
        "verdict": verdict,
    }


def build_covering_wheel(numbers, ticket_size=5, cover_size=3, max_tickets=12):
    numbers = sorted(numbers)
    target_subsets = {tuple(combo) for combo in combinations(numbers, cover_size)}
    ticket_pool = []
    for ticket in combinations(numbers, ticket_size):
        covered = {tuple(combo) for combo in combinations(ticket, cover_size)}
        ticket_pool.append({"ticket": ticket, "covered": covered})

    selected = []
    covered_total = set()
    while ticket_pool and len(selected) < max_tickets and covered_total != target_subsets:
        best = max(
            ticket_pool,
            key=lambda item: (len(item["covered"] - covered_total), balanced_ticket_score(item["ticket"])),
        )
        if not (best["covered"] - covered_total):
            break
        selected.append(list(best["ticket"]))
        covered_total.update(best["covered"])
        ticket_pool.remove(best)

    return {
        "tickets": selected,
        "coverage": {
            "covered": len(covered_total),
            "total": len(target_subsets),
            "rate": round(len(covered_total) / len(target_subsets), 4) if target_subsets else 0,
        },
    }


def balanced_ticket_score(ticket):
    zones = Counter(zone_label(number) for number in ticket)
    tails = Counter(number % 10 for number in ticket)
    zone_penalty = sum(max(0, count - 2) for count in zones.values())
    tail_penalty = sum(max(0, count - 1) for count in tails.values())
    span = max(ticket) - min(ticket)
    return span / NUMBER_MAX - zone_penalty * 0.2 - tail_penalty * 0.1


def industrial_backtest(draws, rounds=180):
    if len(draws) < 140:
        return {"rounds": 0, "top10_avg_hits": 0, "top15_avg_hits": 0}
    start = max(120, len(draws) - rounds - 1)
    top10_hits = 0
    top15_hits = 0
    total = 0
    hit_history = []
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        candidates, _ = score_numbers(train, None, include_dependency=False)
        ranked = [item["number"] for item in candidates]
        round_top10 = len(set(ranked[:10]) & actual)
        round_top15 = len(set(ranked[:15]) & actual)
        top10_hits += round_top10
        top15_hits += round_top15
        hit_history.append({"top10": round_top10, "top15": round_top15})
        total += 1
    random_top10 = DRAW_SIZE * 10 / NUMBER_MAX
    rolling = {}
    for window in [60, 120, 360]:
        sample = hit_history[-window:]
        rolling[str(window)] = {
            "rounds": len(sample),
            "top10_avg_hits": round(sum(item["top10"] for item in sample) / len(sample), 3) if sample else 0,
            "top15_avg_hits": round(sum(item["top15"] for item in sample) / len(sample), 3) if sample else 0,
            "top10_edge_vs_random": round(
                sum(item["top10"] for item in sample) / len(sample) - random_top10, 4
            ) if sample else 0,
        }
    return {
        "rounds": total,
        "top10_avg_hits": round(top10_hits / total, 3) if total else 0,
        "top15_avg_hits": round(top15_hits / total, 3) if total else 0,
        "random_top10_expectation": round(random_top10, 3),
        "rolling_windows": rolling,
    }


def advanced_model_summary(draws):
    models = {
        "markov_chain": markov_chain_scores(draws),
        "time_series": time_series_scores(draws),
        "neural_network": neural_network_scores(draws),
    }
    labels = {
        "markov_chain": "\u99ac\u53ef\u592b\u93c8",
        "time_series": "\u6642\u9593\u5e8f\u5217",
        "neural_network": "\u795e\u7d93\u7db2\u8def",
    }
    rows = []
    vote = Counter()
    for key, scores in models.items():
        ranked = rank_values(scores)[:10]
        vote.update(ranked[:8])
        rows.append({
            "model": key,
            "name": labels[key],
            "top10": ranked,
            "method": {
                "markov_chain": "\u4f9d\u4e0a\u671f\u865f\u78bc\u5efa\u7acb\u72c0\u614b\u8f49\u79fb\u77e9\u9663",
                "time_series": "\u4ee5\u5feb\u6162 EWMA \u8ffd\u8e64\u865f\u78bc\u52d5\u80fd",
                "neural_network": "\u4ee5\u983b\u7387\u3001\u907a\u6f0f\u3001\u8f49\u79fb\u8207\u52d5\u80fd\u505a\u975e\u7dda\u6027\u7d9c\u5408",
            }[key],
        })
    consensus = [number for number, _ in vote.most_common(12)]
    return {
        "models": rows,
        "consensus_top12": consensus,
        "warning": "\u9032\u968e\u6a21\u578b\u53ea\u80fd\u63d0\u4f9b\u8f14\u52a9\u8a55\u5206\uff0c\u5fc5\u9808\u901a\u904e\u56de\u6e2c\u8207\u767c\u5e03\u9580\u6abb\u624d\u80fd\u9032\u5165\u4e3b\u63a8",
    }


def advanced_model_backtest(draws, rounds=120):
    if len(draws) < 140:
        return {"rounds": 0}
    model_names = ["markov_chain", "time_series", "neural_network"]
    totals = {name: {"top10_hits": 0, "rounds": 0} for name in model_names}
    start = max(120, len(draws) - rounds - 1)
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        scores_by_model = {
            "markov_chain": markov_chain_scores(train),
            "time_series": time_series_scores(train),
            "neural_network": neural_network_scores(train),
        }
        for name, scores in scores_by_model.items():
            top10 = set(rank_values(scores)[:10])
            totals[name]["top10_hits"] += len(top10 & actual)
            totals[name]["rounds"] += 1
    random_top10 = DRAW_SIZE * 10 / NUMBER_MAX
    result = {}
    for name, data in totals.items():
        rounds_done = data["rounds"]
        avg_hits = data["top10_hits"] / rounds_done if rounds_done else 0
        result[name] = {
            "rounds": rounds_done,
            "top10_avg_hits": round(avg_hits, 3),
            "top10_edge_vs_random": round(avg_hits - random_top10, 4),
        }
    return {
        "rounds": max(item["rounds"] for item in result.values()) if result else 0,
        "random_top10_expectation": round(random_top10, 3),
        "models": result,
    }


def stability_consensus(draws, base_candidates, review=None):
    snapshots = []
    for cut in [0, 1, 2, 3, 5]:
        if len(draws) - cut < 140:
            continue
        if cut == 0:
            ranked = [item["number"] for item in base_candidates]
        else:
            ranked = [item["number"] for item in score_numbers(draws[:-cut], review)[0]]
        snapshots.append(ranked[:15])
    counts = Counter(number for ranking in snapshots for number in ranking)
    base_score = {item["number"]: item["score"] for item in base_candidates}
    latest_set = set(draws[-1]["numbers"])
    denominator = max(len(snapshots), 1)
    combined = {
        number: base_score[number] * 0.62 + (counts.get(number, 0) / denominator) * 0.38
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }
    previous_blocked = {
        item["number"] for item in base_candidates
        if previous_guard_blocks_item(item)
    }
    ranked = sorted(
        range(NUMBER_MIN, NUMBER_MAX + 1),
        key=lambda number: (
            number not in previous_blocked,
            number not in latest_set,
            combined[number],
            -number,
        ),
        reverse=True,
    )
    original = {item["number"]: item for item in base_candidates}
    stable_candidates = []
    for number in ranked:
        item = dict(original[number])
        item["stability_count"] = counts.get(number, 0)
        item["stability_rate"] = round(counts.get(number, 0) / denominator, 3)
        item["score"] = round(combined[number], 4)
        item["confidence_index"] = round(50 + min(combined[number], 1) * 49, 1)
        if item["stability_rate"] >= 0.8:
            item["reasons"] = (item.get("reasons", []) + ["\u7a69\u5b9a\u5171\u8b58"])[:4]
        stable_candidates.append(item)
    top10_retention = sum(1 for number in ranked[:10] if counts.get(number, 0) >= max(1, math.ceil(denominator * 0.6))) / 10
    return stable_candidates, {
        "snapshots": len(snapshots),
        "top10_retention": round(top10_retention, 3),
        "consensus_counts": {str(number): counts.get(number, 0) for number in ranked[:15]},
    }


def unlikely_number_analysis(draws, candidates, stability, review=None, limit=12):
    features = build_feature_matrix(draws, review, include_dependency=False)
    score_map = {item["number"]: item["score"] for item in candidates}
    rank_map = {item["number"]: index + 1 for index, item in enumerate(candidates)}
    stability_counts = {int(number): count for number, count in stability.get("consensus_counts", {}).items()}
    latest_set = set(draws[-1]["numbers"])
    previous_blocked = {
        item["number"] for item in candidates
        if previous_guard_blocks_item(item)
    }
    failed = failed_number_set(review)
    repeat_policy = repeat_guard(draws)
    rows = []
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        values = features[number]
        weak_signal_count = sum(
            1 for key in ["freq_20", "freq_50", "freq_100", "ewma_slow", "pair", "tail_zone", "validated_dependency"]
            if values.get(key, 0) < 0.35
        )
        penalty = 0.0
        reasons = []
        if number in previous_blocked:
            penalty += 0.32
            reasons.append("\u6628\u65e5\u9810\u6e2c\u865f\u672a\u9054\u6975\u5f37\u91cd\u5165\u9580\u6abb")
        if number in failed:
            penalty += 0.25
            reasons.append("\u4e0a\u671f\u5931\u6557\u865f\u78bc\u9694\u96e2")
        if number in latest_set:
            if repeat_policy.get(number, {}).get("historical_support"):
                penalty += 0.08
                reasons.append("\u9023\u838a\u5408\u683c\u4f46\u4fdd\u5b88\u98a8\u63a7")
            else:
                penalty += 0.28
                reasons.append("\u9023\u838a\u5b88\u9580\u672a\u901a\u904e")
        if stability_counts.get(number, 0) == 0:
            penalty += 0.16
            reasons.append("\u64fe\u52d5\u6a21\u578b\u7121\u7a69\u5b9a\u5171\u8b58")
        if weak_signal_count >= 5:
            penalty += 0.20
            reasons.append("\u77ed\u4e2d\u9577\u671f\u8207\u95dc\u806f\u6307\u6a19\u504f\u5f31")
        if rank_map.get(number, 99) > 24:
            penalty += 0.15
            reasons.append("Top24\u5916")
        appearance_risk = max(0.0, min(1.0, score_map.get(number, 0.0)))
        avoid_score = max(0.0, min(1.0, (1 - appearance_risk) * 0.48 + penalty))
        if not reasons:
            reasons.append("\u7d9c\u5408\u8a55\u5206\u504f\u5f31")
        rows.append(
            {
                "number": number,
                "avoid_score": round(avoid_score, 4),
                "appearance_score": round(appearance_risk, 4),
                "candidate_rank": rank_map.get(number),
                "stability_count": stability_counts.get(number, 0),
                "weak_signal_count": weak_signal_count,
                "reasons": reasons[:4],
                "warning": "\u4f4e\u6a5f\u7387\u4e0d\u4ee3\u8868\u4e0d\u6703\u958b\u51fa",
            }
        )
    rows.sort(key=lambda item: (item["avoid_score"], item["number"]), reverse=True)
    return {
        "method": "inverse_signal_risk_filter",
        "warning": "\u6b64\u5340\u70ba\u98a8\u63a7\u907f\u958b\u89c0\u5bdf\uff0c\u4e0d\u662f\u7d55\u5c0d\u4e0d\u958b\u4fdd\u8b49",
        "numbers": rows[:limit],
    }


def unlikely_backtest(draws, rounds=120, avoid_size=10):
    if len(draws) < 140:
        return {"rounds": 0}
    start = max(120, len(draws) - rounds - 1)
    total = 0
    accidental_hits = 0
    zero_hit_rounds = 0
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        base_candidates, _ = score_numbers(train, None, include_dependency=False)
        stable = {"consensus_counts": {}}
        avoid = unlikely_number_analysis(train, base_candidates, stable, None, limit=avoid_size)["numbers"]
        avoid_numbers = {item["number"] for item in avoid}
        actual = set(draws[idx + 1]["numbers"])
        hits = len(avoid_numbers & actual)
        accidental_hits += hits
        zero_hit_rounds += 1 if hits == 0 else 0
        total += 1
    random_expectation = DRAW_SIZE * avoid_size / NUMBER_MAX
    return {
        "rounds": total,
        "avoid_size": avoid_size,
        "avg_accidental_hits": round(accidental_hits / total, 3) if total else 0,
        "random_expectation": round(random_expectation, 3),
        "edge_vs_random": round(accidental_hits / total - random_expectation, 4) if total else 0,
        "zero_hit_rate": round(zero_hit_rounds / total, 3) if total else 0,
    }


def compute_industrial_analysis(draws, review=None):
    weights, weight_calibration = adaptive_feature_weights(draws, review)
    lifecycle = model_lifecycle_policy(weight_calibration)
    weights = apply_lifecycle_weight_policy(weights, lifecycle)
    base_candidates, weights = score_numbers(draws, review, weights_override=weights)
    candidates, stability = stability_consensus(draws, base_candidates, review)
    candidates = apply_top10_boundary_promotion(candidates, review)
    candidates, precision_calibration = live_precision_calibration(candidates, review)
    candidates, objective_feature_calibration = apply_objective_feature_calibration(candidates, weight_calibration, review)
    candidates, hit_through_calibration = apply_hit_through_calibration(draws, candidates, review)
    candidates, zero_hit_recovery = apply_zero_hit_recovery_mode(draws, candidates, review)
    candidates, slump_recall_coverage = apply_slump_recall_coverage_mode(draws, candidates, review)
    candidates = apply_top10_boundary_promotion(candidates, review)
    candidates, top9_leakage_lock = apply_top9_leakage_lock(candidates, review)
    pack_governance = pack_recent_governance(draws)
    packs = strong_packs(candidates, review, pack_governance)
    audit = industrial_backtest(draws)
    advanced_models = advanced_model_summary(draws)
    advanced_backtest = advanced_model_backtest(draws)
    _, validated_links = validated_dependency_scores(draws)
    lag_profile = lag_dependency_profile(draws)
    edge = audit.get("top10_avg_hits", 0) - audit.get("random_top10_expectation", DRAW_SIZE * 10 / NUMBER_MAX)
    rolling = audit.get("rolling_windows", {})
    recent_edges = [rolling.get(str(window), {}).get("top10_edge_vs_random", -1) for window in [60, 120]]
    recent_passed = all(value >= 0 for value in recent_edges)
    pack_stats = pack_governance.get("pack_stats", {})
    main_target_passed = (
        pack_stats.get("five_hit_two", {}).get("passed", False)
        and pack_stats.get("nine_hit_three", {}).get("passed", False)
    )
    pack_release_passed = pack_governance.get("release_light") in {"green", "yellow"} and main_target_passed
    release_status = "official" if stability["top10_retention"] >= 0.6 and edge >= 0 and recent_passed and pack_release_passed else "watch_only"
    previous = previous_prediction_set(review)
    top10_overlap = sorted(previous & {item["number"] for item in candidates[:10]})
    top15_overlap = sorted(previous & {item["number"] for item in candidates[:15]})
    reentry_passed = sorted(
        item["number"] for item in candidates
        if item.get("previous_prediction_guard") and item["previous_prediction_guard"].get("passed")
    )
    unlikely = unlikely_number_analysis(draws, candidates, stability, review)
    promotion_audit = top10_promotion_audit(candidates, review)
    release_gate = {
        "status": release_status,
        "precision_governor_release_light": pack_governance.get("release_light"),
        "precision_governor_allowed_pack_count": pack_governance.get("allowed_pack_count"),
        "main_targets_required": ["five_hit_two", "nine_hit_three"],
        "main_targets_passed": main_target_passed,
        "top10_retention_required": 0.6,
        "backtest_edge_required": 0,
        "actual_backtest_edge": round(edge, 4),
        "recent_windows_required": [60, 120],
        "recent_edges": recent_edges,
        "recent_performance_passed": recent_passed,
    }
    decisive_decision = decisive_battle_decision(candidates, packs, release_gate, slump_recall_coverage, unlikely)
    return {
        "engine_version": "industrial_v19_short_pack_multi_model_arbitration",
        "leakage_guard": True,
        "repeat_guard": repeat_guard(draws),
        "previous_prediction_guard": {
            "policy": "prevent_exact_copy_but_allow_single-number_soft_reentry_when_recovery_or_cross_validation_passes",
            "previous_top15": sorted(previous),
            "reentry_passed": reentry_passed,
            "current_top10_overlap": top10_overlap,
            "current_top15_overlap": top15_overlap,
            "top10_overlap_rate": round(len(top10_overlap) / 10, 3),
            "top15_overlap_rate": round(len(top15_overlap) / 15, 3),
        },
        "stability_consensus": stability,
        "adaptive_weight_calibration": weight_calibration,
        "live_precision_calibration": precision_calibration,
        "objective_feature_calibration": objective_feature_calibration,
        "hit_through_calibration": hit_through_calibration,
        "zero_hit_recovery": zero_hit_recovery,
        "slump_recall_coverage": slump_recall_coverage,
        "top9_leakage_lock": top9_leakage_lock,
        "top10_promotion_audit": promotion_audit,
        "dependency_analysis": {
            "method": "three_fold_conditional_lift_with_fdr",
            "validated_links": validated_links[:30],
            "validated_link_count": len(validated_links),
            "lag_profile": lag_profile,
            "warning": "\u95dc\u806f\u4e0d\u7b49\u65bc\u56e0\u679c\uff0c\u53ea\u5141\u8a31\u901a\u904e\u5206\u6bb5\u9a57\u8b49\u7684\u9023\u52d5\u9032\u5165\u6a21\u578b",
        },
        "release_gate": release_gate,
        "decisive_battle_decision": decisive_decision,
        "weights": {key: round(value, 4) for key, value in weights.items()},
        "model_lifecycle": lifecycle,
        "backtest": audit,
        "advanced_models": advanced_models,
        "advanced_model_backtest": advanced_backtest,
        "unlikely_number_analysis": unlikely,
        "unlikely_backtest": unlikely_backtest(draws),
        "precision_governor": pack_governance,
        "model_audit": model_audit(audit, review),
        "regime_analysis": regime_analysis(draws),
        "candidates": candidates,
        "strong_prediction_packs": packs,
    }
