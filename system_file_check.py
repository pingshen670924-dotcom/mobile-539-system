import json
import csv
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"
REPORT_JSON = REPORT_DIR / "file_integrity_report.json"
REPORT_MD = REPORT_DIR / "file_integrity_report.md"

TEXT_SUFFIXES = {
    ".py",
    ".ps1",
    ".bat",
    ".md",
    ".txt",
    ".json",
    ".html",
    ".csv",
}
CODE_SUFFIXES = {".py", ".ps1", ".bat"}
CJK_ALLOWED_CODE_FILES = {
    "battle_report.py",
    "daily_midnight_recompute.ps1",
    "industrial_engine.py",
    "line_push.py",
    "pages_build.py",
    "post_draw_mobile_sync.ps1",
    "network_permission_diagnostic.ps1",
    "repair_current_tasks.ps1",
    "repair_network_permission.ps1",
    "setup_line_push.ps1",
    "system_file_check.py",
    "update_539.py",
}
SKIP_DIRS = {
    "__pycache__",
    "backups",
    "logs",
    "539-mobile-cloud-deploy",
    "\u514d\u8cbb\u624b\u6a5f\u7368\u7acb\u7248",
    "\u5c01\u5305\u8f38\u51fa",
}
SKIP_DIR_PREFIXES = (
    "\u820a\u6a94\u6e05\u7406\u5340",
    "TW539\u9810\u6e2c\u7cfb\u7d71_",
)
MOJIBAKE_MARKERS = ["\ufffd", "\u5697", "\ueaa8", "\uea8f", "\ueaf0", "\uf593"]


def is_skipped(path):
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
        if any(part.startswith(prefix) for prefix in SKIP_DIR_PREFIXES):
            return True
    return False


def has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def scan_file(path):
    item = {
        "path": str(path.relative_to(BASE_DIR)),
        "status": "ok",
        "warnings": [],
        "size": path.stat().st_size,
    }
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        item["status"] = "failed"
        item["warnings"].append(f"utf8_decode_failed: {exc}")
        return item
    except Exception as exc:
        item["status"] = "failed"
        item["warnings"].append(f"read_failed: {exc}")
        return item

    for marker in MOJIBAKE_MARKERS:
        if marker in text:
            item["status"] = "warning"
            item["warnings"].append(f"mojibake_marker_found: U+{ord(marker):04X}")
    rel_path = str(path.relative_to(BASE_DIR))
    if (
        path.suffix.lower() in CODE_SUFFIXES
        and rel_path not in CJK_ALLOWED_CODE_FILES
        and has_cjk(text)
    ):
        item["status"] = "warning"
        item["warnings"].append("direct_cjk_found_in_code")
    return item


def scan():
    files = []
    for path in BASE_DIR.rglob("*"):
        if not path.is_file() or is_skipped(path.relative_to(BASE_DIR)):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files.append(scan_file(path))
    failed = [item for item in files if item["status"] == "failed"]
    warnings = [item for item in files if item["status"] == "warning"]
    consistency = data_consistency_check()
    overall_status = "failed" if failed or consistency["status"] == "failed" else ("warning" if warnings else "ok")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": overall_status,
        "checked_files": len(files),
        "failed_count": len(failed) + (1 if consistency["status"] == "failed" else 0),
        "warning_count": len(warnings),
        "files": files,
        "data_consistency": consistency,
    }


def read_latest_csv_draw():
    csv_path = BASE_DIR / "data" / "539.csv"
    if not csv_path.exists():
        return {"status": "failed", "reason": "data/539.csv missing"}
    latest = None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("period") or not row.get("draw_date"):
                continue
            period = int(row["period"])
            numbers = [int(row[f"n{i}"]) for i in range(1, 6)]
            item = {
                "period": period,
                "draw_date": row["draw_date"],
                "numbers": sorted(numbers),
            }
            if latest is None or period > latest["period"]:
                latest = item
    if latest is None:
        return {"status": "failed", "reason": "data/539.csv has no draw rows"}
    return latest


def data_consistency_check():
    latest_csv = read_latest_csv_draw()
    if latest_csv.get("status") == "failed":
        return {
            "status": "failed",
            "checks": [latest_csv],
        }
    checks = []
    status = "ok"

    analysis_path = REPORT_DIR / "latest_analysis.json"
    if analysis_path.exists():
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        latest_analysis = analysis.get("latest_draw", {})
        analysis_numbers = sorted(int(n) for n in latest_analysis.get("numbers", []))
        ok = (
            int(latest_analysis.get("period", -1)) == latest_csv["period"]
            and latest_analysis.get("draw_date") == latest_csv["draw_date"]
            and analysis_numbers == latest_csv["numbers"]
        )
        checks.append({
            "name": "analysis_matches_csv_latest_draw",
            "status": "ok" if ok else "failed",
            "csv_latest": latest_csv,
            "analysis_latest": {
                "period": latest_analysis.get("period"),
                "draw_date": latest_analysis.get("draw_date"),
                "numbers": analysis_numbers,
            },
        })
        if not ok:
            status = "failed"
    else:
        checks.append({"name": "latest_analysis_exists", "status": "failed"})
        status = "failed"

    health_path = REPORT_DIR / "health_status.json"
    if health_path.exists():
        health = json.loads(health_path.read_text(encoding="utf-8"))
        freshness = health.get("data_freshness", {})
        health_data = health.get("data", {})
        ok = (
            freshness.get("latest_date") == latest_csv["draw_date"]
            and int(health_data.get("latest_period", -1)) == latest_csv["period"]
        )
        checks.append({
            "name": "health_matches_csv_latest_draw",
            "status": "ok" if ok else "failed",
            "csv_latest": latest_csv,
            "health_latest": {
                "period": health_data.get("latest_period"),
                "draw_date": freshness.get("latest_date"),
                "freshness_status": freshness.get("status"),
            },
        })
        if not ok:
            status = "failed"
    else:
        checks.append({"name": "health_status_exists", "status": "failed"})
        status = "failed"

    return {
        "status": status,
        "csv_latest": latest_csv,
        "checks": checks,
    }


def save_report(result):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 539 \u6a94\u6848\u8b80\u53d6\u8207\u7de8\u78bc\u6aa2\u67e5",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{result['generated_at']}",
        f"- \u72c0\u614b\uff1a{result['status']}",
        f"- \u6aa2\u67e5\u6a94\u6848\uff1a{result['checked_files']}",
        f"- \u5931\u6557\uff1a{result['failed_count']}",
        f"- \u8b66\u544a\uff1a{result['warning_count']}",
        f"- \u8cc7\u6599\u4e00\u81f4\u6027\uff1a{result.get('data_consistency', {}).get('status', 'unknown')}",
        "",
    ]
    consistency = result.get("data_consistency", {})
    csv_latest = consistency.get("csv_latest", {})
    if csv_latest:
        lines.append(
            f"- CSV \u6700\u65b0\uff1a{csv_latest.get('period')} / {csv_latest.get('draw_date')} / "
            + " ".join(f"{int(n):02d}" for n in csv_latest.get("numbers", []))
        )
    for item in result["files"]:
        if item["status"] != "ok":
            lines.append(f"- {item['status']}: {item['path']} / {', '.join(item['warnings'])}")
    for check in consistency.get("checks", []):
        if check.get("status") != "ok":
            lines.append(f"- data_consistency_{check.get('status')}: {check.get('name', check.get('reason'))}")
    if result["status"] == "ok":
        lines.append("\u6240\u6709\u6587\u5b57\u6a94\u5747\u53ef\u4ee5 UTF-8 \u6b63\u5e38\u8b80\u53d6\uff0c\u7a0b\u5f0f\u6a94\u672a\u767c\u73fe\u76f4\u63a5\u4e2d\u6587\u6b98\u7559\u3002")
        lines.append("\u958b\u734e CSV\u3001latest_analysis.json\u3001health_status.json \u7684\u6700\u65b0\u671f\u5225\u8207\u865f\u78bc\u4e00\u81f4\u3002")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    result = scan()
    save_report(result)
    print(f"file integrity: {result['status']} ({result['checked_files']} files)")
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
