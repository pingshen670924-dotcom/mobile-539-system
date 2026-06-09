import json
import sqlite3
from collections import defaultdict
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backups"
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
HEALTH_JSON = REPORT_DIR / "health_status.json"
HEALTH_MD = REPORT_DIR / "health_status.md"


def fetch_one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def expected_latest_draw_date(now=None):
    now = now or datetime.now()
    candidate = now.date()
    if now.time() < clock_time(21, 0):
        candidate -= timedelta(days=1)
    while candidate.weekday() == 6:
        candidate -= timedelta(days=1)
    return candidate.isoformat()


def prediction_performance(conn):
    rows = conn.execute(
        """
        SELECT top5_hits, top10_hits, top15_hits, set_hits_json, strong_pack_hits_json
        FROM predictions_539
        WHERE status='settled'
        """
    ).fetchall()
    if not rows:
        return {"settled": 0}
    set_hits = []
    pack_stats = defaultdict(lambda: {"rounds": 0, "passed": 0, "hits": 0})
    for row in rows:
        set_hits.extend(item["hits"] for item in json.loads(row[3] or "[]"))
        for key, item in json.loads(row[4] or "{}").items():
            pack_stats[key]["rounds"] += 1
            pack_stats[key]["passed"] += 1 if item.get("passed") else 0
            pack_stats[key]["hits"] += item.get("hits", 0)
    count = len(rows)
    return {
        "settled": count,
        "top5_avg_hits": round(sum(row[0] for row in rows) / count, 3),
        "top10_avg_hits": round(sum(row[1] for row in rows) / count, 3),
        "top15_avg_hits": round(sum(row[2] for row in rows) / count, 3),
        "set_avg_hits": round(sum(set_hits) / len(set_hits), 3) if set_hits else 0,
        "strong_pack_stats": {
            key: {
                "rounds": value["rounds"],
                "pass_rate": round(value["passed"] / value["rounds"], 3) if value["rounds"] else 0,
                "avg_hits": round(value["hits"] / value["rounds"], 3) if value["rounds"] else 0,
            }
            for key, value in pack_stats.items()
        },
    }


def build_health():
    backups = sorted(BACKUP_DIR.glob("539_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    log_path = LOG_DIR / "update.log"
    latest_analysis_path = REPORT_DIR / "latest_analysis.json"

    health = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "database_exists": DB_PATH.exists(),
        "backup_count": len(backups),
        "latest_backup": str(backups[0]) if backups else None,
        "log_exists": log_path.exists(),
        "latest_analysis_exists": latest_analysis_path.exists(),
        "status": "ok",
        "warnings": [],
    }

    if not DB_PATH.exists():
        health["status"] = "failed"
        health["warnings"].append("database missing")
        return health

    with sqlite3.connect(DB_PATH) as conn:
        stats = fetch_one(
            conn,
            """
            SELECT COUNT(*), MIN(period), MAX(period), MIN(draw_date), MAX(draw_date)
            FROM draws_539
            """,
        )
        latest = fetch_one(
            conn,
            """
            SELECT period, draw_date, n1, n2, n3, n4, n5, source, fetched_at
            FROM draws_539
            ORDER BY period DESC
            LIMIT 1
            """,
        )
        last_run = fetch_one(
            conn,
            """
            SELECT run_type, started_at, finished_at, status, message
            FROM update_runs
            ORDER BY id DESC
            LIMIT 1
            """,
        )
        pending_predictions = fetch_one(
            conn,
            "SELECT COUNT(*) FROM predictions_539 WHERE status='pending'",
        )[0]
        settled_predictions = fetch_one(
            conn,
            "SELECT COUNT(*) FROM predictions_539 WHERE status='settled'",
        )[0]
        prediction_snapshots = fetch_one(
            conn,
            "SELECT COUNT(*) FROM prediction_snapshots_539",
        )[0]
        invalid_count = fetch_one(
            conn,
            """
            SELECT COUNT(*)
            FROM draws_539
            WHERE n1 NOT BETWEEN 1 AND 39
               OR n2 NOT BETWEEN 1 AND 39
               OR n3 NOT BETWEEN 1 AND 39
               OR n4 NOT BETWEEN 1 AND 39
               OR n5 NOT BETWEEN 1 AND 39
               OR n1 IN (n2,n3,n4,n5)
               OR n2 IN (n3,n4,n5)
               OR n3 IN (n4,n5)
               OR n4 = n5
            """,
        )[0]

        health.update(
            {
                "draw_count": stats[0],
                "period_range": [stats[1], stats[2]],
                "date_range": [stats[3], stats[4]],
                "latest_draw": {
                    "period": latest[0],
                    "draw_date": latest[1],
                    "numbers": list(latest[2:7]),
                    "source": latest[7],
                    "fetched_at": latest[8],
                },
                "data_freshness": {
                    "status": "fresh" if latest[1] >= expected_latest_draw_date() else "stale",
                    "latest_date": latest[1],
                    "expected_latest_date": expected_latest_draw_date(),
                },
                "last_run": {
                    "run_type": last_run[0] if last_run else None,
                    "started_at": last_run[1] if last_run else None,
                    "finished_at": last_run[2] if last_run else None,
                    "status": last_run[3] if last_run else None,
                    "message": last_run[4] if last_run else None,
                },
                "pending_predictions": pending_predictions,
                "settled_predictions": settled_predictions,
                "prediction_snapshots": prediction_snapshots,
                "prediction_performance": prediction_performance(conn),
                "invalid_draw_count": invalid_count,
            }
        )

    if health["last_run"]["status"] != "success":
        health["status"] = "warning"
        health["warnings"].append("last update run was not successful")
    if health.get("data_freshness", {}).get("status") != "fresh":
        health["status"] = "warning"
        health["warnings"].append("database is behind the expected latest draw date")
    if health["invalid_draw_count"]:
        health["status"] = "failed"
        health["warnings"].append("invalid draw rows found")
    if not backups:
        health["status"] = "warning"
        health["warnings"].append("no database backup found")
    if not latest_analysis_path.exists():
        health["status"] = "warning"
        health["warnings"].append("latest analysis missing")

    return health


def save_health(health):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    HEALTH_JSON.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")

    latest = health.get("latest_draw", {})
    performance = health.get("prediction_performance", {})
    lines = [
        "# 539 \u7cfb\u7d71\u5065\u5eb7\u6aa2\u67e5",
        "",
        f"- \u7522\u751f\u6642\u9593：{health['generated_at']}",
        f"- \u72c0\u614b：{health['status']}",
        f"- \u8b66\u544a：{', '.join(health['warnings']) if health['warnings'] else '\u7121'}",
        f"- \u8cc7\u6599\u7b46\u6578：{health.get('draw_count', 0)}",
        f"- \u6700\u65b0\u671f\u5225：{latest.get('period')} ({latest.get('draw_date')})",
        "- \u6700\u65b0\u865f\u78bc：" + " ".join(f"{n:02d}" for n in latest.get("numbers", [])),
        f"- \u6700\u8fd1\u66f4\u65b0：{health.get('last_run', {}).get('status')} / {health.get('last_run', {}).get('finished_at')}",
        f"- \u5099\u4efd\u6578\u91cf：{health.get('backup_count', 0)}",
        f"- \u5f85\u7d50\u7b97\u9810\u6e2c：{health.get('pending_predictions', 0)}",
        f"- \u5df2\u7d50\u7b97\u9810\u6e2c：{health.get('settled_predictions', 0)}",
        f"- \u9810\u6e2c\u5feb\u7167：{health.get('prediction_snapshots', 0)}",
        f"- \u5be6\u969b Top10 \u5e73\u5747\u547d\u4e2d：{performance.get('top10_avg_hits', '\u5c1a\u7121\u8cc7\u6599')}",
        "",
    ]
    HEALTH_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    health = build_health()
    save_health(health)
    print(f"\u5065\u5eb7\u6aa2\u67e5：{health['status']}")
    print(f"\u5831\u544a：{HEALTH_MD}")


if __name__ == "__main__":
    main()
