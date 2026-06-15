import json
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
    "line_push.py",
    "network_permission_diagnostic.ps1",
    "repair_network_permission.ps1",
    "setup_line_push.ps1",
    "system_file_check.py",
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
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "failed" if failed else ("warning" if warnings else "ok"),
        "checked_files": len(files),
        "failed_count": len(failed),
        "warning_count": len(warnings),
        "files": files,
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
        "",
    ]
    for item in result["files"]:
        if item["status"] != "ok":
            lines.append(f"- {item['status']}: {item['path']} / {', '.join(item['warnings'])}")
    if result["status"] == "ok":
        lines.append("\u6240\u6709\u6587\u5b57\u6a94\u5747\u53ef\u4ee5 UTF-8 \u6b63\u5e38\u8b80\u53d6\uff0c\u7a0b\u5f0f\u6a94\u672a\u767c\u73fe\u76f4\u63a5\u4e2d\u6587\u6b98\u7559\u3002")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    result = scan()
    save_report(result)
    print(f"file integrity: {result['status']} ({result['checked_files']} files)")
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
