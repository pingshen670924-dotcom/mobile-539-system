import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
ANALYSIS_JSON = REPORT_DIR / "latest_analysis.json"
HEALTH_JSON = REPORT_DIR / "health_status.json"
COMPETITION_JSON = REPORT_DIR / "model_competition.json"
BATTLE_MD = REPORT_DIR / "latest_battle_report.md"
BATTLE_TXT = REPORT_DIR / "latest_battle_report.txt"
BATTLE_HTML = REPORT_DIR / "latest_battle_report.html"
ENHANCED_BATTLE_HTML = REPORT_DIR / "539\u6700\u65b0\u5f37\u5316\u6230\u5831.html"
HISTORY_JSON = REPORT_DIR / "prediction_history.json"
HISTORY_HTML = REPORT_DIR / "539\u6bcf\u671f\u9810\u6e2c\u5c0d\u6bd4.html"
HISTORY_DIR = REPORT_DIR / "history"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def taipei_now():
    return datetime.now(TAIPEI_TZ).replace(tzinfo=None)


def fmt_numbers(numbers):
    return " ".join(f"{int(n):02d}" for n in numbers)


def official_status_label(status):
    labels = {
        "inserted": "\u5df2\u4f9d\u6700\u65b0\u958b\u734e\u91cd\u65b0\u5efa\u7acb\u6b63\u5f0f\u9810\u6e2c",
        "updated_pending": "\u5df2\u91cd\u65b0\u904b\u7b97\u4e26\u66f4\u65b0\u6b63\u5f0f\u9810\u6e2c",
        "corrected_pending": "\u5df2\u91cd\u65b0\u904b\u7b97\u4e26\u5957\u7528\u91cd\u8907\u865f\u5b88\u9580\u4fee\u6b63",
        "recalculated_same_as_official": "\u5df2\u91cd\u65b0\u904b\u7b97\uff0c\u7d50\u679c\u8207\u76ee\u524d\u6b63\u5f0f\u9810\u6e2c\u76f8\u540c",
        "stale_data_blocked": "\u8cc7\u6599\u672a\u9054\u61c9\u6709\u958b\u734e\u65e5\uff0c\u7981\u6b62\u7522\u751f\u65b0\u6b63\u5f0f\u9810\u6e2c",
        "aerospace_assurance_blocked": "\u822a\u592a\u7d1a\u5b8c\u6574\u6027\u5be9\u6838\u672a\u901a\u904e\uff0c\u7981\u6b62\u7522\u751f\u6b63\u5f0f\u9810\u6e2c",
        "preserved_settled": "\u8a72\u671f\u6b63\u5f0f\u9810\u6e2c\u5df2\u7d50\u7b97\uff0c\u672c\u6b21\u53ea\u4fdd\u7559\u5feb\u7167",
    }
    return labels.get(status or "", status or "\u672c\u6b21\u91cd\u65b0\u904b\u7b97")


def load_json(path):
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return {}
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def latest_settled_prediction():
    if not DB_PATH.exists():
        return {}
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT based_on_period, target_period, actual_period, actual_date,
                   actual_numbers_json, candidates_json, suggested_sets_json,
                   strong_packs_json, set_hits_json, strong_pack_hits_json,
                   top5_hits, top10_hits, top15_hits, created_at, settled_at,
                   model_weights_json
            FROM predictions_539
            WHERE status='settled'
            ORDER BY actual_period DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {}
    return {
        "based_on_period": row[0],
        "target_period": row[1],
        "actual_period": row[2],
        "actual_date": row[3],
        "actual_numbers": json.loads(row[4] or "[]"),
        "candidates": json.loads(row[5] or "[]"),
        "suggested_sets": json.loads(row[6] or "[]"),
        "strong_packs": json.loads(row[7] or "{}"),
        "set_hits": json.loads(row[8] or "[]"),
        "strong_pack_hits": json.loads(row[9] or "{}"),
        "top5_hits": row[10],
        "top10_hits": row[11],
        "top15_hits": row[12],
        "created_at": row[13],
        "settled_at": row[14],
        "model_weights": json.loads(row[15] or "{}"),
    }


def latest_pending_prediction():
    if not DB_PATH.exists():
        return {}
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT id, based_on_period, based_on_date, target_period,
                   candidates_json, suggested_sets_json, strong_packs_json,
                   model_weights_json, backtest_json, created_at
            FROM predictions_539
            WHERE status='pending'
            ORDER BY based_on_period DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {}
    return {
        "id": row[0],
        "based_on_period": row[1],
        "based_on_date": row[2],
        "target_period": row[3],
        "candidates": json.loads(row[4] or "[]"),
        "suggested_sets": json.loads(row[5] or "[]"),
        "strong_packs": json.loads(row[6] or "{}"),
        "model_weights": json.loads(row[7] or "{}"),
        "backtest": json.loads(row[8] or "{}"),
        "created_at": row[9],
    }


def prediction_history():
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT based_on_period, based_on_date, target_period, candidates_json,
                   strong_packs_json, actual_period, actual_date, actual_numbers_json,
                   top5_hits, top10_hits, top15_hits, strong_pack_hits_json,
                   status, created_at, settled_at,
                   (
                     SELECT COUNT(*)
                     FROM prediction_snapshots_539 s
                     WHERE s.based_on_period=p.based_on_period
                   ) AS snapshot_count
            FROM predictions_539 p
            ORDER BY target_period DESC, id DESC
            """
        ).fetchall()
    history = []
    for row in rows:
        candidates = json.loads(row[3] or "[]")
        actual_numbers = json.loads(row[7] or "[]")
        actual_set = set(actual_numbers)
        top5 = [item.get("number") for item in candidates[:5]]
        top10 = [item.get("number") for item in candidates[:10]]
        top15 = [item.get("number") for item in candidates[:15]]
        strong_hits = json.loads(row[11] or "{}")
        history.append(
            {
                "based_on_period": row[0],
                "based_on_date": row[1],
                "target_period": row[2],
                "top5": top5,
                "top10": top10,
                "top15": top15,
                "actual_period": row[5],
                "actual_date": row[6],
                "actual_numbers": actual_numbers,
                "top5_hits": row[8],
                "top10_hits": row[9],
                "top15_hits": row[10],
                "top10_hit_numbers": sorted(actual_set & set(top10)),
                "strong_pack_hits": strong_hits,
                "status": row[12],
                "created_at": row[13],
                "settled_at": row[14],
                "snapshot_count": row[15],
            }
        )
    return history


def save_prediction_history(history):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": taipei_now().isoformat(timespec="seconds"),
        "total_periods": len(history),
        "settled_periods": sum(1 for item in history if item.get("status") == "settled"),
        "pending_periods": sum(1 for item in history if item.get("status") == "pending"),
        "periods": history,
    }
    HISTORY_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in history:
        target = item.get("target_period")
        if target is None:
            continue
        path = HISTORY_DIR / f"period_{target}.json"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def resolved_official_status(analysis, pending_prediction):
    status = analysis.get("official_prediction_status")
    if status:
        return status
    latest = analysis.get("latest_draw", {})
    if pending_prediction and pending_prediction.get("based_on_period") == latest.get("period"):
        return "recalculated_same_as_official"
    return "recalculated_same_as_official"


def pack_label(key):
    labels = {
        "strong_single": "\u6700\u5f37\u55ae\u652f",
        "two_hit_one": "\u6700\u5f372\u4e2d1",
        "three_hit_one": "\u6700\u5f373\u4e2d1",
        "five_hit_two": "\u6700\u5f375\u4e2d2",
        "nine_hit_three": "\u6700\u5f379\u4e2d3",
    }
    return labels.get(key, key)


def settled_hit_rows(settled):
    if not settled:
        return []
    actual = set(settled.get("actual_numbers", []))
    candidates = settled.get("candidates", [])
    strong_packs = settled.get("strong_packs", {})
    candidate_rank = {item.get("number"): idx + 1 for idx, item in enumerate(candidates)}
    candidate_reason = {
        item.get("number"): "\u3001".join(item.get("reasons", []))
        for item in candidates
    }
    rows = []
    for number in sorted(actual):
        sources = []
        rank = candidate_rank.get(number)
        if rank:
            if rank <= 5:
                sources.append("Top5")
            if rank <= 10:
                sources.append("Top10")
            if rank <= 15:
                sources.append("Top15")
            reason = candidate_reason.get(number)
            if reason:
                sources.append(reason)
        for key, pack in strong_packs.items():
            if number in pack.get("numbers", []):
                sources.append(pack_label(key))
        rows.append(
            {
                "number": number,
                "hit": bool(sources),
                "rank": rank,
                "sources": sources or ["\u672a\u9032\u5165\u6b63\u5f0f\u9810\u6e2c\u4e3b\u9078"],
            }
        )
    return rows


def settled_candidate_review_rows(settled, limit=15):
    if not settled:
        return []
    actual = set(settled.get("actual_numbers", []))
    candidates = settled.get("candidates", [])[:limit]
    strong_packs = settled.get("strong_packs", {})
    rows = []
    for idx, item in enumerate(candidates, 1):
        number = item.get("number")
        hit = number in actual
        pack_sources = [
            pack_label(key)
            for key, pack in strong_packs.items()
            if number in pack.get("numbers", [])
        ]
        reasons = list(item.get("reasons", []))
        if pack_sources:
            reasons.extend(pack_sources)
        if hit:
            diagnosis = "\u547d\u4e2d\uff1a\u4fdd\u7559\u8a72\u985e\u95dc\u806f\u6b0a\u91cd\uff0c\u4f46\u4e0d\u8ffd\u9ad8\u904e\u5ea6\u9023\u7528"
        else:
            diagnosis = "\u672a\u547d\u4e2d\uff1a\u964d\u4f4e\u77ed\u7dda\u8ffd\u71b1\u8207\u540c\u985e\u7406\u7531\u6b0a\u91cd"
        if not hit and item.get("omission", 0) == 0:
            diagnosis = "\u672a\u547d\u4e2d\uff1a\u4e0a\u671f\u91cd\u865f\u672a\u5be6\u73fe\uff0c\u5df2\u555f\u7528\u9023\u838a\u5b88\u9580"
        rows.append(
            {
                "rank": idx,
                "number": number,
                "hit": hit,
                "score": item.get("confidence_index", item.get("score")),
                "omission": item.get("omission"),
                "reasons": reasons or ["\u7d9c\u5408\u6a21\u578b"],
                "diagnosis": diagnosis,
            }
        )
    return rows


def prediction_audit(settled):
    if not settled:
        return {}
    actual = set(settled.get("actual_numbers", []))
    candidates = settled.get("candidates", [])
    candidate_map = {item.get("number"): item for item in candidates}
    reason_stats = {}
    for idx, item in enumerate(candidates[:15], 1):
        number = item.get("number")
        hit = number in actual
        reasons = item.get("reasons", []) or ["\u7d9c\u5408\u6a21\u578b"]
        for reason in reasons:
            bucket = reason_stats.setdefault(reason, {"hit": 0, "miss": 0, "numbers": []})
            bucket["hit" if hit else "miss"] += 1
            bucket["numbers"].append(number)
    missed_actual = []
    for number in sorted(actual):
        item = candidate_map.get(number)
        rank = candidates.index(item) + 1 if item in candidates else None
        missed_actual.append({
            "number": number,
            "rank": rank,
            "status": "hit_in_top15" if rank and rank <= 15 else ("outside_top15" if rank else "not_ranked"),
            "reasons": item.get("reasons", []) if item else [],
        })
    top_groups = {
        "Top5": [item.get("number") for item in candidates[:5]],
        "Top10": [item.get("number") for item in candidates[:10]],
        "Top15": [item.get("number") for item in candidates[:15]],
    }
    return {
        "reason_stats": reason_stats,
        "missed_actual": missed_actual,
        "top_groups": top_groups,
    }


def fmt_hit_numbers(numbers, actual):
    actual_set = set(actual)
    return " ".join(markdown_number(number, number in actual_set) for number in numbers)


def red_circle(number):
    return (
        '<span style="display:inline-flex;align-items:center;justify-content:center;'
        'width:30px;height:30px;border:2px solid #dc2626;border-radius:50%;'
        'color:#dc2626;font-weight:800;margin:0 2px;">'
        f"{int(number):02d}</span>"
    )


def markdown_number(number, hit=False):
    if not hit:
        return f"{int(number):02d}"
    return f"<span style=\"color:#dc2626;border:2px solid #dc2626;border-radius:999px;padding:1px 6px;font-weight:700;\">{int(number):02d}</span>"


def build_report():
    analysis = load_json(ANALYSIS_JSON)
    health = load_json(HEALTH_JSON)
    competition = load_json(COMPETITION_JSON)
    if not analysis:
        raise RuntimeError("\u627e\u4e0d\u5230 latest_analysis.json\uff0c\u8acb\u5148\u57f7\u884c update_539.py\u3002")

    latest = analysis["latest_draw"]
    packs = analysis.get("strong_prediction_packs", {})
    relationships = analysis.get("relationships", {})
    candidates = analysis.get("candidates", [])
    health_status = health.get("status", "unknown")
    industrial = analysis.get("industrial_engine", {})
    audit = industrial.get("model_audit", {})
    regime = industrial.get("regime_analysis", {})
    dependency = industrial.get("dependency_analysis", {})
    release_gate = industrial.get("release_gate", {})
    stability = industrial.get("stability_consensus", {})
    industrial_backtest = industrial.get("backtest", {})
    rolling_windows = industrial_backtest.get("rolling_windows", {})
    unlikely = industrial.get("unlikely_number_analysis", {})
    unlikely_backtest = industrial.get("unlikely_backtest", {})
    freshness = analysis.get("data_freshness", {})
    release_label = "\u6b63\u5f0f\u4e3b\u63a8" if release_gate.get("status") == "official" else "\u50c5\u4f9b\u89c0\u5bdf\uff0c\u4e0d\u5217\u6b63\u5f0f\u4e3b\u63a8"
    settled_prediction = latest_settled_prediction()
    pending_prediction = latest_pending_prediction()
    official_status_code = resolved_official_status(analysis, pending_prediction)
    settled_rows = settled_hit_rows(settled_prediction)
    candidate_review_rows = settled_candidate_review_rows(settled_prediction)
    audit_detail = prediction_audit(settled_prediction)
    champion = competition.get("champion", {})

    lines = [
        "# 539 \u958b\u734e\u9810\u6e2c\u6230\u5831",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{taipei_now().isoformat(timespec='seconds')}",
        f"- \u7cfb\u7d71\u72c0\u614b\uff1a{health_status}",
        f"- \u8cc7\u6599\u65b0\u9bae\u5ea6\uff1a{freshness.get('status', '')} / \u61c9\u6709\u6700\u65b0\u65e5\u671f {freshness.get('expected_latest_date', '')}",
        f"- \u6700\u65b0\u671f\u5225\uff1a{latest['period']} ({latest['draw_date']})",
        "- \u6700\u65b0\u865f\u78bc\uff1a" + fmt_numbers(latest["numbers"]),
        f"- \u9810\u6e2c\u76ee\u6a19\u671f\uff1a{latest['period'] + 1}",
        f"- \u6b63\u5f0f\u9810\u6e2c\u72c0\u614b\uff1a{official_status_label(official_status_code)}",
        f"- \u76ee\u524d\u5f85\u7d50\u7b97\u6b63\u5f0f\u9810\u6e2c\uff1a\u4f9d\u64da\u671f {pending_prediction.get('based_on_period', '\u7121')} / \u76ee\u6a19\u671f {pending_prediction.get('target_period', '\u7121')} / \u5efa\u7acb {pending_prediction.get('created_at', '\u7121')}",
        "- \u91cd\u865f\u5b88\u9580\uff1a\u6700\u65b0\u958b\u734e\u865f\u672a\u901a\u904e\u9023\u838a\u7387\u6aa2\u5b9a\u4e0d\u5217\u5165\u4e3b\u63a8",
        f"- \u5de5\u696d\u5f15\u64ce\uff1a{industrial.get('engine_version', '')}",
        f"- \u9810\u6e2c\u767c\u5e03\u7b49\u7d1a\uff1a{release_label}",
        f"- Top10 \u7a69\u5b9a\u5171\u8b58\u7387\uff1a{stability.get('top10_retention', '')}",
        f"- \u98a8\u96aa\u7b49\u7d1a\uff1a{audit.get('risk_level', '\u672a\u77e5')}",
        f"- \u7af6\u8cfd\u51a0\u8ecd\uff1a{champion.get('model', '\u5c1a\u7121')}",
        "- \u63d0\u9192\uff1a\u672c\u6230\u5831\u70ba\u6b77\u53f2\u7d71\u8a08\u5206\u6790\uff0c\u4e0d\u4fdd\u8b49\u958b\u51fa\uff0c\u8acb\u91cf\u529b\u800c\u70ba\u3002",
        "",
        "## \u4eca\u65e5\u7e3d\u5224\u65b7",
        f"- \u5f15\u64ce\u8a55\u8a9e\uff1a{audit.get('verdict', '')}",
        "- \u958b\u734e\u578b\u614b\uff1a" + "\u3001".join(regime.get("messages", [])),
        f"- \u96a8\u6a5f Top10 \u57fa\u6e96\uff1a{competition.get('random_top10_expectation', '')}",
        f"- \u96a8\u6a5f Top15 \u57fa\u6e96\uff1a{competition.get('random_top15_expectation', '')}",
        "",
        "## \u53c3\u8003\u7db2\u7ad9\u65b9\u6cd5\u8f49\u5316",
        "- \u71b1\u865f\u8207\u51b7\u865f\u4e0d\u55ae\u7368\u7576\u4f5c\u9810\u6e2c\uff0c\u6539\u70ba\u983b\u7387\u3001\u907a\u6f0f\u3001\u7d71\u8a08\u566a\u97f3\u8207\u56de\u6e2c\u540c\u6642\u5224\u65b7\u3002",
        "- \u5f37\u724c\u4e0d\u53ea\u7d66\u865f\u78bc\uff0c\u5fc5\u9808\u4f75\u5217\u7406\u8ad6\u6a5f\u7387\u3001\u5305\u724c\u8986\u84cb\u3001\u7968\u6578\u8207\u98a8\u96aa\u3002",
        "- \u63a1\u7528\u591a\u6a21\u578b\u6295\u7968\u8207\u53ef\u89e3\u91cb\u8f38\u51fa\uff0c\u907f\u514d\u55ae\u4e00\u6a21\u578b\u5931\u771f\u5f8c\u9023\u7e8c\u8ffd\u932f\u3002",
        "",
        "## " + ("\u4eca\u65e5\u5f37\u724c" if release_gate.get("status") == "official" else "\u4eca\u65e5\u89c0\u5bdf\u5019\u9078\uff08\u4e0d\u5217\u6b63\u5f0f\u4e3b\u63a8\uff09"),
    ]

    pack_order = [
        ("strong_single", "\u6700\u5f37\u55ae\u652f"),
        ("two_hit_one", "\u6700\u5f372\u4e2d1"),
        ("three_hit_one", "\u6700\u5f373\u4e2d1"),
        ("five_hit_two", "\u6700\u5f375\u4e2d2"),
        ("nine_hit_three", "\u6700\u5f379\u4e2d3"),
    ]
    for key, label in pack_order:
        pack = packs.get(key, {})
        if pack:
            probability = pack.get("theoretical_probability", {})
            lines.append(f"- {label}\uff1a{fmt_numbers(pack['numbers'])}")
            if probability:
                lines.append(f"  - \u7406\u8ad6\u6a5f\u7387\uff1a{probability.get('probability')} / 1\u4e2d{probability.get('odds_1_in', '')}")
            if key == "nine_hit_three" and pack.get("wheel_tickets"):
                coverage = pack.get("wheel_coverage", {})
                lines.append(f"  - 9\u4e2d3\u8f2a\u7d44\u8986\u84cb\uff1a{coverage.get('covered')}/{coverage.get('total')}\uff0c\u8986\u84cb\u7387 {coverage.get('rate')}")
                for idx, ticket in enumerate(pack["wheel_tickets"], 1):
                    lines.append(f"    {idx}. {fmt_numbers(ticket)}")

    review = analysis.get("failure_review", {})
    if review.get("has_review"):
        settled = review.get("last_settled", {})
        lines.extend([
            "",
            "## \u5931\u6557\u6aa2\u8a0e",
            f"- \u4e0a\u6b21\u9810\u6e2c\uff1a{settled.get('based_on_period')} -> {settled.get('actual_period')}",
            "- \u5be6\u969b\u958b\u51fa\uff1a" + fmt_numbers(settled.get("actual_numbers", [])),
            f"- Top5 / Top10 / Top15 \u547d\u4e2d\uff1a{settled.get('top5_hits')} / {settled.get('top10_hits')} / {settled.get('top15_hits')}",
            "- \u8a3a\u65b7\uff1a\u4ee5\u771f\u5be6\u7d50\u7b97\u7d00\u9304\u53cd\u63a8\u5931\u6557\u4f86\u6e90\uff0c\u964d\u4f4e\u540c\u4e00\u6279\u932f\u865f\u9023\u7e8c\u9032\u5165\u4e3b\u63a8\u3002",
        ])
        for action in review.get("actions", []):
            lines.append(f"- \u6539\u5584\uff1a{action}")

    if settled_prediction:
        actual_numbers = settled_prediction.get("actual_numbers", [])
        lines.extend([
            "",
            "## \u4e0a\u671f\u6b63\u5f0f\u9810\u6e2c\u547d\u4e2d\u89e3\u6790",
            f"- \u6b63\u5f0f\u9810\u6e2c\u5efa\u7acb\u6642\u9593\uff1a{settled_prediction.get('created_at')}",
            f"- \u7d50\u7b97\u6642\u9593\uff1a{settled_prediction.get('settled_at')}",
            f"- \u9810\u6e2c\u4f9d\u64da\u671f\uff1a{settled_prediction.get('based_on_period')}",
            f"- \u539f\u9810\u6e2c\u76ee\u6a19\u671f\uff1a{settled_prediction.get('target_period')}",
            f"- \u5be6\u969b\u958b\u734e\u671f\uff1a{settled_prediction.get('actual_period')} ({settled_prediction.get('actual_date')})",
            f"- Top5 / Top10 / Top15\uff1a{settled_prediction.get('top5_hits')} / {settled_prediction.get('top10_hits')} / {settled_prediction.get('top15_hits')}",
            "- \u958b\u51fa\u865f\u78bc\uff1a" + " ".join(markdown_number(row["number"], row["hit"]) for row in settled_rows),
            "- \u6628\u65e5 Top5\uff1a" + fmt_hit_numbers(audit_detail.get("top_groups", {}).get("Top5", []), actual_numbers),
            "- \u6628\u65e5 Top10\uff1a" + fmt_hit_numbers(audit_detail.get("top_groups", {}).get("Top10", []), actual_numbers),
            "- \u6628\u65e5 Top15\uff1a" + fmt_hit_numbers(audit_detail.get("top_groups", {}).get("Top15", []), actual_numbers),
            "",
            "| \u865f\u78bc | \u547d\u4e2d | \u5019\u9078\u6392\u540d | \u547d\u4e2d\u4f86\u6e90\u95dc\u806f\u89e3\u6790 |",
            "| ---: | --- | ---: | --- |",
        ])
        for row in settled_rows:
            hit_text = "\u662f" if row["hit"] else "\u5426"
            rank_text = row["rank"] if row["rank"] else "-"
            lines.append(
                f"| {markdown_number(row['number'], row['hit'])} | {hit_text} | {rank_text} | "
                + "\u3001".join(row["sources"])
                + " |"
            )
        lines.extend([
            "",
            "## \u6628\u65e5\u53c3\u8003\u7d44\u5408\u6aa2\u8a0e",
            "| \u7d44\u5225 | \u539f\u9810\u6e2c\u7d44\u5408 | \u547d\u4e2d\u6578 | \u547d\u4e2d\u865f | \u672a\u547d\u4e2d\u865f |",
            "| ---: | --- | ---: | --- | --- |",
        ])
        for item in settled_prediction.get("set_hits", []):
            numbers = item.get("numbers", [])
            hit_numbers = sorted(set(numbers) & set(actual_numbers))
            miss_numbers = sorted(set(numbers) - set(actual_numbers))
            lines.append(
                f"| {item.get('set_index')} | {fmt_numbers(numbers)} | {item.get('hits')} | "
                f"{fmt_hit_numbers(hit_numbers, actual_numbers)} | {fmt_numbers(miss_numbers)} |"
            )
        lines.extend([
            "",
            "## \u6628\u65e5\u5f37\u724c\u7d44\u6210\u6557\u6aa2\u8a0e",
            "| \u5f37\u724c | \u539f\u9810\u6e2c\u865f\u78bc | \u76ee\u6a19 | \u5be6\u969b\u547d\u4e2d | \u7d50\u679c | \u547d\u4e2d\u865f | \u672a\u547d\u4e2d\u865f |",
            "| --- | --- | ---: | ---: | --- | --- | --- |",
        ])
        for key, item in settled_prediction.get("strong_pack_hits", {}).items():
            numbers = item.get("numbers", [])
            hit_numbers = sorted(set(numbers) & set(actual_numbers))
            miss_numbers = sorted(set(numbers) - set(actual_numbers))
            result = "\u9054\u6a19" if item.get("passed") else "\u672a\u9054\u6a19"
            lines.append(
                f"| {item.get('name', pack_label(key))} | {fmt_numbers(numbers)} | {item.get('hit_goal')} | {item.get('hits')} | "
                f"{result} | {fmt_hit_numbers(hit_numbers, actual_numbers)} | {fmt_numbers(miss_numbers)} |"
            )
        lines.extend([
            "",
            "## \u6628\u65e5\u4f86\u6e90\u7406\u7531\u6210\u6557\u7d71\u8a08",
            "| \u4f86\u6e90\u7406\u7531 | \u547d\u4e2d | \u672a\u547d\u4e2d | \u6d89\u53ca\u865f\u78bc | \u4fee\u6b63\u65b9\u5411 |",
            "| --- | ---: | ---: | --- | --- |",
        ])
        for reason, stats in sorted(audit_detail.get("reason_stats", {}).items(), key=lambda item: (item[1]["miss"], -item[1]["hit"]), reverse=True):
            if stats["hit"] == 0 and stats["miss"] >= 2:
                action = "\u964d\u6b0a"
            elif stats["hit"] >= stats["miss"]:
                action = "\u4fdd\u7559\u4f46\u964d\u4f4e\u8ffd\u9ad8"
            else:
                action = "\u89c0\u5bdf"
            lines.append(f"| {reason} | {stats['hit']} | {stats['miss']} | {fmt_numbers(stats['numbers'])} | {action} |")
        lines.extend([
            "",
            "## \u5be6\u969b\u958b\u51fa\u865f\u78bc\u6f0f\u6293\u6aa2\u8a0e",
            "| \u958b\u51fa\u865f | \u9810\u6e2c\u6392\u540d | \u72c0\u614b | \u539f\u56e0\u89e3\u91cb |",
            "| ---: | ---: | --- | --- |",
        ])
        for item in audit_detail.get("missed_actual", []):
            if item["status"] == "hit_in_top15":
                status = "\u5df2\u9032Top15"
                explanation = "\u8a72\u865f\u6709\u88ab\u6a21\u578b\u6355\u6349\uff0c\u5f8c\u7e8c\u6aa2\u67e5\u662f\u6392\u540d\u4f4d\u7f6e\u8207\u5f37\u724c\u914d\u7f6e"
            elif item["status"] == "outside_top15":
                status = "Top15\u5916"
                explanation = "\u6709\u6392\u540d\u4f46\u4fe1\u5fc3\u4e0d\u8db3\uff0c\u9700\u6aa2\u67e5\u6b0a\u91cd\u662f\u5426\u904e\u5ea6\u58d3\u4f4e"
            else:
                status = "\u672a\u6392\u5165"
                explanation = "\u6a21\u578b\u672a\u6355\u6349\uff0c\u9700\u52a0\u5f37\u4e2d\u9577\u671f\u8207\u5340\u9593\u8f2a\u52d5\u56e0\u5b50"
            lines.append(f"| {item['number']:02d} | {item.get('rank') or '-'} | {status} | {explanation} |")
        lines.extend([
            "",
            "## \u6628\u65e5\u6b63\u5f0f\u9810\u6e2c\u9010\u865f\u6aa2\u8a0e",
            "| \u9810\u6e2c\u6392\u540d | \u865f\u78bc | \u7d50\u679c | \u4fe1\u5fc3 | \u907a\u6f0f | \u539f\u59cb\u4f86\u6e90 | \u6aa2\u8a0e\u52d5\u4f5c |",
            "| ---: | ---: | --- | ---: | ---: | --- | --- |",
        ])
        for row in candidate_review_rows:
            result = "\u547d\u4e2d" if row["hit"] else "\u672a\u547d\u4e2d"
            reason_text = "\u3001".join(row["reasons"])
            lines.append(
                f"| {row['rank']} | {markdown_number(row['number'], row['hit'])} | {result} | "
                f"{row['score']} | {row['omission']} | {reason_text} | {row['diagnosis']} |"
            )

    lines.extend(["", "## \u5019\u9078 Top 15 \u8a73\u8868"])
    lines.append("| \u6392\u540d | \u865f\u78bc | \u4fe1\u5fc3\u6307\u6578 | \u907a\u6f0f | \u4e3b\u8981\u7406\u7531 |")
    lines.append("| ---: | ---: | ---: | ---: | --- |")
    for idx, item in enumerate(candidates[:15], 1):
        reason = "\u3001".join(item.get("reasons", []))
        lines.append(f"| {idx} | {item['number']:02d} | {item.get('confidence_index')} | {item.get('omission')} | {reason} |")

    if relationships:
        drag = relationships.get("drag", {}).get("top", [])[:10]
        date = relationships.get("date", {})
        tail = relationships.get("tail", {}).get("top_tails", [])
        similar = relationships.get("similar", {}).get("top", [])[:10]
        twin = relationships.get("twin", {}).get("top", [])[:10]
        lines.extend([
            "",
            "## \u724c\u578b\u95dc\u806f",
            "- \u62d6\u724c\uff1a" + fmt_numbers([item["number"] for item in drag]),
            f"- \u65e5\u671f\u724c ({date.get('date', '')})\uff1a" + fmt_numbers(date.get("candidates", [])),
            "- \u5c3e\u6578\u724c\uff1a" + " ".join(f"{item['tail']}\u5c3e({item['count']})" for item in tail),
            "- \u76f8\u4f3c\u724c\uff1a" + fmt_numbers([item["number"] for item in similar]),
            "- \u96d9\u751f\u724c\uff1a" + fmt_numbers([item["number"] for item in twin]),
        ])

    if dependency:
        lines.extend([
            "",
            "## \u865f\u78bc\u95dc\u806f\u8207\u9023\u52d5\u7cbe\u6e96\u5206\u6790",
            f"- \u65b9\u6cd5\uff1a{dependency.get('method')}",
            f"- \u901a\u904e\u524d\u5f8c\u5206\u6bb5\u9a57\u8b49\u9023\u52d5\u6578\uff1a{dependency.get('validated_link_count')}",
            f"- \u8b66\u793a\uff1a{dependency.get('warning')}",
            "",
            "### \u5ef6\u9072\u671f\u9023\u52d5",
            "| \u5ef6\u9072 | \u6a23\u672c | \u5be6\u969b\u5e73\u5747\u91cd\u758a | \u96a8\u6a5f\u671f\u5f85 | \u5dee\u503c |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ])
        for item in dependency.get("lag_profile", []):
            lines.append(
                f"| {item.get('lag')} | {item.get('samples')} | {item.get('average_overlap')} | "
                f"{item.get('random_expectation')} | {item.get('edge')} |"
            )
        lines.extend([
            "",
            "### \u901a\u904e\u4e09\u5340\u6bb5\u8207\u591a\u91cd\u6aa2\u5b9a\u7684\u865f\u78bc\u9023\u52d5",
            "| \u4f86\u6e90\u865f | \u76ee\u6a19\u865f | \u4e09\u5340\u6bb5\u6a23\u672c | \u4e09\u5340\u6bb5\u63d0\u5347 | \u4e09\u5340\u6bb5Z | P\u503c | FDR | \u4fdd\u5b88\u63d0\u5347 |",
            "| ---: | ---: | --- | --- | --- | ---: | ---: | ---: |",
        ])
        for item in dependency.get("validated_links", [])[:20]:
            lines.append(
                f"| {item.get('source'):02d} | {item.get('target'):02d} | {item.get('fold_support')} | "
                f"{item.get('fold_lift')} | {item.get('fold_z')} | {item.get('p_value')} | "
                f"{item.get('fdr_q')} | {item.get('conservative_lift')} |"
            )

    if competition:
        lines.extend(["", "## \u591a\u6a21\u578b\u7af6\u8cfd\u56de\u6e2c"])
        lines.append("| \u6a21\u578b | Top5 | Top10 | Top15 | Top10\u5dee\u503c | Top15\u5dee\u503c | Top10>=2 | Top15>=3 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for model in competition.get("models", []):
            rates = model.get("hit_rates", {})
            lines.append(
                f"| {model.get('model')} | {model.get('top5_avg_hits')} | {model.get('top10_avg_hits')} | {model.get('top15_avg_hits')} | "
                f"{model.get('top10_edge_vs_random')} | {model.get('top15_edge_vs_random')} | {rates.get('top10_ge_2')} | {rates.get('top15_ge_3')} |"
            )
        lines.append("")
        lines.append("### \u5206\u6bb5\u56de\u6e2c")
        for model in competition.get("models", []):
            lines.append(f"- {model.get('model')}\uff1a{model.get('profile', '')}")
            for label, data in model.get("segmented_backtest", {}).items():
                rates = data.get("hit_rates", {})
                lines.append(f"  - {label}\uff1aTop10 {data.get('top10_avg_hits')} / Top15 {data.get('top15_avg_hits')} / Top10>=2 {rates.get('top10_ge_2')} / Top15>=3 {rates.get('top15_ge_3')}")

    backtest = analysis.get("backtest", {})
    ensemble = backtest.get("strategies", {}).get("ensemble", {})
    if ensemble:
        lines.extend([
            "",
            "## \u6a21\u578b\u56de\u6e2c",
            f"- \u56de\u6e2c\u671f\u6578\uff1a{backtest.get('rounds')}",
            f"- \u7d9c\u5408\u6a21\u578b Top10 \u5e73\u5747\u547d\u4e2d\uff1a{ensemble.get('top10_avg_hits')}",
            f"- \u5c0d\u96a8\u6a5f\u5dee\u503c\uff1a{ensemble.get('top10_edge_vs_random')}",
        ])
    if industrial:
        ibt = industrial.get("backtest", {})
        repeat_guard = industrial.get("repeat_guard", {})
        previous_guard = industrial.get("previous_prediction_guard", {})
        release_gate = industrial.get("release_gate", {})
        stability = industrial.get("stability_consensus", {})
        lines.extend([
            "",
            "## \u5de5\u696d\u7d1a\u5f15\u64ce",
            f"- \u5f15\u64ce\u7248\u672c\uff1a{industrial.get('engine_version')}",
            f"- \u9632\u6b62\u672a\u4f86\u8cc7\u6599\u6d29\u6f0f\uff1a{industrial.get('leakage_guard')}",
            f"- Top10 \u56de\u6e2c\u5e73\u5747\u547d\u4e2d\uff1a{ibt.get('top10_avg_hits')}",
            f"- Top15 \u56de\u6e2c\u5e73\u5747\u547d\u4e2d\uff1a{ibt.get('top15_avg_hits')}",
            f"- \u767c\u5e03\u9580\u6abb\uff1a{release_gate.get('status')} / \u56de\u6e2c\u5dee\u503c {release_gate.get('actual_backtest_edge')}",
            f"- Top10 \u7a69\u5b9a\u5171\u8b58\u7387\uff1a{stability.get('top10_retention')} / \u64fe\u52d5\u5feb\u7167 {stability.get('snapshots')}",
            f"- \u6628\u65e5\u9810\u6e2c\u91cd\u8907\u5b88\u9580\uff1aTop10 \u91cd\u758a {previous_guard.get('current_top10_overlap')} / Top15 \u91cd\u758a {previous_guard.get('current_top15_overlap')}",
            f"- \u901a\u904e\u6975\u5f37\u91cd\u5165\u9580\u6abb\uff1a{previous_guard.get('reentry_passed')}",
        ])
        for window, values in ibt.get("rolling_windows", {}).items():
            lines.append(
                f"- \u8fd1 {window} \u671f Top10\uff1a{values.get('top10_avg_hits')} / "
                f"\u5c0d\u96a8\u6a5f\u5dee\u503c {values.get('top10_edge_vs_random')}"
            )
        advanced = industrial.get("advanced_models", {})
        advanced_bt = industrial.get("advanced_model_backtest", {})
        if advanced:
            lines.extend([
                "",
                "### \u9032\u968e\u9810\u6e2c\u6a21\u578b",
                f"- \u8aaa\u660e\uff1a{advanced.get('warning')}",
                f"- \u9032\u968e\u6a21\u578b\u5171\u8b58 Top12\uff1a{fmt_numbers(advanced.get('consensus_top12', []))}",
            ])
            for model in advanced.get("models", []):
                bt_row = advanced_bt.get("models", {}).get(model.get("model"), {})
                lines.append(
                    f"- {model.get('name')}\uff1a{fmt_numbers(model.get('top10', []))} / "
                    f"Top10 \u56de\u6e2c {bt_row.get('top10_avg_hits')} / "
                    f"\u5c0d\u96a8\u6a5f\u5dee\u503c {bt_row.get('top10_edge_vs_random')}"
                )
        if repeat_guard:
            lines.extend([
                "",
                "### \u9023\u838a\u5b88\u9580",
                "| \u6700\u65b0\u865f | \u6a23\u672c | \u9023\u838a\u6b21 | \u6b77\u53f2\u9023\u838a\u7387 | \u57fa\u6e96\u7387 | \u6c7a\u7b56 |",
                "| ---: | ---: | ---: | ---: | ---: | --- |",
            ])
            for number in sorted(int(key) for key in repeat_guard.keys()):
                item = repeat_guard.get(number) or repeat_guard.get(str(number), {})
                decision = "\u89c0\u5bdf\u4e0d\u4e3b\u63a8" if item.get("historical_support") else "\u5c01\u9396"
                lines.append(
                    f"| {number:02d} | {item.get('sample')} | {item.get('repeat_hits')} | "
                    f"{item.get('repeat_rate')} | {item.get('baseline')} | {decision} |"
                )
        unlikely = industrial.get("unlikely_number_analysis", {})
        unlikely_bt = industrial.get("unlikely_backtest", {})
        if unlikely:
            lines.extend([
                "",
                "### \u4f4e\u6a5f\u7387\u66ab\u907f\u865f\u78bc",
                f"- \u8aaa\u660e\uff1a{unlikely.get('warning')}",
                f"- \u56de\u6e2c\uff1a\u8fd1 {unlikely_bt.get('rounds')} \u671f\uff0c\u66ab\u907f {unlikely_bt.get('avoid_size')} \u78bc\u5e73\u5747\u8aa4\u4e2d {unlikely_bt.get('avg_accidental_hits')}\uff0c\u96a8\u6a5f\u57fa\u6e96 {unlikely_bt.get('random_expectation')}\uff0c\u5dee\u503c {unlikely_bt.get('edge_vs_random')}\uff0c\u5b8c\u5168\u907f\u958b\u7387 {unlikely_bt.get('zero_hit_rate')}",
                "| # | \u865f\u78bc | \u66ab\u907f\u6307\u6578 | \u51fa\u73fe\u8a55\u5206 | \u539f\u56e0 |",
                "| ---: | ---: | ---: | ---: | --- |",
            ])
            for idx, item in enumerate(unlikely.get("numbers", [])[:12], 1):
                reason = "\u3001".join(item.get("reasons", []))
                lines.append(
                    f"| {idx} | {item.get('number'):02d} | {item.get('avoid_score')} | "
                    f"{item.get('appearance_score')} | {reason} |"
                )

    performance = health.get("prediction_performance", {})
    lines.extend([
        "",
        "## \u771f\u5be6\u8ffd\u8e64",
        f"- \u5f85\u7d50\u7b97\u9810\u6e2c\uff1a{health.get('pending_predictions', 0)}",
        f"- \u5df2\u7d50\u7b97\u9810\u6e2c\uff1a{health.get('settled_predictions', 0)}",
        f"- \u9810\u6e2c\u5feb\u7167\uff1a{health.get('prediction_snapshots', 0)}",
        "- \u4fdd\u7559\u539f\u5247\uff1a\u6b63\u5f0f\u9810\u6e2c\u4e0d\u88ab\u540c\u671f\u91cd\u8dd1\u8986\u84cb\uff0c\u91cd\u8dd1\u7d50\u679c\u53ea\u9032\u5feb\u7167\u8868\u4f9b\u6bd4\u5c0d\u3002",
        f"- \u5be6\u969b Top10 \u5e73\u5747\u547d\u4e2d\uff1a{performance.get('top10_avg_hits', '\u5c1a\u7121\u8cc7\u6599')}",
        "",
    ])
    return "\n".join(lines)


def build_html_report(markdown_text):
    analysis = load_json(ANALYSIS_JSON)
    history = prediction_history()
    aerospace = analysis.get("aerospace_assurance", {})
    packs = analysis.get("strong_prediction_packs", {})
    candidates = analysis.get("candidates", [])
    latest = analysis.get("latest_draw", {})
    industrial = analysis.get("industrial_engine", {})
    audit = industrial.get("model_audit", {})
    regime = industrial.get("regime_analysis", {})
    dependency = industrial.get("dependency_analysis", {})
    release_gate = industrial.get("release_gate", {})
    stability = industrial.get("stability_consensus", {})
    industrial_backtest = industrial.get("backtest", {})
    rolling_windows = industrial_backtest.get("rolling_windows", {})
    unlikely = industrial.get("unlikely_number_analysis", {})
    unlikely_backtest = industrial.get("unlikely_backtest", {})
    freshness = analysis.get("data_freshness", {})
    previous_guard = industrial.get("previous_prediction_guard", {})
    crowd = analysis.get("crowd_consensus", load_json(REPORT_DIR / "crowd_consensus.json"))
    settled_prediction = latest_settled_prediction()
    pending_prediction = latest_pending_prediction()
    official_status_code = resolved_official_status(analysis, pending_prediction)
    settled_rows = settled_hit_rows(settled_prediction)
    candidate_review_rows = settled_candidate_review_rows(settled_prediction)
    audit_detail = prediction_audit(settled_prediction)

    def card(title, value, sub=""):
        return (
            '<section class="card">'
            f"<h2>{title}</h2>"
            f'<div class="value">{value}</div>'
            f'<p class="sub">{sub}</p>'
            "</section>"
        )

    pack_order = [
        ("strong_single", "\u6700\u5f37\u55ae\u652f"),
        ("two_hit_one", "\u6700\u5f372\u4e2d1"),
        ("three_hit_one", "\u6700\u5f373\u4e2d1"),
        ("five_hit_two", "\u6700\u5f375\u4e2d2"),
        ("nine_hit_three", "\u6700\u5f379\u4e2d3"),
    ]
    pack_cards = []
    for key, label in pack_order:
        pack = packs.get(key, {})
        if pack:
            probability = pack.get("theoretical_probability", {})
            odds = probability.get("odds_1_in")
            sub = f"\u7406\u8ad6\u6a5f\u7387 {probability.get('probability')} / 1\u4e2d{odds}" if odds else ""
            pack_cards.append(card(label, fmt_numbers(pack.get("numbers", [])), sub))

    wheel_rows = ""
    wheel = packs.get("nine_hit_three", {})
    for idx, ticket in enumerate(wheel.get("wheel_tickets", []), 1):
        wheel_rows += f"<tr><td>{idx}</td><td>{fmt_numbers(ticket)}</td></tr>"
    coverage = wheel.get("wheel_coverage", {})

    candidate_rows = ""
    for idx, item in enumerate(candidates[:15], 1):
        reason = "\u3001".join(item.get("reasons", []))
        candidate_rows += (
            "<tr>"
            f"<td>{idx}</td><td>{item['number']:02d}</td><td>{item['confidence_index']}</td>"
            f"<td>{item['omission']}</td><td>{reason}</td>"
            "</tr>"
        )

    unlikely_rows = ""
    for idx, item in enumerate(unlikely.get("numbers", []), 1):
        reason = "\u3001".join(item.get("reasons", []))
        rank = item.get("candidate_rank") or "-"
        unlikely_rows += (
            "<tr>"
            f"<td>{idx}</td><td>{item.get('number'):02d}</td><td>{item.get('avoid_score')}</td>"
            f"<td>{item.get('appearance_score')}</td><td>{rank}</td>"
            f"<td>{item.get('stability_count')}</td><td>{reason}</td>"
            "</tr>"
        )

    settled_actual_html = " ".join(red_circle(row["number"]) if row["hit"] else f"{row['number']:02d}" for row in settled_rows)
    settled_rows_html = ""
    for row in settled_rows:
        number_html = red_circle(row["number"]) if row["hit"] else f"{row['number']:02d}"
        hit_text = "\u547d\u4e2d" if row["hit"] else "\u672a\u547d\u4e2d"
        rank_text = row["rank"] if row["rank"] else "-"
        source_text = "\u3001".join(row["sources"])
        settled_rows_html += (
            "<tr>"
            f"<td>{number_html}</td><td>{hit_text}</td><td>{rank_text}</td>"
            f"<td>{source_text}</td>"
            "</tr>"
        )

    candidate_review_html = ""
    for row in candidate_review_rows:
        number_html = red_circle(row["number"]) if row["hit"] else f"{row['number']:02d}"
        result_text = "\u547d\u4e2d" if row["hit"] else "\u672a\u547d\u4e2d"
        reason_text = "\u3001".join(row["reasons"])
        candidate_review_html += (
            "<tr>"
            f"<td>{row['rank']}</td><td>{number_html}</td><td>{result_text}</td>"
            f"<td>{row['score']}</td><td>{row['omission']}</td><td>{reason_text}</td><td>{row['diagnosis']}</td>"
            "</tr>"
        )

    set_review_html = ""
    actual_numbers = settled_prediction.get("actual_numbers", [])
    for item in settled_prediction.get("set_hits", []):
        numbers = item.get("numbers", [])
        hit_numbers = sorted(set(numbers) & set(actual_numbers))
        miss_numbers = sorted(set(numbers) - set(actual_numbers))
        set_review_html += (
            "<tr>"
            f"<td>{item.get('set_index')}</td><td>{fmt_numbers(numbers)}</td><td>{item.get('hits')}</td>"
            f"<td>{fmt_hit_numbers(hit_numbers, actual_numbers)}</td><td>{fmt_numbers(miss_numbers)}</td>"
            "</tr>"
        )

    pack_review_html = ""
    for key, item in settled_prediction.get("strong_pack_hits", {}).items():
        numbers = item.get("numbers", [])
        hit_numbers = sorted(set(numbers) & set(actual_numbers))
        miss_numbers = sorted(set(numbers) - set(actual_numbers))
        result = "\u9054\u6a19" if item.get("passed") else "\u672a\u9054\u6a19"
        pack_review_html += (
            "<tr>"
            f"<td>{item.get('name', pack_label(key))}</td><td>{fmt_numbers(numbers)}</td>"
            f"<td>{item.get('hit_goal')}</td><td>{item.get('hits')}</td><td>{result}</td>"
            f"<td>{fmt_hit_numbers(hit_numbers, actual_numbers)}</td><td>{fmt_numbers(miss_numbers)}</td>"
            "</tr>"
        )

    reason_review_html = ""
    for reason, stats in sorted(audit_detail.get("reason_stats", {}).items(), key=lambda item: (item[1]["miss"], -item[1]["hit"]), reverse=True):
        if stats["hit"] == 0 and stats["miss"] >= 2:
            action = "\u964d\u6b0a"
        elif stats["hit"] >= stats["miss"]:
            action = "\u4fdd\u7559\u4f46\u964d\u4f4e\u8ffd\u9ad8"
        else:
            action = "\u89c0\u5bdf"
        reason_review_html += (
            "<tr>"
            f"<td>{reason}</td><td>{stats['hit']}</td><td>{stats['miss']}</td>"
            f"<td>{fmt_numbers(stats['numbers'])}</td><td>{action}</td>"
            "</tr>"
        )

    dependency_rows_html = ""
    for item in dependency.get("validated_links", [])[:20]:
        dependency_rows_html += (
            "<tr>"
            f"<td>{item.get('source'):02d}</td><td>{item.get('target'):02d}</td>"
            f"<td>{item.get('fold_support')}</td><td>{item.get('fold_lift')}</td><td>{item.get('fold_z')}</td>"
            f"<td>{item.get('p_value')}</td><td>{item.get('fdr_q')}</td>"
            f"<td>{item.get('conservative_lift')}</td>"
            "</tr>"
        )

    plain_html = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    latest_numbers = fmt_numbers(latest.get("numbers", []))
    risk = audit.get("risk_level", "\u672a\u77e5")
    verdict = audit.get("verdict", "")
    regime_messages = "\u3001".join(regime.get("messages", []))
    release_status = release_gate.get("status", "watch_only")
    release_label = "\u6b63\u5f0f\u4e3b\u63a8" if release_status == "official" else "\u50c5\u4f9b\u89c0\u5bdf\uff0c\u7981\u6b62\u6b63\u5f0f\u4e3b\u63a8"
    freshness_label = "\u8cc7\u6599\u5df2\u66f4\u65b0" if freshness.get("status") == "fresh" else "\u8cc7\u6599\u904e\u671f\uff0c\u7981\u6b62\u9810\u6e2c"
    observation_note = "" if release_status == "official" else "\u672c\u5340\u70ba\u89c0\u5bdf\u5019\u9078\uff0c\u767c\u5e03\u9580\u6abb\u672a\u901a\u904e"
    official_status = official_status_label(official_status_code)
    pending_summary = (
        f"\u4f9d\u64da\u671f {pending_prediction.get('based_on_period', '\u7121')} / "
        f"\u76ee\u6a19\u671f {pending_prediction.get('target_period', '\u7121')} / "
        f"\u5efa\u7acb {pending_prediction.get('created_at', '\u7121')}"
    )

    rolling_rows = ""
    for window in ["60", "120", "360"]:
        values = rolling_windows.get(window, {})
        edge_value = values.get("top10_edge_vs_random")
        result = "\u901a\u904e" if edge_value is not None and edge_value >= 0 else "\u672a\u901a\u904e"
        rolling_rows += (
            "<tr>"
            f"<td>{window}</td><td>{values.get('rounds')}</td><td>{values.get('top10_avg_hits')}</td>"
            f"<td>{edge_value}</td><td>{result}</td>"
            "</tr>"
        )

    advanced = industrial.get("advanced_models", {})
    advanced_bt = industrial.get("advanced_model_backtest", {})
    advanced_rows = ""
    for model in advanced.get("models", []):
        bt_row = advanced_bt.get("models", {}).get(model.get("model"), {})
        advanced_rows += (
            "<tr>"
            f"<td>{model.get('name')}</td><td>{fmt_numbers(model.get('top10', []))}</td>"
            f"<td>{bt_row.get('top10_avg_hits')}</td><td>{bt_row.get('top10_edge_vs_random')}</td>"
            f"<td>{model.get('method')}</td>"
            "</tr>"
        )

    crowd_rows = ""
    candidate_numbers = {item.get("number") for item in candidates[:15]}
    for item in crowd.get("consensus_ranking", [])[:15]:
        match = "\u7cfb\u7d71\u5019\u9078\u5171\u8b58" if item.get("number") in candidate_numbers else "\u50c5\u7db2\u8def\u4eba\u6c23"
        crowd_rows += (
            "<tr>"
            f"<td>{item.get('number'):02d}</td><td>{item.get('source_votes')}</td><td>{match}</td>"
            "</tr>"
        )
    crowd_source_rows = ""
    for item in crowd.get("source_performance", []):
        crowd_source_rows += (
            "<tr>"
            f"<td>{item.get('source_name')}</td><td>{item.get('settled_rounds')}</td>"
            f"<td>{item.get('avg_hits')}</td><td>{item.get('recent30_avg_hits')}</td>"
            f"<td>{item.get('edge_vs_random')}</td><td>{item.get('model_weight_cap')}</td>"
            "</tr>"
        )
    crowd_warning_rows = ""
    for warning in crowd.get("collection", {}).get("warnings", [])[:12]:
        crowd_warning_rows += f"<tr><td>{warning}</td></tr>"

    uncertainty_rows = ""
    for item in aerospace.get("uncertainty_audit", {}).get("numbers", [])[:15]:
        uncertainty_rows += (
            "<tr>"
            f"<td>{item.get('number'):02d}</td><td>{item.get('base_rank')}</td>"
            f"<td>{item.get('top10_rate')}</td>"
            "</tr>"
        )

    consensus_counts = {
        int(number): int(count)
        for number, count in stability.get("consensus_counts", {}).items()
    }
    snapshots = max(int(stability.get("snapshots", 0) or 0), 1)
    uncertainty_map = {
        int(item.get("number")): float(item.get("top10_rate", 0))
        for item in aerospace.get("uncertainty_audit", {}).get("numbers", [])
    }
    primary_top10 = [item.get("number") for item in candidates[:10]]
    redundant_overlap = set(aerospace.get("redundant_channel_audit", {}).get("overlap", []))
    stable_consensus_rows = ""
    stable_core = []
    for rank, number in enumerate(primary_top10, 1):
        snapshot_rate = consensus_counts.get(number, 0) / snapshots
        monte_carlo_rate = uncertainty_map.get(number, 0)
        cross_channel = number in redundant_overlap
        combined = snapshot_rate * 0.45 + monte_carlo_rate * 0.45 + (0.10 if cross_channel else 0)
        if combined >= 0.85:
            level = "\u6838\u5fc3\u7a69\u5b9a"
            stable_core.append(number)
        elif combined >= 0.68:
            level = "\u7a69\u5b9a"
        elif combined >= 0.50:
            level = "\u89c0\u5bdf"
        else:
            level = "\u6613\u6ce2\u52d5"
        cross_label = "\u901a\u904e" if cross_channel else "\u672a\u901a\u904e"
        stable_consensus_rows += (
            "<tr>"
            f"<td>{rank}</td><td>{number:02d}</td>"
            f"<td>{consensus_counts.get(number, 0)}/{snapshots}</td>"
            f"<td>{snapshot_rate:.3f}</td><td>{monte_carlo_rate:.4f}</td>"
            f"<td>{cross_label}</td>"
            f"<td>{combined:.4f}</td><td>{level}</td>"
            "</tr>"
        )
    stable_core_text = fmt_numbers(stable_core) or "\u7121"

    history_rows = ""
    for item in history:
        status = "\u5df2\u7d50\u7b97" if item.get("status") == "settled" else "\u5f85\u7d50\u7b97"
        history_rows += (
            "<tr>"
            f"<td>{item.get('target_period')}</td>"
            f"<td>{status}</td>"
            f"<td>{item.get('based_on_period')}<br>{item.get('based_on_date', '')}</td>"
            f"<td>{fmt_numbers(item.get('top10', []))}</td>"
            f"<td>{fmt_numbers(item.get('actual_numbers', [])) or '-'}</td>"
            f"<td>{fmt_numbers(item.get('top10_hit_numbers', [])) or '-'}</td>"
            f"<td>{item.get('top5_hits') if item.get('top5_hits') is not None else '-'}</td>"
            f"<td>{item.get('top10_hits') if item.get('top10_hits') is not None else '-'}</td>"
            f"<td>{item.get('top15_hits') if item.get('top15_hits') is not None else '-'}</td>"
            f"<td>{item.get('snapshot_count', 0)}</td>"
            f"<td>{item.get('created_at', '')}<br>{item.get('settled_at') or '-'}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>539 \u958b\u734e\u9810\u6e2c\u6230\u5831</title>
  <style>
    body {{ margin:0; font-family:"Microsoft JhengHei", Arial, sans-serif; background:#f6f7fb; color:#20242a; }}
    header {{ background:#0f172a; color:white; padding:22px 28px; }}
    header h1 {{ margin:0 0 8px; font-size:28px; }}
    header p {{ margin:0; color:#cbd5e1; }}
    main {{ max-width:1180px; margin:0 auto; padding:22px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; }}
    .card {{ background:white; border:1px solid #e5e7eb; border-radius:8px; padding:16px; }}
    .card h2 {{ margin:0 0 10px; font-size:16px; color:#475569; }}
    .value {{ font-size:24px; font-weight:800; letter-spacing:1px; }}
    .sub {{ color:#64748b; margin:8px 0 0; font-size:13px; }}
    .band {{ background:white; border:1px solid #e5e7eb; border-radius:8px; margin-top:16px; padding:18px; }}
    .band h2 {{ margin:0 0 12px; font-size:20px; }}
    table {{ width:100%; border-collapse:collapse; background:white; }}
    th, td {{ border-bottom:1px solid #e5e7eb; padding:9px; text-align:left; }}
    th {{ background:#f1f5f9; color:#334155; }}
    .risk {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#fee2e2; color:#991b1b; font-weight:700; }}
    .status {{ display:inline-block; padding:5px 10px; border-radius:6px; background:#e2e8f0; color:#0f172a; font-weight:800; }}
    .blocked {{ background:#fee2e2; color:#991b1b; }}
    .fresh {{ background:#dcfce7; color:#166534; }}
    .notice {{ border-left:5px solid #dc2626; background:#fff7f7; }}
    pre {{ white-space:pre-wrap; background:#0b1020; color:#dbeafe; border-radius:8px; padding:16px; overflow:auto; }}
  </style>
</head>
<body>
  <header>
    <h1>539 \u958b\u734e\u9810\u6e2c\u6230\u5831</h1>
    <p>\u6700\u65b0\u671f\u5225 {latest.get('period')} / \u958b\u734e {latest_numbers} / \u904b\u7b97\u6642\u9593 {analysis.get('generated_at', '')}</p>
  </header>
  <main>
    <section class="band notice">
      <h2>\u672c\u671f\u767c\u5e03\u7d50\u8ad6</h2>
      <p><span class="status {'fresh' if freshness.get('status') == 'fresh' else 'blocked'}">{freshness_label}</span>
      <span class="status {'fresh' if release_status == 'official' else 'blocked'}">{release_label}</span></p>
      <p>\u5f15\u64ce\uff1a{industrial.get('engine_version', '')} / \u6700\u65b0\u8cc7\u6599\uff1a{freshness.get('latest_date', latest.get('draw_date'))} / \u61c9\u6709\u8cc7\u6599\uff1a{freshness.get('expected_latest_date', '')}</p>
      <p>\u6b63\u5f0f\u9810\u6e2c\u72c0\u614b\uff1a{official_status}</p>
      <p>\u76ee\u524d\u5f85\u7d50\u7b97\u6b63\u5f0f\u9810\u6e2c\uff1a{pending_summary}</p>
      <p>\u767c\u5e03\u5224\u5b9a\uff1aTop10 \u7a69\u5b9a\u5171\u8b58 {stability.get('top10_retention')} / \u6574\u9ad4\u56de\u6e2c\u5dee\u503c {release_gate.get('actual_backtest_edge')} / \u8fd1\u671f\u56de\u6e2c\u662f\u5426\u901a\u904e {release_gate.get('recent_performance_passed')}</p>
      <p>\u6628\u65e5\u9810\u6e2c\u91cd\u8907\u5b88\u9580\uff1aTop10 \u91cd\u758a {previous_guard.get('current_top10_overlap')} / Top15 \u91cd\u758a {previous_guard.get('current_top15_overlap')} / \u901a\u904e\u6975\u5f37\u91cd\u5165 {previous_guard.get('reentry_passed')}</p>
    </section>
    <div class="grid">
      {card('\u8cc7\u6599\u65b0\u9bae\u5ea6', freshness_label, f"\u6700\u65b0 {freshness.get('latest_date', latest.get('draw_date'))} / \u61c9\u6709 {freshness.get('expected_latest_date', '')}")}
      {card('\u767c\u5e03\u7b49\u7d1a', release_label, f"\u6574\u9ad4\u56de\u6e2c\u5dee\u503c {release_gate.get('actual_backtest_edge')}")}
      {card('Top10 \u7a69\u5b9a\u5171\u8b58', stability.get('top10_retention', ''), f"\u64fe\u52d5\u5feb\u7167 {stability.get('snapshots', '')}")}
      {card('\u9a57\u8b49\u9023\u52d5', dependency.get('validated_link_count', 0), '\u901a\u904e\u4e09\u5340\u6bb5\u8207 FDR \u6821\u6b63')}
      {card('\u6628\u65e5\u9810\u6e2c\u91cd\u758a', f"Top10 {previous_guard.get('top10_overlap_rate', '')} / Top15 {previous_guard.get('top15_overlap_rate', '')}", f"\u6975\u5f37\u91cd\u5165 {previous_guard.get('reentry_passed', [])}")}
      {card('\u7db2\u8def\u4eba\u6c23\u4f86\u6e90', crowd.get('source_count', 0), f"\u6a21\u578b\u5f71\u97ff {crowd.get('model_influence_status', '')}")}
    </div>
    <section class="band">
      <h2>\u8fd1\u671f\u7a69\u5b9a\u5ea6\u56de\u6e2c</h2>
      <table><thead><tr><th>\u671f\u6578</th><th>\u6a23\u672c</th><th>Top10 \u5e73\u5747\u547d\u4e2d</th><th>\u5c0d\u96a8\u6a5f\u5dee\u503c</th><th>\u9580\u6abb</th></tr></thead><tbody>{rolling_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u7a69\u5b9a\u5171\u8b58\u7368\u7acb\u6846\u67b6</h2>
      <p>\u5de5\u696d\u5feb\u7167\u5171\u8b58\u7387\uff1a{stability.get('top10_retention')} / \u64fe\u52d5\u5feb\u7167\uff1a{stability.get('snapshots')} / \u822a\u592a\u8499\u5730\u5361\u7f85 Top10 \u4fdd\u7559\u7387\uff1a{aerospace.get('uncertainty_audit', {}).get('top10_retention')}</p>
      <p>\u4e3b\u5f15\u64ce\u8207\u9032\u968e\u96d9\u901a\u9053\u91cd\u758a\uff1a{aerospace.get('redundant_channel_audit', {}).get('overlap_count')} / \u7a69\u5b9a\u6838\u5fc3\u865f\uff1a{stable_core_text}</p>
      <table><thead><tr><th>\u6392\u540d</th><th>\u865f\u78bc</th><th>\u5feb\u7167\u5171\u8b58</th><th>\u5feb\u7167\u7387</th><th>\u8499\u5730\u5361\u7f85\u7559\u5b58\u7387</th><th>\u96d9\u901a\u9053</th><th>\u7d9c\u5408\u7a69\u5b9a\u5206</th><th>\u7a69\u5b9a\u7b49\u7d1a</th></tr></thead><tbody>{stable_consensus_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u5168\u90e8\u6b63\u5f0f\u9810\u6e2c\u6b77\u53f2\u5c0d\u6bd4</h2>
      <p>\u6bcf\u671f\u6b63\u5f0f\u9810\u6e2c\u3001\u5be6\u969b\u958b\u734e\u3001\u547d\u4e2d\u865f\u78bc\u8207\u91cd\u8dd1\u5feb\u7167\u6578\u90fd\u6c38\u4e45\u4fdd\u7559\u3002</p>
      <table><thead><tr><th>\u76ee\u6a19\u671f</th><th>\u72c0\u614b</th><th>\u4f9d\u64da\u671f</th><th>\u7576\u671f\u6b63\u5f0f Top10</th><th>\u5be6\u969b\u958b\u734e</th><th>Top10 \u547d\u4e2d\u865f</th><th>Top5</th><th>Top10</th><th>Top15</th><th>\u5feb\u7167\u6578</th><th>\u5efa\u7acb / \u7d50\u7b97</th></tr></thead><tbody>{history_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u822a\u592a\u7d1a\u904b\u7b97\u4fdd\u8b49\u5be9\u6838</h2>
      <p>\u5be9\u6838\u72c0\u614b\uff1a{aerospace.get('release_assurance', {}).get('status')} / \u4fdd\u8b49\u5206\u6578 {aerospace.get('release_assurance', {}).get('assurance_score')}</p>
      <p>\u8cc7\u6599\u6307\u7d0b SHA-256\uff1a{aerospace.get('input_fingerprint_sha256', '')}</p>
      <p>\u8f38\u51fa\u6307\u7d0b SHA-256\uff1a{aerospace.get('output_fingerprint_sha256', '')}</p>
      <p>\u8cc7\u6599\u4e0d\u8b8a\u689d\u4ef6\uff1a{aerospace.get('input_invariants', {}).get('passed')} / \u5931\u6557 {aerospace.get('input_invariants', {}).get('failure_count')}</p>
      <p>\u96d9\u901a\u9053\u4ea4\u53c9\u9a57\u8b49\uff1a{aerospace.get('redundant_channel_audit', {}).get('status')} / Top10 \u91cd\u758a {aerospace.get('redundant_channel_audit', {}).get('overlap_count')} / Jaccard {aerospace.get('redundant_channel_audit', {}).get('jaccard')}</p>
      <p>\u6a21\u578b\u6f02\u79fb\uff1a{aerospace.get('drift_audit', {}).get('status')} / TV {aerospace.get('drift_audit', {}).get('total_variation')}</p>
      <p>\u8499\u5730\u5361\u7f85\u64fe\u52d5\u6e2c\u8a66\uff1a{aerospace.get('uncertainty_audit', {}).get('simulations')} \u6b21 / Top10 \u4fdd\u7559\u7387 {aerospace.get('uncertainty_audit', {}).get('top10_retention')} / {aerospace.get('uncertainty_audit', {}).get('status')}</p>
      <table><thead><tr><th>\u865f\u78bc</th><th>\u539f\u6392\u540d</th><th>\u64fe\u52d5\u5f8c Top10 \u7559\u5b58\u7387</th></tr></thead><tbody>{uncertainty_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u9032\u968e\u9810\u6e2c\u6a21\u578b</h2>
      <p>{advanced.get('warning', '')}</p>
      <p>\u9032\u968e\u6a21\u578b\u5171\u8b58 Top12\uff1a{fmt_numbers(advanced.get('consensus_top12', []))}</p>
      <table><thead><tr><th>\u6a21\u578b</th><th>Top10</th><th>Top10 \u56de\u6e2c</th><th>\u5c0d\u96a8\u6a5f\u5dee\u503c</th><th>\u65b9\u6cd5</th></tr></thead><tbody>{advanced_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u7db2\u8def\u4eba\u6c23\u5171\u8b58\uff08\u672a\u901a\u904e\u56de\u6e2c\u524d\u4e0d\u5f71\u97ff\u4e3b\u6a21\u578b\uff09</h2>
      <p>{crowd.get('warning', '')}</p>
      <table><thead><tr><th>\u865f\u78bc</th><th>\u4f86\u6e90\u7968\u6578</th><th>\u8207\u7cfb\u7d71\u95dc\u4fc2</th></tr></thead><tbody>{crowd_rows}</tbody></table>
      <h3>\u4f86\u6e90\u771f\u5be6\u7e3e\u6548</h3>
      <table><thead><tr><th>\u4f86\u6e90</th><th>\u5df2\u7d50\u7b97</th><th>\u5e73\u5747\u547d\u4e2d</th><th>\u8fd130\u671f</th><th>\u5c0d\u96a8\u6a5f\u5dee\u503c</th><th>\u6a21\u578b\u6b0a\u91cd\u4e0a\u9650</th></tr></thead><tbody>{crowd_source_rows}</tbody></table>
      <h3>\u672c\u6b21\u81ea\u52d5\u6293\u53d6\u72c0\u614b</h3>
      <p>\u6536\u96c6\u7b46\u6578\uff1a{crowd.get('collection', {}).get('collected', 0)} / \u4f86\u6e90\u6e05\u55ae\uff1a{crowd.get('collection', {}).get('source_list_count', 0)}</p>
      <table><thead><tr><th>\u8b66\u544a\u6216\u9650\u5236</th></tr></thead><tbody>{crowd_warning_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>{'\u4eca\u65e5\u6b63\u5f0f\u4e3b\u63a8' if release_status == 'official' else '\u4eca\u65e5\u89c0\u5bdf\u5019\u9078\uff08\u4e0d\u5217\u6b63\u5f0f\u4e3b\u63a8\uff09'}</h2>
      <p>{observation_note}</p>
    </section>
    <div class="grid">
      {''.join(pack_cards)}
    </div>
    <section class="band">
      <h2>\u5de5\u696d\u7d1a\u6a21\u578b\u5be9\u8a08</h2>
      <p><span class="risk">\u98a8\u96aa\u7b49\u7d1a\uff1a{risk}</span></p>
      <p>{verdict}</p>
      <p>\u958b\u734e\u578b\u614b\uff1a{regime_messages}</p>
    </section>
    <section class="band">
      <h2>\u4f4e\u6a5f\u7387\u66ab\u907f\u865f\u78bc\uff08\u98a8\u63a7\u89c0\u5bdf\uff09</h2>
      <p>{unlikely.get('warning', '')}</p>
      <p>\u56de\u6e2c\uff1a\u8fd1 {unlikely_backtest.get('rounds')} \u671f\uff0c\u66ab\u907f {unlikely_backtest.get('avoid_size')} \u78bc\u5e73\u5747\u8aa4\u4e2d {unlikely_backtest.get('avg_accidental_hits')}\uff0c\u96a8\u6a5f\u57fa\u6e96 {unlikely_backtest.get('random_expectation')}\uff0c\u5dee\u503c {unlikely_backtest.get('edge_vs_random')}\uff0c\u5b8c\u5168\u907f\u958b\u7387 {unlikely_backtest.get('zero_hit_rate')}</p>
      <table><thead><tr><th>#</th><th>\u865f\u78bc</th><th>\u66ab\u907f\u6307\u6578</th><th>\u51fa\u73fe\u8a55\u5206</th><th>\u5019\u9078\u6392\u540d</th><th>\u7a69\u5b9a\u6b21\u6578</th><th>\u66ab\u907f\u539f\u56e0</th></tr></thead><tbody>{unlikely_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u4e0a\u671f\u6b63\u5f0f\u9810\u6e2c\u547d\u4e2d\u89e3\u6790</h2>
      <p>\u9810\u6e2c\u4f9d\u64da\u671f {settled_prediction.get('based_on_period', '')} / \u5be6\u969b\u958b\u734e\u671f {settled_prediction.get('actual_period', '')}</p>
      <p>{settled_actual_html}</p>
      <table><thead><tr><th>\u865f\u78bc</th><th>\u72c0\u614b</th><th>\u5019\u9078\u6392\u540d</th><th>\u547d\u4e2d\u4f86\u6e90\u95dc\u806f\u89e3\u6790</th></tr></thead><tbody>{settled_rows_html}</tbody></table>
    </section>
    <section class="band">
      <h2>\u6628\u65e5\u6b63\u5f0f\u9810\u6e2c\u9010\u865f\u6aa2\u8a0e</h2>
      <table><thead><tr><th>\u6392\u540d</th><th>\u865f\u78bc</th><th>\u7d50\u679c</th><th>\u4fe1\u5fc3</th><th>\u907a\u6f0f</th><th>\u539f\u59cb\u4f86\u6e90</th><th>\u6aa2\u8a0e\u52d5\u4f5c</th></tr></thead><tbody>{candidate_review_html}</tbody></table>
    </section>
    <section class="band">
      <h2>\u6628\u65e5\u53c3\u8003\u7d44\u5408\u8207\u5f37\u724c\u6aa2\u8a0e</h2>
      <h3>\u53c3\u8003\u7d44\u5408</h3>
      <table><thead><tr><th>\u7d44\u5225</th><th>\u539f\u9810\u6e2c</th><th>\u547d\u4e2d\u6578</th><th>\u547d\u4e2d\u865f</th><th>\u672a\u547d\u4e2d\u865f</th></tr></thead><tbody>{set_review_html}</tbody></table>
      <h3>\u5f37\u724c\u7d44</h3>
      <table><thead><tr><th>\u5f37\u724c</th><th>\u539f\u9810\u6e2c</th><th>\u76ee\u6a19</th><th>\u5be6\u969b</th><th>\u7d50\u679c</th><th>\u547d\u4e2d\u865f</th><th>\u672a\u547d\u4e2d\u865f</th></tr></thead><tbody>{pack_review_html}</tbody></table>
    </section>
    <section class="band">
      <h2>\u6628\u65e5\u4f86\u6e90\u7406\u7531\u6210\u6557\u7d71\u8a08</h2>
      <table><thead><tr><th>\u4f86\u6e90\u7406\u7531</th><th>\u547d\u4e2d</th><th>\u672a\u547d\u4e2d</th><th>\u6d89\u53ca\u865f\u78bc</th><th>\u4fee\u6b63\u65b9\u5411</th></tr></thead><tbody>{reason_review_html}</tbody></table>
    </section>
    <section class="band">
      <h2>\u901a\u904e\u6a23\u672c\u5916\u9a57\u8b49\u7684\u865f\u78bc\u9023\u52d5</h2>
      <p>\u901a\u904e\u9023\u52d5\u6578\uff1a{dependency.get('validated_link_count', 0)}\u3002\u95dc\u806f\u4e0d\u7b49\u65bc\u56e0\u679c\uff0c\u672a\u904e\u986f\u8457\u6027\u9580\u6abb\u8005\u5168\u90e8\u6dd8\u6c70\u3002</p>
      <table><thead><tr><th>\u4f86\u6e90</th><th>\u76ee\u6a19</th><th>\u4e09\u5340\u6bb5\u6a23\u672c</th><th>\u4e09\u5340\u6bb5\u63d0\u5347</th><th>\u4e09\u5340\u6bb5Z</th><th>P\u503c</th><th>FDR</th><th>\u4fdd\u5b88\u63d0\u5347</th></tr></thead><tbody>{dependency_rows_html}</tbody></table>
    </section>
    <section class="band">
      <h2>9\u4e2d3 \u8f2a\u7d44\u8986\u84cb</h2>
      <p>\u8986\u84cb\uff1a{coverage.get('covered')}/{coverage.get('total')} / \u8986\u84cb\u7387 {coverage.get('rate')}</p>
      <table><thead><tr><th>#</th><th>\u7d44\u5408</th></tr></thead><tbody>{wheel_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u5019\u9078 Top 15</h2>
      <table><thead><tr><th>#</th><th>\u865f\u78bc</th><th>\u6307\u6578</th><th>\u907a\u6f0f</th><th>\u7406\u7531</th></tr></thead><tbody>{candidate_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u4f4e\u6a5f\u7387\u66ab\u907f\u865f\u78bc\uff08\u98a8\u63a7\u89c0\u5bdf\uff09</h2>
      <p>{unlikely.get('warning', '')}</p>
      <p>\u56de\u6e2c\uff1a\u8fd1 {unlikely_backtest.get('rounds')} \u671f\uff0c\u66ab\u907f {unlikely_backtest.get('avoid_size')} \u78bc\u5e73\u5747\u8aa4\u4e2d {unlikely_backtest.get('avg_accidental_hits')}\uff0c\u96a8\u6a5f\u57fa\u6e96 {unlikely_backtest.get('random_expectation')}\uff0c\u5dee\u503c {unlikely_backtest.get('edge_vs_random')}\uff0c\u5b8c\u5168\u907f\u958b\u7387 {unlikely_backtest.get('zero_hit_rate')}</p>
      <table><thead><tr><th>#</th><th>\u865f\u78bc</th><th>\u66ab\u907f\u6307\u6578</th><th>\u51fa\u73fe\u8a55\u5206</th><th>\u5019\u9078\u6392\u540d</th><th>\u7a69\u5b9a\u6b21\u6578</th><th>\u66ab\u907f\u539f\u56e0</th></tr></thead><tbody>{unlikely_rows}</tbody></table>
    </section>
    <section class="band">
      <h2>\u539f\u59cb\u6230\u5831</h2>
      <pre>{plain_html}</pre>
    </section>
  </main>
</body>
</html>"""


def build_history_html(history):
    rows = ""
    for item in history:
        status = "\u5df2\u7d50\u7b97" if item.get("status") == "settled" else "\u5f85\u7d50\u7b97"
        rows += (
            "<tr>"
            f"<td>{item.get('target_period')}</td><td>{status}</td>"
            f"<td>{item.get('based_on_period')} / {item.get('based_on_date', '')}</td>"
            f"<td>{fmt_numbers(item.get('top10', []))}</td>"
            f"<td>{fmt_numbers(item.get('actual_numbers', [])) or '-'}</td>"
            f"<td>{fmt_numbers(item.get('top10_hit_numbers', [])) or '-'}</td>"
            f"<td>{item.get('top5_hits') if item.get('top5_hits') is not None else '-'}</td>"
            f"<td>{item.get('top10_hits') if item.get('top10_hits') is not None else '-'}</td>"
            f"<td>{item.get('top15_hits') if item.get('top15_hits') is not None else '-'}</td>"
            f"<td>{item.get('snapshot_count', 0)}</td>"
            "</tr>"
        )
    settled = [item for item in history if item.get("status") == "settled"]
    average_top10 = (
        round(sum(item.get("top10_hits") or 0 for item in settled) / len(settled), 3)
        if settled else 0
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>539 \u6bcf\u671f\u9810\u6e2c\u5c0d\u6bd4</title>
  <style>
    body {{ margin:0; font-family:"Microsoft JhengHei", Arial, sans-serif; background:#f6f7fb; color:#20242a; }}
    header {{ background:#0f172a; color:white; padding:22px 28px; }}
    main {{ max-width:1400px; margin:0 auto; padding:22px; }}
    .band {{ background:white; border:1px solid #e5e7eb; border-radius:8px; padding:18px; overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; min-width:1100px; }}
    th, td {{ border-bottom:1px solid #e5e7eb; padding:9px; text-align:left; }}
    th {{ background:#f1f5f9; }}
  </style>
</head>
<body>
  <header>
    <h1>539 \u6bcf\u671f\u9810\u6e2c\u5c0d\u6bd4</h1>
    <p>\u6b63\u5f0f\u9810\u6e2c\u671f\u6578 {len(history)} / \u5df2\u7d50\u7b97 {len(settled)} / Top10 \u5e73\u5747\u547d\u4e2d {average_top10}</p>
  </header>
  <main>
    <section class="band">
      <table><thead><tr><th>\u76ee\u6a19\u671f</th><th>\u72c0\u614b</th><th>\u4f9d\u64da\u671f</th><th>\u6b63\u5f0f Top10</th><th>\u5be6\u969b\u958b\u734e</th><th>Top10 \u547d\u4e2d\u865f</th><th>Top5</th><th>Top10</th><th>Top15</th><th>\u5feb\u7167\u6578</th></tr></thead><tbody>{rows}</tbody></table>
    </section>
  </main>
</body>
</html>"""


def save_battle_reports(report=None):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = report or build_report()
    html = build_html_report(report)
    history = prediction_history()
    save_prediction_history(history)
    history_html = build_history_html(history)
    BATTLE_MD.write_text(report, encoding="utf-8")
    BATTLE_TXT.write_text(report, encoding="utf-8")
    BATTLE_HTML.write_text(html, encoding="utf-8")
    ENHANCED_BATTLE_HTML.write_text(html, encoding="utf-8")
    HISTORY_HTML.write_text(history_html, encoding="utf-8")
    return ENHANCED_BATTLE_HTML


def main():
    output = save_battle_reports()
    print(f"\u6230\u5831\u5b8c\u6210：{output}")


if __name__ == "__main__":
    main()

