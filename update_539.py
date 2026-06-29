import argparse
import base64
import csv
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from analyze_539 import analyze, build_sets, save_analysis
from battle_report import ENHANCED_BATTLE_HTML, build_report, save_battle_reports
from dashboard import DASHBOARD_HTML, save_dashboard
from health_check import build_health, save_health
from industrial_engine import score_numbers
from model_competition import run_competition, save_competition
from pages_build import build as build_mobile_site
from research_kpi import evaluate_research_kpis


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups"
DB_PATH = DATA_DIR / "539.sqlite"
CSV_PATH = DATA_DIR / "539.csv"
RUN_LOCK_PATH = BASE_DIR / "logs" / "539_update.lock"

API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB"
DOWNLOAD_API = f"{API_BASE}/Lottery/ResultDownload"
LATEST_API = f"{API_BASE}/Lottery/LatestResult"
HISTORY_API = f"{API_BASE}/Lottery/Daily539Result"
PUBLIC_FALLBACK_LATEST_URL = "https://www.pilio.idv.tw/lto539/drawlist/drawlist.asp"

START_ROC_YEAR = 96
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def taipei_now():
    return datetime.now(TAIPEI_TZ).replace(tzinfo=None)
GAME_NAME = "\u4eca\u5f69539"


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "update.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def roc_year_now():
    return taipei_now().year - 1911


def expected_latest_draw_date(now=None):
    now = now or taipei_now()
    candidate = now.date()
    if now.time() < clock_time(20, 33):
        candidate -= timedelta(days=1)
    while candidate.weekday() == 6:
        candidate -= timedelta(days=1)
    return candidate.isoformat()


def data_freshness(latest_date, now=None):
    now = now or taipei_now()
    expected = expected_latest_draw_date(now)
    latest = datetime.strptime(latest_date, "%Y-%m-%d").date()
    expected_date = datetime.strptime(expected, "%Y-%m-%d").date()
    return {
        "status": "fresh" if latest >= expected_date else "stale",
        "latest_date": latest_date,
        "expected_latest_date": expected,
        "lag_days": max((expected_date - latest).days, 0),
        "checked_at": now.isoformat(timespec="seconds"),
    }


def update_attempt_window_is_open(now=None):
    now = now or taipei_now()
    return now.time() >= clock_time(20, 33)


def http_get_bytes(url, retries=3, retry_delay=2):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 539-data-system/1.0",
            "Accept": "*/*",
        },
    )
    context = ssl._create_unverified_context()
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60, context=context) as response:
                data = response.read()
                if not data:
                    raise RuntimeError("empty response")
                return data
        except Exception as exc:
            last_error = exc
            logging.warning("\u4e0b\u8f09\u5931\u6557，\u7b2c %s/%s \u6b21：%s", attempt, retries, url)
            if attempt < retries:
                time.sleep(retry_delay * attempt)
    logging.warning("Python download failed; trying PowerShell fallback: %s", url)
    try:
        return http_get_bytes_via_powershell(url)
    except Exception as fallback_error:
        raise RuntimeError(f"\u4e0b\u8f09\u5931\u6557：{url} ({last_error}); powershell_fallback={fallback_error}")


def powershell_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def http_get_bytes_via_powershell(url):
    with NamedTemporaryFile(delete=False, suffix=".download") as temp_file:
        temp_path = Path(temp_file.name)
    script = (
        "$ErrorActionPreference='Stop';"
        "$ProgressPreference='SilentlyContinue';"
        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
        f"Invoke-WebRequest -Uri {powershell_quote(url)} "
        "-Headers @{'User-Agent'='Mozilla/5.0 539-data-system/1.0'} "
        f"-UseBasicParsing -TimeoutSec 60 -OutFile {powershell_quote(str(temp_path))};"
    )
    command = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                command,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or "PowerShell download failed.")
        data = temp_path.read_bytes()
        if not data:
            raise RuntimeError("PowerShell download returned empty response.")
        return data
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


def lock_process_is_active():
    try:
        payload = json.loads(RUN_LOCK_PATH.read_text(encoding="utf-8") or "{}")
        pid = int(payload.get("pid") or 0)
    except Exception:
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return str(pid) in output and "No tasks" not in output
    except Exception:
        return False


def acquire_run_lock(max_age_minutes=90, wait_seconds=90):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait_seconds
    while True:
        if RUN_LOCK_PATH.exists():
            age_seconds = time.time() - RUN_LOCK_PATH.stat().st_mtime
            lock_is_active = lock_process_is_active()
            if not lock_is_active:
                RUN_LOCK_PATH.unlink(missing_ok=True)
            elif time.time() < deadline:
                time.sleep(5)
                continue
            else:
                raise RuntimeError(
                    "another update is still running; waited and stopped to protect the database"
                    f" (lock age {int(age_seconds)} seconds, stale limit {max_age_minutes} minutes)"
                )
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            fd = os.open(str(RUN_LOCK_PATH), flags)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "pid": os.getpid(),
                    "started_at": taipei_now().isoformat(timespec="seconds"),
                }, ensure_ascii=False))
            return
        except FileExistsError:
            if time.time() < deadline:
                time.sleep(3)
                continue
            raise RuntimeError("update lock is busy; waited and stopped to protect the database")


def release_run_lock():
    try:
        RUN_LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        logging.warning("Run lock could not be removed: %s", RUN_LOCK_PATH)


def http_get_bytes_via_curl(url):
    with NamedTemporaryFile(delete=False, suffix=".download") as temp_file:
        temp_path = Path(temp_file.name)
    try:
        completed = subprocess.run(
            [
                "curl.exe",
                "-L",
                "--fail",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "20",
                "--max-time",
                "90",
                "-A",
                "Mozilla/5.0 539-data-system/1.0",
                "-o",
                str(temp_path),
                url,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=100,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or "curl download failed.")
        data = temp_path.read_bytes()
        if not data:
            raise RuntimeError("curl download returned empty response.")
        return data
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


def http_get_bytes(url, retries=3, retry_delay=2):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 539-data-system/1.0",
            "Accept": "*/*",
        },
    )
    context = ssl._create_unverified_context()
    errors = []
    for label, downloader in (
        ("powershell", http_get_bytes_via_powershell),
        ("curl", http_get_bytes_via_curl),
    ):
        try:
            logging.info("Trying %s download path first: %s", label, url)
            return downloader(url)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logging.warning("%s download path failed: %s", label, url)

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60, context=context) as response:
                data = response.read()
                if not data:
                    raise RuntimeError("empty response")
                return data
        except Exception as exc:
            errors.append(f"python attempt {attempt}/{retries}: {exc}")
            logging.warning("Python download failed, attempt %s/%s: %s", attempt, retries, url)
            if attempt < retries:
                time.sleep(retry_delay * attempt)

    sandbox_note = ""
    try:
        check = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=codex_sandbox_offline_block_outbound"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if "codex_sandbox_offline_block_outbound" in ((check.stdout or "") + (check.stderr or "")):
            sandbox_note = " | detected Codex sandbox outbound block; run the Windows desktop one-click launcher outside Codex"
    except Exception:
        pass
    raise RuntimeError("download failed: " + " | ".join(errors) + sandbox_note)


def http_get_json(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    raw = http_get_bytes(url)
    return json.loads(raw.decode("utf-8-sig"))


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS draws_539 (
            period INTEGER PRIMARY KEY,
            draw_date TEXT NOT NULL,
            n1 INTEGER NOT NULL,
            n2 INTEGER NOT NULL,
            n3 INTEGER NOT NULL,
            n4 INTEGER NOT NULL,
            n5 INTEGER NOT NULL,
            draw_order TEXT,
            sales_amount INTEGER,
            sales_count INTEGER,
            prize_total INTEGER,
            jackpot_winners INTEGER,
            second_winners INTEGER,
            third_winners INTEGER,
            fourth_winners INTEGER,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_draws_539_date ON draws_539(draw_date)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS update_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            message TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions_539 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            based_on_period INTEGER NOT NULL UNIQUE,
            based_on_date TEXT NOT NULL,
            target_period INTEGER,
            candidates_json TEXT NOT NULL,
            suggested_sets_json TEXT NOT NULL,
            strong_packs_json TEXT,
            unlikely_packs_json TEXT,
            model_weights_json TEXT NOT NULL,
            backtest_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            settled_at TEXT,
            actual_period INTEGER,
            actual_date TEXT,
            actual_numbers_json TEXT,
            top5_hits INTEGER,
            top10_hits INTEGER,
            top15_hits INTEGER,
            set_hits_json TEXT,
            strong_pack_hits_json TEXT,
            unlikely_pack_hits_json TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_539_status ON predictions_539(status)")
    ensure_column(conn, "predictions_539", "strong_packs_json", "TEXT")
    ensure_column(conn, "predictions_539", "strong_pack_hits_json", "TEXT")
    ensure_column(conn, "predictions_539", "unlikely_packs_json", "TEXT")
    ensure_column(conn, "predictions_539", "unlikely_pack_hits_json", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_snapshots_539 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            based_on_period INTEGER NOT NULL,
            based_on_date TEXT NOT NULL,
            target_period INTEGER,
            candidates_json TEXT NOT NULL,
            suggested_sets_json TEXT NOT NULL,
            strong_packs_json TEXT,
            unlikely_packs_json TEXT,
            model_weights_json TEXT NOT NULL,
            backtest_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            snapshot_reason TEXT NOT NULL
        )
        """
    )
    ensure_column(conn, "prediction_snapshots_539", "unlikely_packs_json", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prediction_snapshots_period ON prediction_snapshots_539(based_on_period)")
    conn.commit()


def ensure_column(conn, table_name, column_name, column_type):
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def start_run(conn, run_type):
    cursor = conn.execute(
        "INSERT INTO update_runs (run_type, started_at, status) VALUES (?, ?, ?)",
        (run_type, datetime.now().isoformat(timespec="seconds"), "running"),
    )
    conn.commit()
    return cursor.lastrowid


def finish_run(conn, run_id, status, message=""):
    conn.execute(
        "UPDATE update_runs SET finished_at=?, status=?, message=? WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), status, message[:1000], run_id),
    )
    conn.commit()


def backup_database():
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"539_{stamp}.sqlite"
    shutil.copy2(DB_PATH, backup_path)
    backups = sorted(BACKUP_DIR.glob("539_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_backup in backups[10:]:
        old_backup.unlink()
    logging.info("\u5df2\u5efa\u7acb\u8cc7\u6599\u5eab\u5099\u4efd：%s", backup_path)
    return backup_path


def to_int(value):
    if value is None:
        return None
    value = str(value).strip().replace(",", "")
    if value == "":
        return None
    return int(float(value))


def normalize_date(value):
    value = str(value).strip()
    if "T" in value:
        value = value.split("T", 1)[0].replace("-", "/")
    dt = datetime.strptime(value, "%Y/%m/%d")
    return dt.strftime("%Y-%m-%d")


def validate_draw_row(row):
    nums = [row["n1"], row["n2"], row["n3"], row["n4"], row["n5"]]
    if len(set(nums)) != 5:
        raise ValueError(f"\u671f\u5225 {row['period']} \u865f\u78bc\u91cd\u8907：{nums}")
    if any(n < 1 or n > 39 for n in nums):
        raise ValueError(f"\u671f\u5225 {row['period']} \u865f\u78bc\u8d85\u51fa 1-39：{nums}")
    if row["period"] is None:
        raise ValueError("\u671f\u5225\u4e0d\u53ef\u70ba\u7a7a")


def upsert_draw(conn, row):
    validate_draw_row(row)
    conn.execute(
        """
        INSERT INTO draws_539 (
            period, draw_date, n1, n2, n3, n4, n5, draw_order,
            sales_amount, sales_count, prize_total,
            jackpot_winners, second_winners, third_winners, fourth_winners,
            source, fetched_at
        )
        VALUES (
            :period, :draw_date, :n1, :n2, :n3, :n4, :n5, :draw_order,
            :sales_amount, :sales_count, :prize_total,
            :jackpot_winners, :second_winners, :third_winners, :fourth_winners,
            :source, :fetched_at
        )
        ON CONFLICT(period) DO UPDATE SET
            draw_date=excluded.draw_date,
            n1=excluded.n1,
            n2=excluded.n2,
            n3=excluded.n3,
            n4=excluded.n4,
            n5=excluded.n5,
            draw_order=COALESCE(excluded.draw_order, draws_539.draw_order),
            sales_amount=COALESCE(excluded.sales_amount, draws_539.sales_amount),
            sales_count=COALESCE(excluded.sales_count, draws_539.sales_count),
            prize_total=COALESCE(excluded.prize_total, draws_539.prize_total),
            jackpot_winners=COALESCE(excluded.jackpot_winners, draws_539.jackpot_winners),
            second_winners=COALESCE(excluded.second_winners, draws_539.second_winners),
            third_winners=COALESCE(excluded.third_winners, draws_539.third_winners),
            fourth_winners=COALESCE(excluded.fourth_winners, draws_539.fourth_winners),
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        row,
    )


def fetch_year_zip_url(gregorian_year):
    payload = http_get_json(DOWNLOAD_API, {"year": gregorian_year})
    if payload.get("rtCode") != 0 or not payload.get("content"):
        raise RuntimeError(f"\u5e74\u5ea6 {gregorian_year} \u4e0b\u8f09 API \u56de\u50b3\u7570\u5e38: {payload}")
    return payload["content"]["path"]


def import_year(conn, roc_year):
    gregorian_year = roc_year + 1911
    zip_url = fetch_year_zip_url(gregorian_year)
    zip_bytes = http_get_bytes(zip_url)
    imported = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [
            name
            for name in zf.namelist()
            if name.endswith(".csv") and (GAME_NAME in name or "539" in name)
        ]
        if not names:
            raise RuntimeError(f"\u5e74\u5ea6 {gregorian_year} \u58d3\u7e2e\u6a94\u627e\u4e0d\u5230 {GAME_NAME} CSV")

        with zf.open(names[0]) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            fetched_at = datetime.now().isoformat(timespec="seconds")
            for item in reader:
                nums = [to_int(item.get(f"\u734e\u865f{i}")) for i in range(1, 6)]
                if any(n is None for n in nums):
                    continue
                row = {
                    "period": to_int(item.get("\u671f\u5225")),
                    "draw_date": normalize_date(item.get("\u958b\u734e\u65e5\u671f")),
                    "n1": nums[0],
                    "n2": nums[1],
                    "n3": nums[2],
                    "n4": nums[3],
                    "n5": nums[4],
                    "draw_order": None,
                    "sales_amount": to_int(item.get("\u92b7\u552e\u7e3d\u984d")),
                    "sales_count": to_int(item.get("\u92b7\u552e\u6ce8\u6578")),
                    "prize_total": to_int(item.get("\u7e3d\u734e\u91d1")),
                    "jackpot_winners": None,
                    "second_winners": None,
                    "third_winners": None,
                    "fourth_winners": None,
                    "source": f"taiwanlottery_result_download_{gregorian_year}",
                    "fetched_at": fetched_at,
                }
                upsert_draw(conn, row)
                imported += 1

    conn.commit()
    return imported


def import_all_years(conn, start_roc_year=START_ROC_YEAR, end_roc_year=None):
    end_roc_year = end_roc_year or roc_year_now()
    total = 0
    for roc_year in range(start_roc_year, end_roc_year + 1):
        try:
            count = import_year(conn, roc_year)
            total += count
            logging.info("\u5df2\u532f\u5165\u6c11\u570b %s \u5e74：%s \u7b46", roc_year, count)
            time.sleep(0.2)
        except Exception as exc:
            logging.error("\u6c11\u570b %s \u5e74\u532f\u5165\u5931\u6557：%s", roc_year, exc)
    return total


def row_from_api_result(result, source):
    nums = result["drawNumberSize"][:5]
    row = {
        "period": to_int(result["period"]),
        "draw_date": normalize_date(result["lotteryDate"]),
        "n1": nums[0],
        "n2": nums[1],
        "n3": nums[2],
        "n4": nums[3],
        "n5": nums[4],
        "draw_order": ",".join(str(n).zfill(2) for n in result.get("drawNumberAppear", [])[:5]),
        "sales_amount": to_int(result.get("sellAmount")),
        "sales_count": None,
        "prize_total": to_int(result.get("totalAmount")),
        "jackpot_winners": to_int((result.get("d539JackpotAssign") or {}).get("winnerCount")),
        "second_winners": to_int((result.get("d539SecondAssign") or {}).get("winnerCount")),
        "third_winners": to_int((result.get("d539ThirdAssign") or {}).get("winnerCount")),
        "fourth_winners": to_int((result.get("d539FourthAssign") or {}).get("winnerCount")),
        "source": source,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    return row


def update_latest(conn):
    payload = http_get_json(LATEST_API)
    content = payload.get("content") or {}
    latest = content.get("daily539Result")
    if not latest:
        raise RuntimeError(f"\u627e\u4e0d\u5230 daily539Result: {payload}")

    row = row_from_api_result(latest, "taiwanlottery_latest_result")
    upsert_draw(conn, row)
    conn.commit()
    logging.info(
        "\u5df2\u66f4\u65b0\u6700\u65b0\u4e00\u671f："
        f"{row['period']} {row['draw_date']} "
        f"{row['n1']:02d} {row['n2']:02d} {row['n3']:02d} {row['n4']:02d} {row['n5']:02d}"
    )
    return row


def parse_public_fallback_latest(text):
    pattern = re.compile(
        r"<td[^>]*>\s*(20\d{2})\s*<br\s*/?>\s*(\d{2})/(\d{2})\s*<br\s*/?>\s*\([^<]*\)\s*</td>\s*"
        r"<td[^>]*>(.*?)</td>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        year, month, day, numbers_html = match.groups()
        numbers = [int(value) for value in re.findall(r"\d{2}", numbers_html)[:5]]
        if len(numbers) != 5 or len(set(numbers)) != 5:
            continue
        if any(number < 1 or number > 39 for number in numbers):
            continue
        draw_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        return {
            "draw_date": draw_date,
            "draw_order": ",".join(f"{number:02d}" for number in numbers),
            "numbers": sorted(numbers),
        }
    return None


def infer_period_for_draw_date(conn, draw_date):
    existing = conn.execute(
        "SELECT period FROM draws_539 WHERE draw_date=? ORDER BY period DESC LIMIT 1",
        (draw_date,),
    ).fetchone()
    if existing:
        return int(existing[0])

    target = datetime.strptime(draw_date, "%Y-%m-%d").date()
    previous = conn.execute(
        "SELECT period, draw_date FROM draws_539 WHERE draw_date < ? ORDER BY draw_date DESC, period DESC LIMIT 1",
        (draw_date,),
    ).fetchone()
    if not previous:
        raise RuntimeError(f"cannot infer fallback period for {draw_date}")

    period = int(previous[0])
    current = datetime.strptime(previous[1], "%Y-%m-%d").date()
    while current < target:
        current += timedelta(days=1)
        if current.weekday() != 6:
            period += 1
    return period


def import_public_fallback_latest(conn):
    current = stats(conn)
    freshness = data_freshness(current["max_date"]) if current["max_date"] else None
    if freshness and freshness["status"] == "fresh":
        return 0

    text = http_get_bytes(PUBLIC_FALLBACK_LATEST_URL, retries=2, retry_delay=1).decode("utf-8", "replace")
    parsed = parse_public_fallback_latest(text)
    if not parsed:
        raise RuntimeError("public fallback latest result could not be parsed")

    expected = freshness["expected_latest_date"] if freshness else expected_latest_draw_date()
    if parsed["draw_date"] < expected:
        logging.warning(
            "Public fallback latest result is also behind expected date: latest=%s expected=%s",
            parsed["draw_date"],
            expected,
        )
        return 0

    numbers = parsed["numbers"]
    row = {
        "period": infer_period_for_draw_date(conn, parsed["draw_date"]),
        "draw_date": parsed["draw_date"],
        "n1": numbers[0],
        "n2": numbers[1],
        "n3": numbers[2],
        "n4": numbers[3],
        "n5": numbers[4],
        "draw_order": parsed["draw_order"],
        "sales_amount": None,
        "sales_count": None,
        "prize_total": None,
        "jackpot_winners": None,
        "second_winners": None,
        "third_winners": None,
        "fourth_winners": None,
        "source": "public_fallback_pilio_latest",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    before = current["max_date"]
    upsert_draw(conn, row)
    conn.commit()
    logging.info(
        "Public fallback latest imported: %s %s %02d %02d %02d %02d %02d (previous latest=%s)",
        row["period"],
        row["draw_date"],
        row["n1"],
        row["n2"],
        row["n3"],
        row["n4"],
        row["n5"],
        before,
    )
    return 1


def month_strings(count=2):
    today = taipei_now()
    year = today.year
    month = today.month
    months = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return months


def import_month(conn, month):
    payload = http_get_json(
        HISTORY_API,
        {
            "month": month,
            "endMonth": month,
            "pageNum": 1,
            "pageSize": 100,
        },
    )
    content = payload.get("content") or {}
    results = content.get("daily539Res") or []
    for result in results:
        row = row_from_api_result(result, f"taiwanlottery_daily539_result_{month}")
        upsert_draw(conn, row)
    conn.commit()
    logging.info("\u5df2\u88dc\u9f4a %s \u6b77\u53f2\u67e5\u8a62 API：%s \u7b46", month, len(results))
    return len(results)


def import_recent_months(conn, count=2):
    total = 0
    for month in month_strings(count):
        total += import_month(conn, month)
    return total


def export_csv(conn):
    rows = conn.execute(
        """
        SELECT period, draw_date, n1, n2, n3, n4, n5, draw_order,
               sales_amount, sales_count, prize_total,
               jackpot_winners, second_winners, third_winners, fourth_winners,
               source, fetched_at
        FROM draws_539
        ORDER BY period
        """
    ).fetchall()

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow([description[0] for description in conn.execute("SELECT * FROM draws_539 LIMIT 0").description])
        for row in rows:
            writer.writerow(row)
    return len(rows)


def stats(conn):
    row = conn.execute(
        """
        SELECT COUNT(*), MIN(period), MAX(period), MIN(draw_date), MAX(draw_date)
        FROM draws_539
        """
    ).fetchone()
    return {
        "count": row[0],
        "min_period": row[1],
        "max_period": row[2],
        "min_date": row[3],
        "max_date": row[4],
    }


def integrity_report(conn):
    rows = conn.execute(
        "SELECT period, draw_date, n1, n2, n3, n4, n5 FROM draws_539 ORDER BY period"
    ).fetchall()
    invalid = []
    duplicates = []
    for row in rows:
        nums = list(row[2:7])
        if len(set(nums)) != 5 or any(n < 1 or n > 39 for n in nums):
            invalid.append(row[0])
    periods = [row[0] for row in rows]
    seen = set()
    for period in periods:
        if period in seen:
            duplicates.append(period)
        seen.add(period)
    return {
        "rows": len(rows),
        "invalid_periods": invalid,
        "duplicate_periods": duplicates,
        "latest_period": periods[-1] if periods else None,
        "latest_date": rows[-1][1] if rows else None,
    }


def unlikely_packs_from_analysis(analysis):
    industrial = analysis.get("industrial_engine") or {}
    unlikely = industrial.get("unlikely_number_analysis") or {}
    return unlikely.get("avoid_packs") or {}


def settle_unlikely_packs(unlikely_packs, actual_numbers):
    actual_set = {int(number) for number in actual_numbers}
    results = {}
    for key, pack in (unlikely_packs or {}).items():
        numbers = [int(number) for number in pack.get("numbers", []) if number]
        accidental_hits = sorted(set(numbers) & actual_set)
        results[key] = {
            "name": pack.get("name", key),
            "numbers": numbers,
            "target": "不中",
            "hit_goal": 0,
            "accidental_hits": len(accidental_hits),
            "hit_numbers": accidental_hits,
            "avoided_numbers": sorted(set(numbers) - actual_set),
            "passed": len(accidental_hits) == 0,
            "confidence_index": pack.get("confidence_index"),
            "avg_avoid_score": pack.get("avg_avoid_score"),
            "min_avoid_score": pack.get("min_avoid_score"),
        }
    return results


def unlikely_packs_from_saved_candidates(candidates):
    cleaned = []
    for index, item in enumerate(candidates):
        try:
            number = int(item.get("number"))
            score = float(item.get("score", 0.0) or 0.0)
            confidence = float(item.get("confidence_index", 50.0) or 50.0)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 39:
            cleaned.append({
                "number": number,
                "score": max(0.0, min(1.0, score)),
                "confidence_index": confidence,
                "rank": int(item.get("rank") or index + 1),
            })
    cleaned.sort(key=lambda row: (row["score"], row["confidence_index"], -row["rank"], -row["number"]))

    def make_pack(key, name, size):
        selected = cleaned[:size]
        numbers = sorted(row["number"] for row in selected)
        avoid_scores = [1.0 - row["score"] for row in selected]
        avg_avoid = sum(avoid_scores) / len(avoid_scores) if avoid_scores else 0.0
        min_avoid = min(avoid_scores) if avoid_scores else 0.0
        return key, {
            "name": name,
            "numbers": numbers,
            "target": "不中",
            "hit_goal": 0,
            "confidence_index": round(50 + avg_avoid * 49, 1),
            "avg_avoid_score": round(avg_avoid, 4),
            "min_avoid_score": round(min_avoid, 4),
            "source": "historical_backfill_from_saved_candidates",
            "rule": "使用當時已保存候選排序的最低分號碼回填，避免使用未來資料。",
        }

    return dict([
        make_pack("five_miss", "5不中暫避", 5),
        make_pack("ten_miss", "10不中暫避", 10),
        make_pack("fifteen_miss", "15不中暫避", 15),
    ])


def backfill_missing_unlikely_reviews(conn, limit=60):
    rows = conn.execute(
        """
        SELECT id, candidates_json, actual_numbers_json, unlikely_packs_json, unlikely_pack_hits_json
        FROM predictions_539
        WHERE status='settled'
          AND (
            unlikely_packs_json IS NULL OR unlikely_packs_json='' OR unlikely_packs_json='{}'
            OR unlikely_pack_hits_json IS NULL OR unlikely_pack_hits_json='' OR unlikely_pack_hits_json='{}'
          )
        ORDER BY actual_period DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    repaired = 0
    for row in rows:
        try:
            candidates = json.loads(row[1] or "[]")
            actual_numbers = json.loads(row[2] or "[]")
            packs = json.loads(row[3] or "{}")
        except json.JSONDecodeError:
            continue
        if not packs:
            packs = unlikely_packs_from_saved_candidates(candidates)
        hits = settle_unlikely_packs(packs, actual_numbers)
        conn.execute(
            """
            UPDATE predictions_539
            SET unlikely_packs_json=?, unlikely_pack_hits_json=?
            WHERE id=?
            """,
            (
                json.dumps(packs, ensure_ascii=False),
                json.dumps(hits, ensure_ascii=False),
                row[0],
            ),
        )
        repaired += 1
    conn.commit()
    return {"repaired": repaired, "checked": len(rows)}


def settle_predictions(conn):
    pending = conn.execute(
        """
        SELECT id, based_on_period, candidates_json, suggested_sets_json, strong_packs_json, unlikely_packs_json
        FROM predictions_539
        WHERE status = 'pending'
        ORDER BY based_on_period
        """
    ).fetchall()
    settled = 0
    for prediction in pending:
        actual = conn.execute(
            """
            SELECT period, draw_date, n1, n2, n3, n4, n5
            FROM draws_539
            WHERE period > ?
            ORDER BY period
            LIMIT 1
            """,
            (prediction[1],),
        ).fetchone()
        if not actual:
            continue
        actual_numbers = set(actual[2:7])
        candidates = json.loads(prediction[2])
        suggested_sets = json.loads(prediction[3])
        strong_packs = json.loads(prediction[4] or "{}")
        unlikely_packs = json.loads(prediction[5] or "{}")
        ranked_numbers = [item["number"] for item in candidates]
        set_hits = [
            {
                "set_index": idx + 1,
                "numbers": combo,
                "hits": len(set(combo) & actual_numbers),
            }
            for idx, combo in enumerate(suggested_sets)
        ]
        strong_pack_hits = {}
        for key, pack in strong_packs.items():
            numbers = pack.get("numbers", [])
            hits = len(set(numbers) & actual_numbers)
            strong_pack_hits[key] = {
                "name": pack.get("name", key),
                "hit_goal": pack.get("hit_goal"),
                "numbers": numbers,
                "hits": hits,
                "passed": hits >= int(pack.get("hit_goal") or 0),
            }
        unlikely_pack_hits = settle_unlikely_packs(unlikely_packs, actual_numbers)
        conn.execute(
            """
            UPDATE predictions_539
            SET settled_at=?, actual_period=?, actual_date=?, actual_numbers_json=?,
                top5_hits=?, top10_hits=?, top15_hits=?, set_hits_json=?,
                strong_pack_hits_json=?, unlikely_pack_hits_json=?, status='settled'
            WHERE id=?
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                actual[0],
                actual[1],
                json.dumps(sorted(actual_numbers), ensure_ascii=False),
                len(set(ranked_numbers[:5]) & actual_numbers),
                len(set(ranked_numbers[:10]) & actual_numbers),
                len(set(ranked_numbers[:15]) & actual_numbers),
                json.dumps(set_hits, ensure_ascii=False),
                json.dumps(strong_pack_hits, ensure_ascii=False),
                json.dumps(unlikely_pack_hits, ensure_ascii=False),
                prediction[0],
            ),
        )
        settled += 1
    conn.commit()
    return settled


def build_repair_analysis_for_period(conn, target_period):
    target = conn.execute(
        """
        SELECT period, draw_date
        FROM draws_539
        WHERE period=?
        """,
        (target_period,),
    ).fetchone()
    if not target:
        return None
    based = conn.execute(
        """
        SELECT period, draw_date
        FROM draws_539
        WHERE period < ?
        ORDER BY period DESC
        LIMIT 1
        """,
        (target_period,),
    ).fetchone()
    if not based:
        return None

    temp = NamedTemporaryFile(prefix="tw539_repair_", suffix=".sqlite", delete=False)
    temp_path = Path(temp.name)
    temp.close()
    try:
        with sqlite3.connect(temp_path) as repair_conn:
            draw_schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='draws_539'"
            ).fetchone()[0]
            prediction_schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='predictions_539'"
            ).fetchone()[0]
            repair_conn.execute(draw_schema)
            repair_conn.execute(prediction_schema)

            draw_columns = [row[1] for row in conn.execute("PRAGMA table_info(draws_539)").fetchall()]
            prediction_columns = [row[1] for row in conn.execute("PRAGMA table_info(predictions_539)").fetchall()]
            draw_placeholder = ",".join("?" for _ in draw_columns)
            prediction_placeholder = ",".join("?" for _ in prediction_columns)

            draw_rows = conn.execute(
                f"SELECT {','.join(draw_columns)} FROM draws_539 WHERE period <= ? ORDER BY period",
                (based[0],),
            ).fetchall()
            repair_conn.executemany(
                f"INSERT INTO draws_539 ({','.join(draw_columns)}) VALUES ({draw_placeholder})",
                draw_rows,
            )
            prediction_rows = conn.execute(
                f"""
                SELECT {','.join(prediction_columns)}
                FROM predictions_539
                WHERE status='settled' AND target_period < ?
                ORDER BY target_period
                """,
                (target_period,),
            ).fetchall()
            if prediction_rows:
                repair_conn.executemany(
                    f"INSERT INTO predictions_539 ({','.join(prediction_columns)}) VALUES ({prediction_placeholder})",
                    prediction_rows,
                )
            repair_conn.commit()

        repair_analysis = analyze(temp_path)
        repair_analysis["auto_repair"] = {
            "status": "reconstructed_missing_prediction",
            "target_period": target_period,
            "target_draw_date": target[1],
            "based_on_period": based[0],
            "based_on_date": based[1],
            "repair_generated_at": datetime.now().isoformat(timespec="seconds"),
            "rule": "rebuild_with_only_draws_available_before_target_period",
        }
        return repair_analysis
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def fetch_repair_draws_until(conn, based_period):
    rows = conn.execute(
        """
        SELECT period, draw_date, n1, n2, n3, n4, n5
        FROM draws_539
        WHERE period <= ?
        ORDER BY period
        """,
        (based_period,),
    ).fetchall()
    return [
        {
            "period": row[0],
            "draw_date": row[1],
            "numbers": [row[2], row[3], row[4], row[5], row[6]],
        }
        for row in rows
    ]


def build_lightweight_repair_packs(candidates):
    specs = {
        "strong_single": ("最強單支", 1, 1),
        "two_hit_one": ("最強2中1", 1, 2),
        "three_hit_one": ("最強3中1", 1, 3),
        "five_hit_two": ("最強5中2", 2, 5),
        "nine_hit_three": ("最強9中3", 3, 9),
    }
    score_map = {item["number"]: float(item.get("score", 0.0) or 0.0) for item in candidates}
    packs = {}
    for key, (name, goal, size) in specs.items():
        numbers = sorted(item["number"] for item in candidates[:size])
        avg_score = sum(score_map.get(number, 0.0) for number in numbers) / len(numbers) if numbers else 0.0
        packs[key] = {
            "name": name,
            "hit_goal": goal,
            "numbers": numbers,
            "score_sum": round(sum(score_map.get(number, 0.0) for number in numbers), 4),
            "avg_score": round(avg_score, 4),
            "status": "auto_repaired_from_pre_draw_data",
            "official_release": False,
            "release_note": "缺漏期自動補修，僅使用該期開獎前資料重建，供結算追蹤使用",
        }
    return packs


def build_lightweight_repair_analysis_for_period(conn, target_period):
    target = conn.execute(
        """
        SELECT period, draw_date
        FROM draws_539
        WHERE period=?
        """,
        (target_period,),
    ).fetchone()
    if not target:
        return None
    based = conn.execute(
        """
        SELECT period, draw_date
        FROM draws_539
        WHERE period < ?
        ORDER BY period DESC
        LIMIT 1
        """,
        (target_period,),
    ).fetchone()
    if not based:
        return None
    draws = fetch_repair_draws_until(conn, based[0])
    if len(draws) < 100:
        return None
    candidates, weights = score_numbers(draws, None, include_dependency=False)
    analysis = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "latest_draw": draws[-1],
        "candidates": candidates,
        "official_candidates": candidates,
        "suggested_sets": build_sets(candidates) if len(candidates) >= 18 else [],
        "strong_prediction_packs": build_lightweight_repair_packs(candidates),
        "model_weights": weights,
        "backtest": {
            "rounds": 0,
            "note": "缺漏期快速補修紀錄，不跑完整大型回測，避免一鍵更新卡死",
        },
        "auto_repair": {
            "status": "reconstructed_missing_prediction",
            "target_period": target_period,
            "target_draw_date": target[1],
            "based_on_period": based[0],
            "based_on_date": based[1],
            "repair_generated_at": datetime.now().isoformat(timespec="seconds"),
            "rule": "rebuild_with_only_draws_available_before_target_period",
            "engine": "lightweight_pre_draw_repair",
        },
    }
    return analysis


def repair_missing_prediction_records(conn, lookback=12):
    latest = conn.execute(
        """
        SELECT period, draw_date
        FROM draws_539
        ORDER BY period DESC
        LIMIT 1
        """
    ).fetchone()
    if not latest:
        return {"repaired": 0, "targets": []}
    missing_targets = conn.execute(
        """
        SELECT d.period, d.draw_date
        FROM draws_539 d
        LEFT JOIN predictions_539 p ON p.target_period=d.period
        WHERE d.period BETWEEN ? AND ?
          AND p.target_period IS NULL
        ORDER BY d.period
        """,
        (latest[0] - lookback, latest[0]),
    ).fetchall()
    repaired = []
    for target_period, target_date in missing_targets:
        analysis = build_lightweight_repair_analysis_for_period(conn, target_period)
        if not analysis:
            continue
        based = analysis["latest_draw"]
        candidates_json = json.dumps(analysis.get("official_candidates", analysis["candidates"]), ensure_ascii=False)
        suggested_sets_json = json.dumps(analysis["suggested_sets"], ensure_ascii=False)
        strong_packs_json = json.dumps(analysis["strong_prediction_packs"], ensure_ascii=False)
        unlikely_packs_json = json.dumps(unlikely_packs_from_analysis(analysis), ensure_ascii=False)
        model_weights_json = json.dumps(analysis["model_weights"], ensure_ascii=False)
        backtest_payload = dict(analysis["backtest"])
        backtest_payload["auto_repair"] = analysis["auto_repair"]
        backtest_json = json.dumps(backtest_payload, ensure_ascii=False)
        created_at = datetime.now().isoformat(timespec="seconds")
        try:
            conn.execute(
                """
                INSERT INTO predictions_539 (
                    based_on_period, based_on_date, target_period,
                    candidates_json, suggested_sets_json, strong_packs_json, unlikely_packs_json,
                    model_weights_json, backtest_json, created_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    based["period"],
                    based["draw_date"],
                    target_period,
                    candidates_json,
                    suggested_sets_json,
                    strong_packs_json,
                    unlikely_packs_json,
                    model_weights_json,
                    backtest_json,
                    created_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO prediction_snapshots_539 (
                    based_on_period, based_on_date, target_period,
                    candidates_json, suggested_sets_json, strong_packs_json, unlikely_packs_json,
                    model_weights_json, backtest_json, created_at, snapshot_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    based["period"],
                    based["draw_date"],
                    target_period,
                    candidates_json,
                    suggested_sets_json,
                    strong_packs_json,
                    unlikely_packs_json,
                    model_weights_json,
                    backtest_json,
                    created_at,
                    "auto_repaired_missing_prediction_record",
                ),
            )
            repaired.append({
                "target_period": target_period,
                "target_date": target_date,
                "based_on_period": based["period"],
                "based_on_date": based["draw_date"],
            })
        except sqlite3.IntegrityError:
            logging.warning("Missing prediction repair skipped because based period already exists: %s", based["period"])
    conn.commit()
    return {"repaired": len(repaired), "targets": repaired}


def store_prediction_snapshot(conn, analysis, reason):
    latest = analysis["latest_draw"]
    conn.execute(
        """
        INSERT INTO prediction_snapshots_539 (
            based_on_period, based_on_date, target_period,
            candidates_json, suggested_sets_json, strong_packs_json, unlikely_packs_json,
            model_weights_json, backtest_json, created_at, snapshot_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            latest["period"],
            latest["draw_date"],
            latest["period"] + 1,
            json.dumps(analysis.get("official_candidates", analysis["candidates"]), ensure_ascii=False),
            json.dumps(analysis["suggested_sets"], ensure_ascii=False),
            json.dumps(analysis["strong_prediction_packs"], ensure_ascii=False),
            json.dumps(unlikely_packs_from_analysis(analysis), ensure_ascii=False),
            json.dumps(analysis["model_weights"], ensure_ascii=False),
            json.dumps(analysis["backtest"], ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
            reason,
        ),
    )


def archive_existing_prediction(conn, prediction_id, reason):
    row = conn.execute(
        """
        SELECT based_on_period, based_on_date, target_period,
               candidates_json, suggested_sets_json, strong_packs_json, unlikely_packs_json,
               model_weights_json, backtest_json
        FROM predictions_539
        WHERE id=?
        """,
        (prediction_id,),
    ).fetchone()
    if not row:
        return
    conn.execute(
        """
        INSERT INTO prediction_snapshots_539 (
            based_on_period, based_on_date, target_period,
            candidates_json, suggested_sets_json, strong_packs_json, unlikely_packs_json,
            model_weights_json, backtest_json, created_at, snapshot_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*row, datetime.now().isoformat(timespec="seconds"), reason),
    )


def current_prediction_numbers(analysis, limit=15):
    return [
        item["number"] for item in analysis.get("official_candidates", analysis.get("candidates", []))[:limit]
        if isinstance(item, dict) and "number" in item
    ]


def latest_settled_prediction_numbers(conn, limit=15):
    row = conn.execute(
        """
        SELECT candidates_json, strong_packs_json, based_on_period, actual_period
        FROM predictions_539
        WHERE status='settled'
        ORDER BY actual_period DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    candidates = json.loads(row[0] or "[]")
    packs = json.loads(row[1] or "{}")
    return {
        "top_numbers": [
            item["number"] for item in candidates[:limit]
            if isinstance(item, dict) and "number" in item
        ],
        "pack_numbers": {
            key: list(value.get("numbers") or [])
            for key, value in packs.items()
            if isinstance(value, dict)
        },
        "based_on_period": row[2],
        "actual_period": row[3],
    }


def previous_copy_block_reason(conn, analysis):
    previous = latest_settled_prediction_numbers(conn)
    if not previous:
        return None
    current_top = current_prediction_numbers(analysis, limit=15)
    previous_top = previous["top_numbers"]
    if current_top and previous_top and current_top == previous_top:
        return "blocked_previous_top15_exact_copy"
    current_packs = analysis.get("strong_prediction_packs") or {}
    copied_packs = []
    for key, pack in current_packs.items():
        if not isinstance(pack, dict):
            continue
        current_numbers = list(pack.get("numbers") or [])
        previous_numbers = previous["pack_numbers"].get(key)
        if current_numbers and previous_numbers and current_numbers == previous_numbers:
            copied_packs.append(key)
    if copied_packs and len(copied_packs) == len(current_packs):
        return "blocked_previous_strong_packs_exact_copy"
    return None


def store_prediction(conn, analysis):
    latest = analysis["latest_draw"]
    new_candidates_json = json.dumps(analysis.get("official_candidates", analysis["candidates"]), ensure_ascii=False)
    new_sets_json = json.dumps(analysis["suggested_sets"], ensure_ascii=False)
    new_packs_json = json.dumps(analysis["strong_prediction_packs"], ensure_ascii=False)
    new_unlikely_packs_json = json.dumps(unlikely_packs_from_analysis(analysis), ensure_ascii=False)
    new_weights_json = json.dumps(analysis["model_weights"], ensure_ascii=False)
    new_backtest_json = json.dumps(analysis["backtest"], ensure_ascii=False)
    exists = conn.execute(
        """
        SELECT id, status, candidates_json, suggested_sets_json, strong_packs_json,
               unlikely_packs_json, model_weights_json, backtest_json
        FROM predictions_539
        WHERE based_on_period=?
        """,
        (latest["period"],),
    ).fetchone()
    if exists:
        previous_guard = analysis.get("industrial_engine", {}).get("previous_prediction_guard", {})
        existing_top15 = {
            item["number"] for item in json.loads(exists[2] or "[]")[:15]
        }
        previous_top15 = set(previous_guard.get("previous_top15", []))
        requires_guard_correction = bool(existing_top15 & previous_top15)
        if exists[1] == "pending" and previous_guard and requires_guard_correction and not previous_guard.get("current_top15_overlap"):
            archive_existing_prediction(conn, exists[0], "official_prediction_before_previous_prediction_guard_correction")
            conn.execute(
                """
                UPDATE predictions_539
                SET candidates_json=?, suggested_sets_json=?, strong_packs_json=?, unlikely_packs_json=?,
                    model_weights_json=?, backtest_json=?, created_at=?
                WHERE id=?
                """,
                (
                    new_candidates_json,
                    new_sets_json,
                    new_packs_json,
                    new_unlikely_packs_json,
                    new_weights_json,
                    new_backtest_json,
                    datetime.now().isoformat(timespec="seconds"),
                    exists[0],
                ),
            )
            store_prediction_snapshot(conn, analysis, "official_prediction_corrected_by_previous_prediction_guard")
            conn.commit()
            return "corrected_pending"
        changed = (
            exists[2] != new_candidates_json
            or exists[3] != new_sets_json
            or (exists[4] or "") != new_packs_json
            or (exists[5] or "") != new_unlikely_packs_json
            or exists[6] != new_weights_json
            or exists[7] != new_backtest_json
        )
        if exists[1] == "pending" and changed:
            archive_existing_prediction(conn, exists[0], "official_prediction_before_recalculation_update")
            conn.execute(
                """
                UPDATE predictions_539
                SET candidates_json=?, suggested_sets_json=?, strong_packs_json=?, unlikely_packs_json=?,
                    model_weights_json=?, backtest_json=?, created_at=?
                WHERE id=?
                """,
                (
                    new_candidates_json,
                    new_sets_json,
                    new_packs_json,
                    new_unlikely_packs_json,
                    new_weights_json,
                    new_backtest_json,
                    datetime.now().isoformat(timespec="seconds"),
                    exists[0],
                ),
            )
            store_prediction_snapshot(conn, analysis, "official_prediction_recalculated_and_updated")
            conn.commit()
            return "updated_pending"
        if exists[1] == "pending":
            conn.execute(
                """
                UPDATE predictions_539
                SET candidates_json=?, suggested_sets_json=?, strong_packs_json=?, unlikely_packs_json=?,
                    model_weights_json=?, backtest_json=?, created_at=?
                WHERE id=?
                """,
                (
                    new_candidates_json,
                    new_sets_json,
                    new_packs_json,
                    new_unlikely_packs_json,
                    new_weights_json,
                    new_backtest_json,
                    datetime.now().isoformat(timespec="seconds"),
                    exists[0],
                ),
            )
            store_prediction_snapshot(conn, analysis, "official_prediction_recalculated_same_result_refreshed")
            conn.commit()
            return "recalculated_same_as_official_refreshed"
        store_prediction_snapshot(conn, analysis, "rerun_preserved_settled_prediction")
        conn.commit()
        return "preserved_settled"
    copy_reason = previous_copy_block_reason(conn, analysis)
    if copy_reason:
        store_prediction_snapshot(conn, analysis, copy_reason)
        conn.commit()
        return copy_reason
    conn.execute(
        """
        INSERT INTO predictions_539 (
            based_on_period, based_on_date, target_period,
            candidates_json, suggested_sets_json, strong_packs_json, unlikely_packs_json, model_weights_json, backtest_json,
            created_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            latest["period"],
            latest["draw_date"],
            latest["period"] + 1,
            new_candidates_json,
            new_sets_json,
            new_packs_json,
            new_unlikely_packs_json,
            new_weights_json,
            new_backtest_json,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    store_prediction_snapshot(conn, analysis, "official_prediction_created")
    conn.commit()
    return "inserted"


def prediction_performance(conn):
    rows = conn.execute(
        """
        SELECT top5_hits, top10_hits, top15_hits, set_hits_json, strong_pack_hits_json, unlikely_pack_hits_json
        FROM predictions_539
        WHERE status='settled'
        """
    ).fetchall()
    if not rows:
        return {"settled": 0}
    set_hit_totals = []
    kpi_records = []
    pack_stats = defaultdict(lambda: {"rounds": 0, "passed": 0, "hits": 0})
    unlikely_stats = defaultdict(lambda: {"rounds": 0, "passed": 0, "accidental_hits": 0})
    for row in rows:
        set_hits = json.loads(row[3] or "[]")
        set_hit_totals.extend(item["hits"] for item in set_hits)
        strong_pack_hits = json.loads(row[4] or "{}")
        unlikely_pack_hits = json.loads(row[5] or "{}")
        kpi_records.append({"top15_hits": row[2], "strong_pack_hits": strong_pack_hits})
        for key, item in strong_pack_hits.items():
            pack_stats[key]["rounds"] += 1
            pack_stats[key]["passed"] += 1 if item.get("passed") else 0
            pack_stats[key]["hits"] += item.get("hits", 0)
        for key, item in unlikely_pack_hits.items():
            unlikely_stats[key]["rounds"] += 1
            unlikely_stats[key]["passed"] += 1 if item.get("passed") else 0
            unlikely_stats[key]["accidental_hits"] += int(item.get("accidental_hits") or 0)
    count = len(rows)
    return {
        "settled": count,
        "top5_avg_hits": round(sum(row[0] for row in rows) / count, 3),
        "top10_avg_hits": round(sum(row[1] for row in rows) / count, 3),
        "top15_avg_hits": round(sum(row[2] for row in rows) / count, 3),
        "set_avg_hits": round(sum(set_hit_totals) / len(set_hit_totals), 3) if set_hit_totals else 0,
        "strong_pack_stats": {
            key: {
                "rounds": value["rounds"],
                "pass_rate": round(value["passed"] / value["rounds"], 3) if value["rounds"] else 0,
                "avg_hits": round(value["hits"] / value["rounds"], 3) if value["rounds"] else 0,
            }
            for key, value in pack_stats.items()
        },
        "unlikely_pack_stats": {
            key: {
                "rounds": value["rounds"],
                "pass_rate": round(value["passed"] / value["rounds"], 3) if value["rounds"] else 0,
                "avg_accidental_hits": round(value["accidental_hits"] / value["rounds"], 3) if value["rounds"] else 0,
            }
            for key, value in unlikely_stats.items()
        },
        "research_kpi": evaluate_research_kpis(kpi_records),
    }


def main():
    setup_logging()
    acquire_run_lock()
    try:
        run_main()
    finally:
        release_run_lock()


def run_main():
    parser = argparse.ArgumentParser(description="\u4eca\u5f69539\u6b77\u53f2\u8207\u6700\u65b0\u958b\u734e\u8cc7\u6599\u66f4\u65b0")
    parser.add_argument("--all", action="store_true", help="\u532f\u5165\u6c11\u570b96\u5e74\u81f3\u4eca\u5e74\u7684\u5b98\u65b9\u5e74\u5ea6\u6a94，\u4e26\u66f4\u65b0\u6700\u65b0\u4e00\u671f")
    parser.add_argument("--latest", action="store_true", help="\u53ea\u66f4\u65b0\u5b98\u65b9\u6700\u65b0\u4e00\u671f")
    parser.add_argument("--start-roc-year", type=int, default=START_ROC_YEAR)
    parser.add_argument("--end-roc-year", type=int)
    parser.add_argument("--require-fresh", action="store_true", help="Fail when the database is behind the expected draw date")
    parser.add_argument("--retry-until-fresh-minutes", type=int, default=0, help="Keep retrying after draw time until the latest expected draw is imported")
    parser.add_argument("--retry-interval-seconds", type=int, default=180, help="Wait time between freshness retry attempts")
    args = parser.parse_args()

    if not args.all and not args.latest:
        args.latest = True

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    backup_database()

    run_type = "all" if args.all else "latest"
    run_id = None
    update_warnings = []
    freshness = None

    def safe_update_step(label, action):
        try:
            return action()
        except Exception as exc:
            message = f"{label}: {exc}"
            update_warnings.append(message)
            logging.warning("\u66f4\u65b0\u6b65\u9a5f\u5931\u6557，\u6539\u7528\u672c\u6a5f\u5df2\u6709\u8cc7\u6599\u7e7c\u7e8c：%s", message)
            return 0

    def run_download_steps(conn, prefix="initial"):
        if args.all:
            safe_update_step(f"{prefix}_annual_download", lambda: import_all_years(conn, args.start_roc_year, args.end_roc_year))
            safe_update_step(f"{prefix}_recent_month_download", lambda: import_recent_months(conn))
            safe_update_step(f"{prefix}_latest_download", lambda: update_latest(conn))
            safe_update_step(f"{prefix}_public_fallback_latest", lambda: import_public_fallback_latest(conn))
        elif args.latest:
            safe_update_step(f"{prefix}_recent_month_download", lambda: import_recent_months(conn, count=1))
            safe_update_step(f"{prefix}_latest_download", lambda: update_latest(conn))
            safe_update_step(f"{prefix}_public_fallback_latest", lambda: import_public_fallback_latest(conn))

    def refresh_export_and_freshness(conn):
        count = export_csv(conn)
        current = stats(conn)
        current_freshness = data_freshness(current["max_date"]) if current["max_date"] else None
        return count, current, current_freshness

    def retry_until_fresh(conn, current_freshness):
        max_minutes = max(int(args.retry_until_fresh_minutes or 0), 0)
        if not current_freshness or current_freshness["status"] == "fresh" or max_minutes <= 0:
            return current_freshness
        if not update_attempt_window_is_open():
            return current_freshness
        deadline = time.monotonic() + max_minutes * 60
        interval = max(int(args.retry_interval_seconds or 180), 30)
        attempt = 0
        while current_freshness and current_freshness["status"] != "fresh" and time.monotonic() < deadline:
            remaining = max(deadline - time.monotonic(), 0)
            sleep_seconds = min(interval, remaining)
            if sleep_seconds > 0:
                logging.warning(
                    "Latest draw is still stale; waiting %.0f seconds before retry. latest=%s expected=%s",
                    sleep_seconds,
                    current_freshness.get("latest_date"),
                    current_freshness.get("expected_latest_date"),
                )
                time.sleep(sleep_seconds)
            attempt += 1
            run_download_steps(conn, f"freshness_retry_{attempt}")
            _, _, current_freshness = refresh_export_and_freshness(conn)
            logging.info("Freshness retry %s result: %s", attempt, json.dumps(current_freshness, ensure_ascii=False))
        return current_freshness

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        run_id = start_run(conn, run_type)
        try:
            run_download_steps(conn)
            count, current, freshness = refresh_export_and_freshness(conn)
            freshness = retry_until_fresh(conn, freshness)
            count, current, freshness = refresh_export_and_freshness(conn)
            if args.require_fresh and freshness and freshness["status"] != "fresh":
                raise RuntimeError(
                    f"database stale: latest={freshness['latest_date']} expected={freshness['expected_latest_date']}"
                )
            if not current["count"]:
                raise RuntimeError("\u8cc7\u6599\u5eab\u6c92\u6709\u4efb\u4f55\u958b\u734e\u8cc7\u6599，\u7121\u6cd5\u7522\u751f\u5206\u6790")
            repaired_missing = repair_missing_prediction_records(conn)
            if repaired_missing["repaired"]:
                logging.warning(
                    "已自動補修缺漏預測紀錄，補修後會立即進入結算：%s",
                    json.dumps(repaired_missing, ensure_ascii=False),
                )
            settled = settle_predictions(conn)
            if settled:
                logging.info("\u5df2\u7d50\u7b97\u9810\u6e2c\u7d00\u9304：%s \u7b46", settled)
            repaired_unlikely = backfill_missing_unlikely_reviews(conn)
            if repaired_unlikely["repaired"]:
                logging.info(
                    "\u5df2\u81ea\u52d5\u56de\u586b\u4f4e\u6a5f\u7387\u6aa2\u8a0e：%s",
                    json.dumps(repaired_unlikely, ensure_ascii=False),
                )
            integrity = integrity_report(conn)
            if integrity["invalid_periods"] or integrity["duplicate_periods"]:
                raise RuntimeError(f"\u8cc7\u6599\u5b8c\u6574\u6027\u6aa2\u67e5\u5931\u6557：{integrity}")
            if update_warnings:
                integrity["warnings"] = update_warnings
                finish_run(conn, run_id, "warning", json.dumps(integrity, ensure_ascii=False))
            else:
                finish_run(conn, run_id, "success", json.dumps(integrity, ensure_ascii=False))
        except Exception as exc:
            finish_run(conn, run_id, "failed", str(exc))
            logging.exception("\u66f4\u65b0\u5931\u6557")
            raise

    analysis = analyze(DB_PATH)
    analysis["data_freshness"] = freshness
    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        live_performance = prediction_performance(conn)
    research_kpi = live_performance.get("research_kpi", {})
    analysis["research_kpi"] = research_kpi
    if not research_kpi.get("release_allowed", False):
        release_gate = analysis.setdefault("industrial_engine", {}).setdefault("release_gate", {})
        release_gate["status"] = "research_kpi_blocked"
        release_gate["research_kpi_status"] = research_kpi.get("status")
        release_gate["research_kpi_release_allowed"] = False
    if freshness and freshness["status"] != "fresh":
        release_gate = analysis.setdefault("industrial_engine", {}).setdefault("release_gate", {})
        release_gate["status"] = "stale_data_blocked"
        release_gate["data_freshness"] = freshness
    save_analysis(analysis)
    competition = run_competition(DB_PATH)
    save_competition(competition)

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        prediction_status = "stale_data_blocked"
        aerospace_status = analysis.get("aerospace_assurance", {}).get("release_assurance", {}).get("status")
        if aerospace_status == "blocked":
            prediction_status = "aerospace_assurance_blocked"
            store_prediction_snapshot(conn, analysis, "aerospace_assurance_blocked_official_prediction")
            conn.commit()
            logging.warning("Official prediction blocked by aerospace assurance.")
        elif freshness and freshness["status"] != "fresh":
            recalculated_status = store_prediction(conn, analysis)
            prediction_status = "stale_data_" + recalculated_status
            logging.warning(
                "Data is stale, but pending prediction was still recalculated to prevent stale reports: latest=%s expected=%s status=%s",
                freshness.get("latest_date"),
                freshness.get("expected_latest_date"),
                recalculated_status,
            )
        else:
            prediction_status = store_prediction(conn, analysis)
            if prediction_status == "inserted":
                logging.info("\u5df2\u65b0\u589e\u9810\u6e2c\u7d00\u9304：based_on_period=%s", analysis["latest_draw"]["period"])
            elif prediction_status == "corrected_pending":
                logging.info("Pending official prediction corrected by previous-prediction guard: based_on_period=%s", analysis["latest_draw"]["period"])
            elif prediction_status == "updated_pending":
                logging.info("Pending official prediction recalculated and updated: based_on_period=%s", analysis["latest_draw"]["period"])
            elif prediction_status == "recalculated_same_as_official":
                logging.info("\u5df2\u91cd\u65b0\u904b\u7b97，\u7d50\u679c\u8207\u76ee\u524d\u6b63\u5f0f\u9810\u6e2c\u76f8\u540c，\u672c\u6b21\u53e6\u5b58\u5feb\u7167：based_on_period=%s", analysis["latest_draw"]["period"])
            else:
                logging.info("\u6b63\u5f0f\u9810\u6e2c\u7d00\u9304\u5df2\u7d50\u7b97，\u672c\u6b21\u91cd\u8dd1\u53e6\u5b58\u5feb\u7167：based_on_period=%s", analysis["latest_draw"]["period"])
        if (
            analysis.get("industrial_engine", {}).get("release_gate", {}).get("status") != "official"
            and prediction_status not in {"stale_data_blocked", "aerospace_assurance_blocked"}
        ):
            prediction_status = "observation_only_" + prediction_status
        analysis["official_prediction_status"] = prediction_status
        save_analysis(analysis)
        performance = prediction_performance(conn)
        logging.info("\u5be6\u969b\u9810\u6e2c\u7e3e\u6548：%s", json.dumps(performance, ensure_ascii=False))

    health = build_health()
    save_health(health)
    logging.info("\u5065\u5eb7\u6aa2\u67e5\u72c0\u614b：%s", health["status"])

    battle_report = build_report()
    save_battle_reports(battle_report)
    logging.info("Battle report: %s", ENHANCED_BATTLE_HTML)
    save_dashboard()
    logging.info("Dashboard: %s", DASHBOARD_HTML)
    try:
        build_mobile_site()
        logging.info("Mobile site rebuilt: %s", BASE_DIR / "site" / "index.html")
    except Exception as exc:
        logging.warning("Mobile site rebuild failed: %s", exc)

    logging.info("\u8cc7\u6599\u5eab：%s", DB_PATH)
    logging.info("CSV：%s", CSV_PATH)
    logging.info("\u5206\u6790\u5831\u544a：%s", BASE_DIR / "reports" / "latest_analysis.md")
    logging.info("\u5019\u9078 Top 10：%s", " ".join(f"{x['number']:02d}" for x in analysis["candidates"][:10]))
    logging.info(
        f"\u76ee\u524d\u5171 {count} \u7b46，\u671f\u5225 {current['min_period']} - {current['max_period']}，"
        f"\u65e5\u671f {current['min_date']} - {current['max_date']}"
    )


if __name__ == "__main__":
    main()

