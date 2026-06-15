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
            "passed": False,
            "decision": "watch_only_not_main",
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
    validated_dependency = values.get("validated_dependency", 0) >= 0.7
    passed = validated_dependency and sum(strong_conditions) >= 2
    return {
        "passed": passed,
        "decision": "exceptionally_strong_reentry" if passed else "blocked_previous_prediction",
        "validated_dependency": validated_dependency,
        "strong_condition_count": sum(strong_conditions),
        "required_strong_conditions": 2,
    }


def build_feature_matrix(draws, review=None, include_dependency=True):
    windows = [5, 10, 20, 50, 100, 300]
    feature_scores = {n: defaultdict(float) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}

    for window in windows:
        subset = draws[-window:] if len(draws) >= window else draws
        freq = frequency(subset)
        zscores = {n: binomial_zscore(freq.get(n, 0), len(subset)) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
        normalized = normalize(zscores)
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
        feature_scores[number]["date"] = date_score[number]
        feature_scores[number]["repeat"] = 1.0 if number in latest_set else 0.0
        feature_scores[number]["neighbor"] = 1.0 if any(abs(number - anchor) == 1 for anchor in latest_set) else 0.0

    return feature_scores


def industrial_weights(review=None):
    weights = {
        "freq_5": 0.025,
        "freq_10": 0.045,
        "freq_20": 0.085,
        "freq_50": 0.125,
        "freq_100": 0.13,
        "freq_300": 0.055,
        "ewma_fast": 0.06,
        "ewma_slow": 0.08,
        "omission": 0.13,
        "transition": 0.07,
        "validated_dependency": 0.065,
        "markov_chain": 0.055,
        "time_series": 0.05,
        "neural_network": 0.06,
        "pair": 0.09,
        "tail_zone": 0.09,
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
                "repeat": 0.005,
                "neighbor": 0.01,
                "freq_50": 0.15,
                "freq_100": 0.145,
                "omission": 0.16,
                "tail_zone": 0.115,
                "pair": 0.11,
            }
        )
    total = sum(weights.values()) or 1
    return {key: value / total for key, value in weights.items()}


def score_numbers(draws, review=None, include_dependency=True):
    features = build_feature_matrix(draws, review, include_dependency=include_dependency)
    weights = industrial_weights(review)
    failed = failed_number_set(review)
    latest_set = set(draws[-1]["numbers"])
    repeat_policy = repeat_guard(draws)
    score = {}
    reasons = defaultdict(list)

    for number, values in features.items():
        raw = sum(values.get(name, 0) * weight for name, weight in weights.items())
        previous_policy = previous_prediction_guard(number, values, review)
        if previous_policy and not previous_policy["passed"]:
            raw *= 0.03
            reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u672a\u9054\u6975\u5f37\u91cd\u5165\u9580\u6abb")
        elif previous_policy and previous_policy["passed"]:
            reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u901a\u904e\u6975\u5f37\u91cd\u5165\u9580\u6abb")
        if number in failed:
            raw *= 0.18
            reasons[number].append("\u4e0a\u671f\u5931\u6557\u6838\u5fc3\u865f\u78bc\u9694\u96e2")
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
        if values["freq_50"] >= 0.7 or values["freq_100"] >= 0.7:
            reasons[number].append("\u4e2d\u671f\u7a69\u5b9a")
        if values["date"] > 0:
            reasons[number].append("\u65e5\u671f\u724c")
        if number in latest_set:
            policy = repeat_policy.get(number, {})
            raw *= 0.05
            if policy.get("historical_support"):
                reasons[number].append("\u9023\u838a\u89c0\u5bdf\u4e0d\u4e3b\u63a8")
            else:
                reasons[number].append("\u9023\u838a\u5b88\u9580\u672a\u901a\u904e")
        score[number] = raw

    normalized_score = normalize(score)
    omissions = omission(draws)
    ranked = rank_values(normalized_score)
    candidates = []
    for number in ranked:
        candidates.append(
            {
                "number": number,
                "score": round(normalized_score[number], 4),
                "confidence_index": round(50 + normalized_score[number] * 49, 1),
                "omission": omissions[number],
                "repeat_guard": repeat_policy.get(number),
                "previous_prediction_guard": previous_prediction_guard(number, features[number], review),
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
    start = max(120, len(draws) - rounds - 1)
    stats = {
        key: {"rounds": 0, "passes": 0, "hits": 0, "zero_hits": 0}
        for key in pack_specs
    }

    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        historical_candidates, _ = score_numbers(train, None, include_dependency=False)
        for key, spec in pack_specs.items():
            numbers = optimized_group(historical_candidates, spec["size"], None)
            hits = len(set(numbers) & actual)
            stats[key]["rounds"] += 1
            stats[key]["hits"] += hits
            stats[key]["passes"] += 1 if hits >= spec["goal"] else 0
            stats[key]["zero_hits"] += 1 if hits == 0 else 0

    pack_stats = {}
    allowed_count = 0
    for key, spec in pack_specs.items():
        item = stats[key]
        rounds_done = item["rounds"] or 1
        pass_rate = item["passes"] / rounds_done
        avg_hits = item["hits"] / rounds_done
        zero_rate = item["zero_hits"] / rounds_done
        passed = pass_rate >= spec["min_pass_rate"] and avg_hits >= spec["min_avg_hits"]
        allowed_count += 1 if passed else 0
        pack_stats[key] = {
            "rounds": item["rounds"],
            "goal": spec["goal"],
            "pass_rate": round(pass_rate, 3),
            "avg_hits": round(avg_hits, 3),
            "zero_hit_rate": round(zero_rate, 3),
            "min_pass_rate": spec["min_pass_rate"],
            "min_avg_hits": spec["min_avg_hits"],
            "passed": passed,
        }

    release_light = "green" if allowed_count >= 4 else "yellow" if allowed_count >= 2 else "red"
    return {
        "status": "evaluated",
        "rounds": next(iter(stats.values()))["rounds"],
        "release_light": release_light,
        "allowed_pack_count": allowed_count,
        "pack_stats": pack_stats,
        "message": "strict walk-forward pack governance; packs below threshold are withheld",
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
            "theoretical_probability": probability,
            "zones": Counter(zone_label(n) for n in numbers),
            "tails": Counter(n % 10 for n in numbers),
            "governance": {},
        }

    specs = {
        "strong_single": ("\u6700\u5f37\u55ae\u652f", 1, 1, 0.82, 2),
        "two_hit_one": ("\u6700\u5f372\u4e2d1", 1, 2, 0.76, 2),
        "three_hit_one": ("\u6700\u5f373\u4e2d1", 1, 3, 0.72, 1),
        "five_hit_two": ("\u6700\u5f375\u4e2d2", 2, 5, 0.68, 1),
        "nine_hit_three": ("\u6700\u5f379\u4e2d3", 3, 9, 0.62, 0),
    }
    packs = {}
    for key, (name, goal, size, min_avg_score, min_stability) in specs.items():
        allowed_pool = [
            item for item in candidates[:30]
            if item["number"] in qualified_numbers or (
                item.get("score", 0) >= min_avg_score and item.get("stability_count", 0) >= min_stability
            )
        ]
        if len(allowed_pool) < size:
            packs[key] = empty_pack(name, goal, "strict confidence pool has fewer qualified numbers than pack size")
            packs[key]["governance"] = pack_stats.get(key, {})
            continue
        numbers = optimized_group(allowed_pool, size, review)
        avg_score = sum(score_map[n] for n in numbers) / len(numbers) if numbers else 0
        weak_numbers = [
            n for n in numbers
            if candidate_map[n].get("previous_prediction_guard") and not candidate_map[n]["previous_prediction_guard"].get("passed")
        ]
        recent_stat = pack_stats.get(key, {})
        if recent_stat and not recent_stat.get("passed"):
            packs[key] = empty_pack(name, goal, "recent walk-forward pack performance did not pass")
        elif avg_score < min_avg_score:
            packs[key] = empty_pack(name, goal, "average score is below strict release threshold")
        elif weak_numbers:
            packs[key] = empty_pack(name, goal, "contains previous prediction re-entry numbers that failed the strict gate")
        else:
            packs[key] = pack(name, goal, sorted(numbers))
        packs[key]["governance"] = recent_stat

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


def industrial_backtest(draws, rounds=360):
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


def advanced_model_backtest(draws, rounds=180):
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
        if item.get("previous_prediction_guard") and not item["previous_prediction_guard"].get("passed")
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
        if item.get("previous_prediction_guard") and not item["previous_prediction_guard"].get("passed")
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
            penalty += 0.28
            if repeat_policy.get(number, {}).get("historical_support"):
                reasons.append("\u9023\u838a\u50c5\u89c0\u5bdf")
            else:
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
    base_candidates, weights = score_numbers(draws, review)
    candidates, stability = stability_consensus(draws, base_candidates, review)
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
    return {
        "engine_version": "industrial_v6_precision_governor_strict_release",
        "leakage_guard": True,
        "repeat_guard": repeat_guard(draws),
        "previous_prediction_guard": {
            "policy": "block_previous_top15_unless_validated_dependency_and_two_exceptional_conditions",
            "previous_top15": sorted(previous),
            "reentry_passed": reentry_passed,
            "current_top10_overlap": top10_overlap,
            "current_top15_overlap": top15_overlap,
            "top10_overlap_rate": round(len(top10_overlap) / 10, 3),
            "top15_overlap_rate": round(len(top15_overlap) / 15, 3),
        },
        "stability_consensus": stability,
        "dependency_analysis": {
            "method": "three_fold_conditional_lift_with_fdr",
            "validated_links": validated_links[:30],
            "validated_link_count": len(validated_links),
            "lag_profile": lag_profile,
            "warning": "\u95dc\u806f\u4e0d\u7b49\u65bc\u56e0\u679c\uff0c\u53ea\u5141\u8a31\u901a\u904e\u5206\u6bb5\u9a57\u8b49\u7684\u9023\u52d5\u9032\u5165\u6a21\u578b",
        },
        "release_gate": {
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
        },
        "weights": {key: round(value, 4) for key, value in weights.items()},
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
