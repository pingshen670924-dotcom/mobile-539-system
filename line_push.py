import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"
ANALYSIS_JSON = REPORT_DIR / "latest_analysis.json"
HISTORY_JSON = REPORT_DIR / "prediction_history.json"
STATUS_JSON = REPORT_DIR / "line_push_status.json"
SETTINGS_JSON = BASE_DIR / "line_settings.json"


def taipei_now_text():
    return datetime.now().isoformat(timespec="seconds")


def load_json(path, default):
    try:
        if not path.exists():
            return default
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return default
        return json.loads(text)
    except Exception:
        return default


def fmt_numbers(numbers):
    return " ".join(f"{int(number):02d}" for number in numbers if number is not None)


def extract_candidate_numbers(candidates, limit):
    values = []
    for item in candidates[:limit]:
        if isinstance(item, dict):
            values.append(item.get("number"))
        else:
            values.append(item)
    return [number for number in values if number is not None]


def load_settings():
    settings = load_json(SETTINGS_JSON, {})
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or settings.get("channel_access_token", "")
    to_id = os.environ.get("LINE_TO_ID") or settings.get("to_id", "")
    delivery_mode = os.environ.get("LINE_DELIVERY_MODE") or settings.get("delivery_mode", "broadcast")
    return token.strip(), to_id.strip(), delivery_mode.strip().lower()


def load_mobile_url():
    for path in BASE_DIR.glob("*版網址.txt"):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return ""


def build_message():
    analysis = load_json(ANALYSIS_JSON, {})
    history_payload = load_json(HISTORY_JSON, {})
    history = history_payload.get("periods", [])
    latest = analysis.get("latest_draw", {})
    candidates = analysis.get("official_candidates") or analysis.get("candidates", [])
    top10 = fmt_numbers(extract_candidate_numbers(candidates, 10))
    top15 = fmt_numbers(extract_candidate_numbers(candidates, 15))
    packs = analysis.get("strong_prediction_packs", {})
    freshness = analysis.get("data_freshness", {})
    mode = analysis.get("prediction_mode", "")
    latest_period = latest.get("period", "")
    latest_date = latest.get("draw_date", "")
    target_period = latest_period + 1 if isinstance(latest_period, int) else ""
    pending = next((item for item in history if item.get("status") == "pending"), {})
    settled = next((item for item in history if item.get("status") == "settled"), {})
    mobile_url = load_mobile_url()

    lines = [
        "539每日戰報已更新",
        f"時間：{taipei_now_text()}",
        f"模式：{mode or '正式運算'}",
        f"最新開獎：{latest_period} / {latest_date} / {fmt_numbers(latest.get('numbers', []))}",
        f"資料狀態：{freshness.get('status', 'unknown')} / 應有日期 {freshness.get('expected_latest_date', '')}",
        f"預測目標：{pending.get('target_period', target_period)} / 預計開獎日 {pending.get('target_expected_date', '')}",
        f"Top10：{top10}",
        f"Top15：{top15}",
    ]

    pack_labels = [
        ("strong_single", "最強單支"),
        ("two_hit_one", "最強2中1"),
        ("three_hit_one", "最強3中1"),
        ("five_hit_two", "最強5中2"),
        ("nine_hit_three", "最強9中3"),
    ]
    for key, label in pack_labels:
        pack = packs.get(key, {})
        numbers = fmt_numbers(pack.get("numbers", []))
        if numbers:
            lines.append(f"{label}：{numbers}")

    if settled:
        lines.append(
            "上期檢討："
            f"{settled.get('target_period')} / 實際 {settled.get('actual_date')} / "
            f"Top5 {settled.get('top5_hits')} / Top10 {settled.get('top10_hits')} / Top15 {settled.get('top15_hits')}"
        )
    if mobile_url:
        lines.append(f"手機戰報：{mobile_url}")
    else:
        lines.append("手機戰報：請先執行手機版一鍵上線")
    lines.append("提醒：本系統為統計研究，不保證開出。")
    return "\n".join(lines)[:4900]


def save_status(payload):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def push_message(token, to_id, delivery_mode, text):
    if delivery_mode == "broadcast":
        endpoint = "https://api.line.me/v2/bot/message/broadcast"
        payload = {"messages": [{"type": "text", "text": text}]}
    else:
        endpoint = "https://api.line.me/v2/bot/message/push"
        payload = {"to": to_id, "messages": [{"type": "text", "text": text}]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def main():
    token, to_id, delivery_mode = load_settings()
    if not token or (delivery_mode != "broadcast" and not to_id):
        save_status(
            {
                "generated_at": taipei_now_text(),
                "status": "skipped",
                "reason": "LINE settings are not configured.",
                "delivery_mode": delivery_mode,
            }
        )
        print("LINE push skipped: settings are not configured.")
        return 0

    text = build_message()
    try:
        status_code, response_text = push_message(token, to_id, delivery_mode, text)
        save_status(
            {
                "generated_at": taipei_now_text(),
                "status": "sent",
                "delivery_mode": delivery_mode,
                "http_status": status_code,
                "response": response_text,
            }
        )
        print("LINE push sent.")
        return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        save_status(
            {
                "generated_at": taipei_now_text(),
                "status": "failed",
                "delivery_mode": delivery_mode,
                "http_status": exc.code,
                "error": detail,
            }
        )
        print(f"LINE push failed: HTTP {exc.code}")
        return 1
    except Exception as exc:
        save_status(
            {
                "generated_at": taipei_now_text(),
                "status": "failed",
                "delivery_mode": delivery_mode,
                "error": str(exc),
            }
        )
        print(f"LINE push failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
