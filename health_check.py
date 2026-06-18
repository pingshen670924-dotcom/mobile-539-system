import json
import sqlite3
import subprocess
import time
from collections import defaultdict
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path

from research_kpi import evaluate_research_kpis


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backups"
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
HEALTH_JSON = REPORT_DIR / "health_status.json"
HEALTH_MD = REPORT_DIR / "health_status.md"
OBSOLETE_RUNTIME_NAMES = [
    "cleanup_archive_20260615_094319",
    "cleanup_archive_20260615_094339",
    "cleanup_archive_20260615_094440",
    "cleanup_archive_20260615_094636",
    "539-mobile-cloud-deploy",
    "\u514d\u8cbb\u624b\u6a5f\u7368\u7acb\u7248",
    "\u5c01\u5b58_\u820a\u7684\u4e00\u9375\u6309\u9215",
]

TEXT = {
    "title": "\u4eca\u5f69539 \u7cfb\u7d71\u5065\u5eb7\u6aa2\u67e5",
    "none": "\u7121",
    "sandbox_message": (
        "Codex \u6c99\u76d2\u5916\u9023\u53d7\u9650\uff1b"
        "\u8acb\u4f7f\u7528 Windows \u4e00\u9375\u5165\u53e3\u57f7\u884c\u6bcf\u65e5\u6b63\u5f0f\u66f4\u65b0"
    ),
    "sandbox_risk": (
        "Codex \u6c99\u76d2\u5916\u9023\u9650\u5236\uff1b"
        "Windows \u4e00\u9375\u5165\u53e3\u53ef\u57f7\u884c\u6b63\u5f0f\u66f4\u65b0\uff0c\u4e14\u672c\u6a5f\u8cc7\u6599\u70ba\u6700\u65b0"
    ),
    "sandbox_short": (
        "\u76ee\u524d\u662f Codex \u6c99\u76d2\u5916\u9023\u9650\u5236\uff1b"
        "Windows \u684c\u9762\u6b63\u5f0f\u57f7\u884c\u8acb\u4f7f\u7528 "
        "539\u4e00\u9375\u5168\u81ea\u52d5\u555f\u52d5.bat \u6216 539-Windows\u5916\u5c64\u66f4\u65b0.bat\u3002"
    ),
}


def safe_write_text(path, text, encoding="utf-8", retries=8, delay=0.35):
    temp_path = path.with_name(path.name + ".tmp")
    last_error = None
    for _ in range(retries):
        try:
            temp_path.write_text(text, encoding=encoding)
            temp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(delay)
    raise last_error


def fetch_one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def codex_sandbox_block_visible():
    try:
        completed = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=codex_sandbox_offline_block_outbound"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return "codex_sandbox_offline_block_outbound" in output
    except Exception:
        return False


def short_last_run_message(message):
    message = message or ""
    if "WinError 10013" in message and codex_sandbox_block_visible():
        return TEXT["sandbox_short"]
    if len(message) > 360:
        return message[:360] + "..."
    return message


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
    kpi_records = []
    pack_stats = defaultdict(lambda: {"rounds": 0, "passed": 0, "hits": 0})
    for row in rows:
        set_hits.extend(item["hits"] for item in json.loads(row[3] or "[]"))
        strong_pack_hits = json.loads(row[4] or "{}")
        kpi_records.append({"top15_hits": row[2], "strong_pack_hits": strong_pack_hits})
        for key, item in strong_pack_hits.items():
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
        "research_kpi": evaluate_research_kpis(kpi_records),
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
        "notices": [],
    }
    if not DB_PATH.exists():
        health["status"] = "failed"
        health["warnings"].append("database missing")
        return health

    with sqlite3.connect(DB_PATH) as conn:
        stats = fetch_one(conn, "SELECT COUNT(*), MIN(period), MAX(period), MIN(draw_date), MAX(draw_date) FROM draws_539")
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
        pending_predictions = fetch_one(conn, "SELECT COUNT(*) FROM predictions_539 WHERE status='pending'")[0]
        settled_predictions = fetch_one(conn, "SELECT COUNT(*) FROM predictions_539 WHERE status='settled'")[0]
        prediction_snapshots = fetch_one(conn, "SELECT COUNT(*) FROM prediction_snapshots_539")[0]
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
                    "message": short_last_run_message(last_run[4] if last_run else None),
                },
                "pending_predictions": pending_predictions,
                "settled_predictions": settled_predictions,
                "prediction_snapshots": prediction_snapshots,
                "prediction_performance": prediction_performance(conn),
                "invalid_draw_count": invalid_count,
            }
        )

    analysis_period = None
    analysis_based_on_period = None
    if latest_analysis_path.exists():
        try:
            analysis_payload = json.loads(latest_analysis_path.read_text(encoding="utf-8"))
            analysis_period = analysis_payload.get("latest_draw", {}).get("period")
            analysis_based_on_period = analysis_payload.get("latest_draw", {}).get("period")
        except (OSError, json.JSONDecodeError, AttributeError):
            health["status"] = "warning"
            health["warnings"].append("latest analysis cannot be read")

    database_period = health.get("latest_draw", {}).get("period")
    health["analysis_sync"] = {
        "database_latest_period": database_period,
        "analysis_latest_period": analysis_period,
        "prediction_based_on_period": analysis_based_on_period,
        "status": "synced" if str(analysis_period) == str(database_period) else "behind",
    }
    if latest_analysis_path.exists() and str(analysis_period) != str(database_period):
        health["status"] = "warning"
        health["warnings"].append("latest analysis/report is behind database")

    last_run = health.get("last_run", {})
    if last_run.get("status") != "success":
        message = last_run.get("message") or ""
        if health.get("data_freshness", {}).get("status") == "fresh" and ("WinError 10013" in message or "Codex" in message):
            health["external_risk"] = TEXT["sandbox_risk"]
            health["notices"].append(TEXT["sandbox_message"])
        else:
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
    obsolete_existing = [name for name in OBSOLETE_RUNTIME_NAMES if (BASE_DIR / name).exists()]
    health["cleanup"] = {
        "status": "ok" if not obsolete_existing else "pending_windows_cleanup",
        "obsolete_folder_count": len(obsolete_existing),
        "obsolete_folders": obsolete_existing,
        "cleanup_method": "handled automatically by the one-click Windows launcher",
    }
    health["data"] = {
        "latest_period": health.get("latest_draw", {}).get("period"),
        "latest_draw_date": health.get("latest_draw", {}).get("draw_date"),
        "latest_numbers": health.get("latest_draw", {}).get("numbers", []),
        "freshness": health.get("data_freshness", {}).get("status"),
    }
    version_path = BASE_DIR / "site" / "version.json"
    mobile = {"status": "missing"}
    if version_path.exists():
        try:
            version = json.loads(version_path.read_text(encoding="utf-8"))
            mobile = {
                "status": "built",
                "version": version.get("version"),
                "mobile_built_at": version.get("mobile_built_at"),
                "latest_period": version.get("latest_period"),
                "latest_draw_date": version.get("latest_draw_date"),
            }
        except (OSError, json.JSONDecodeError, AttributeError):
            mobile = {"status": "unreadable"}
    health["mobile"] = mobile
    return health


def save_health(health):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_text(HEALTH_JSON, json.dumps(health, ensure_ascii=False, indent=2))

    latest = health.get("latest_draw", {})
    performance = health.get("prediction_performance", {})
    warnings = "\u3001".join(health["warnings"]) if health["warnings"] else TEXT["none"]
    lines = [
        f"# {TEXT['title']}",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{health['generated_at']}",
        f"- \u72c0\u614b\uff1a{health['status']}",
        f"- \u8b66\u544a\uff1a{warnings}",
        f"- \u5916\u90e8\u98a8\u96aa\uff1a{health.get('external_risk', TEXT['none'])}",
        f"- \u8cc7\u6599\u7b46\u6578\uff1a{health.get('draw_count', 0)}",
        f"- \u6700\u65b0\u671f\u5225\uff1a{latest.get('period')} ({latest.get('draw_date')})",
        "- \u6700\u65b0\u865f\u78bc\uff1a" + " ".join(f"{n:02d}" for n in latest.get("numbers", [])),
        f"- \u5206\u6790\u540c\u6b65\uff1a{health.get('analysis_sync', {}).get('status')} / {health.get('analysis_sync', {}).get('analysis_latest_period')}",
        f"- \u6700\u8fd1\u66f4\u65b0\uff1a{health.get('last_run', {}).get('status')} / {health.get('last_run', {}).get('finished_at')}",
        f"- \u5099\u4efd\u6578\u91cf\uff1a{health.get('backup_count', 0)}",
        f"- \u5f85\u7d50\u7b97\u9810\u6e2c\uff1a{health.get('pending_predictions', 0)}",
        f"- \u5df2\u7d50\u7b97\u9810\u6e2c\uff1a{health.get('settled_predictions', 0)}",
        f"- \u9810\u6e2c\u5feb\u7167\uff1a{health.get('prediction_snapshots', 0)}",
        f"- \u5be6\u969b Top10 \u5e73\u5747\u547d\u4e2d\uff1a{performance.get('top10_avg_hits', '\u5c1a\u7121\u8cc7\u6599')}",
        "",
    ]
    safe_write_text(HEALTH_MD, "\n".join(lines))


def main():
    health = build_health()
    save_health(health)
    print(f"health check: {health['status']}")
    print(f"report: {HEALTH_MD}")


if __name__ == "__main__":
    main()
