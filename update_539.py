import argparse
import csv
import io
import json
import logging
import shutil
import sqlite3
import ssl
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from analyze_539 import analyze, save_analysis
from battle_report import ENHANCED_BATTLE_HTML, build_report, save_battle_reports
from crowd_consensus import run_cycle as run_crowd_cycle
from dashboard import DASHBOARD_HTML, save_dashboard
from health_check import build_health, save_health
from model_competition import run_competition, save_competition


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups"
DB_PATH = DATA_DIR / "539.sqlite"
CSV_PATH = DATA_DIR / "539.csv"

API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB"
DOWNLOAD_API = f"{API_BASE}/Lottery/ResultDownload"
LATEST_API = f"{API_BASE}/Lottery/LatestResult"
HISTORY_API = f"{API_BASE}/Lottery/Daily539Result"

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
    if now.time() < clock_time(21, 0):
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
    raise RuntimeError(f"\u4e0b\u8f09\u5931\u6557：{url} ({last_error})")


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
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_539_status ON predictions_539(status)")
    ensure_column(conn, "predictions_539", "strong_packs_json", "TEXT")
    ensure_column(conn, "predictions_539", "strong_pack_hits_json", "TEXT")
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
            model_weights_json TEXT NOT NULL,
            backtest_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            snapshot_reason TEXT NOT NULL
        )
        """
    )
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


def settle_predictions(conn):
    pending = conn.execute(
        """
        SELECT id, based_on_period, candidates_json, suggested_sets_json, strong_packs_json
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
        conn.execute(
            """
            UPDATE predictions_539
            SET settled_at=?, actual_period=?, actual_date=?, actual_numbers_json=?,
                top5_hits=?, top10_hits=?, top15_hits=?, set_hits_json=?,
                strong_pack_hits_json=?, status='settled'
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
                prediction[0],
            ),
        )
        settled += 1
    conn.commit()
    return settled


def store_prediction_snapshot(conn, analysis, reason):
    latest = analysis["latest_draw"]
    conn.execute(
        """
        INSERT INTO prediction_snapshots_539 (
            based_on_period, based_on_date, target_period,
            candidates_json, suggested_sets_json, strong_packs_json,
            model_weights_json, backtest_json, created_at, snapshot_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            latest["period"],
            latest["draw_date"],
            latest["period"] + 1,
            json.dumps(analysis["candidates"], ensure_ascii=False),
            json.dumps(analysis["suggested_sets"], ensure_ascii=False),
            json.dumps(analysis["strong_prediction_packs"], ensure_ascii=False),
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
               candidates_json, suggested_sets_json, strong_packs_json,
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
            candidates_json, suggested_sets_json, strong_packs_json,
            model_weights_json, backtest_json, created_at, snapshot_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*row, datetime.now().isoformat(timespec="seconds"), reason),
    )


def store_prediction(conn, analysis):
    latest = analysis["latest_draw"]
    exists = conn.execute(
        "SELECT id, status, candidates_json FROM predictions_539 WHERE based_on_period=?",
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
                SET candidates_json=?, suggested_sets_json=?, strong_packs_json=?,
                    model_weights_json=?, backtest_json=?, created_at=?
                WHERE id=?
                """,
                (
                    json.dumps(analysis["candidates"], ensure_ascii=False),
                    json.dumps(analysis["suggested_sets"], ensure_ascii=False),
                    json.dumps(analysis["strong_prediction_packs"], ensure_ascii=False),
                    json.dumps(analysis["model_weights"], ensure_ascii=False),
                    json.dumps(analysis["backtest"], ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                    exists[0],
                ),
            )
            store_prediction_snapshot(conn, analysis, "official_prediction_corrected_by_previous_prediction_guard")
            conn.commit()
            return "corrected_pending"
        store_prediction_snapshot(conn, analysis, "rerun_preserved_official_prediction")
        conn.commit()
        return "preserved_pending" if exists[1] == "pending" else "preserved_settled"
    conn.execute(
        """
        INSERT INTO predictions_539 (
            based_on_period, based_on_date, target_period,
            candidates_json, suggested_sets_json, strong_packs_json, model_weights_json, backtest_json,
            created_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            latest["period"],
            latest["draw_date"],
            latest["period"] + 1,
            json.dumps(analysis["candidates"], ensure_ascii=False),
            json.dumps(analysis["suggested_sets"], ensure_ascii=False),
            json.dumps(analysis["strong_prediction_packs"], ensure_ascii=False),
            json.dumps(analysis["model_weights"], ensure_ascii=False),
            json.dumps(analysis["backtest"], ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    store_prediction_snapshot(conn, analysis, "official_prediction_created")
    conn.commit()
    return "inserted"


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
    set_hit_totals = []
    pack_stats = defaultdict(lambda: {"rounds": 0, "passed": 0, "hits": 0})
    for row in rows:
        set_hits = json.loads(row[3] or "[]")
        set_hit_totals.extend(item["hits"] for item in set_hits)
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
        "set_avg_hits": round(sum(set_hit_totals) / len(set_hit_totals), 3) if set_hit_totals else 0,
        "strong_pack_stats": {
            key: {
                "rounds": value["rounds"],
                "pass_rate": round(value["passed"] / value["rounds"], 3) if value["rounds"] else 0,
                "avg_hits": round(value["hits"] / value["rounds"], 3) if value["rounds"] else 0,
            }
            for key, value in pack_stats.items()
        },
    }


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="\u4eca\u5f69539\u6b77\u53f2\u8207\u6700\u65b0\u958b\u734e\u8cc7\u6599\u66f4\u65b0")
    parser.add_argument("--all", action="store_true", help="\u532f\u5165\u6c11\u570b96\u5e74\u81f3\u4eca\u5e74\u7684\u5b98\u65b9\u5e74\u5ea6\u6a94，\u4e26\u66f4\u65b0\u6700\u65b0\u4e00\u671f")
    parser.add_argument("--latest", action="store_true", help="\u53ea\u66f4\u65b0\u5b98\u65b9\u6700\u65b0\u4e00\u671f")
    parser.add_argument("--start-roc-year", type=int, default=START_ROC_YEAR)
    parser.add_argument("--end-roc-year", type=int)
    parser.add_argument("--require-fresh", action="store_true", help="Fail when the database is behind the expected draw date")
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

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        run_id = start_run(conn, run_type)
        try:
            if args.all:
                safe_update_step("annual_download", lambda: import_all_years(conn, args.start_roc_year, args.end_roc_year))
                safe_update_step("recent_month_download", lambda: import_recent_months(conn))
                safe_update_step("latest_download", lambda: update_latest(conn))
            elif args.latest:
                safe_update_step("recent_month_download", lambda: import_recent_months(conn, count=1))
                safe_update_step("latest_download", lambda: update_latest(conn))

            count = export_csv(conn)
            current = stats(conn)
            freshness = data_freshness(current["max_date"]) if current["max_date"] else None
            if args.require_fresh and freshness and freshness["status"] != "fresh":
                raise RuntimeError(
                    f"database stale: latest={freshness['latest_date']} expected={freshness['expected_latest_date']}"
                )
            if not current["count"]:
                raise RuntimeError("\u8cc7\u6599\u5eab\u6c92\u6709\u4efb\u4f55\u958b\u734e\u8cc7\u6599，\u7121\u6cd5\u7522\u751f\u5206\u6790")
            settled = settle_predictions(conn)
            if settled:
                logging.info("\u5df2\u7d50\u7b97\u9810\u6e2c\u7d00\u9304：%s \u7b46", settled)
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
    crowd_consensus = run_crowd_cycle(DB_PATH)
    analysis["crowd_consensus"] = crowd_consensus
    analysis["data_freshness"] = freshness
    if freshness and freshness["status"] != "fresh":
        release_gate = analysis.setdefault("industrial_engine", {}).setdefault("release_gate", {})
        release_gate["status"] = "stale_data_blocked"
        release_gate["data_freshness"] = freshness
    save_analysis(analysis)
    competition = run_competition(DB_PATH)
    save_competition(competition)

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        prediction_status = store_prediction(conn, analysis)
        if prediction_status == "inserted":
            logging.info("\u5df2\u65b0\u589e\u9810\u6e2c\u7d00\u9304：based_on_period=%s", analysis["latest_draw"]["period"])
        elif prediction_status == "corrected_pending":
            logging.info("Pending official prediction corrected by previous-prediction guard: based_on_period=%s", analysis["latest_draw"]["period"])
        elif prediction_status == "preserved_pending":
            logging.info("\u5df2\u4fdd\u7559\u540c\u671f\u5f85\u7d50\u7b97\u6b63\u5f0f\u9810\u6e2c，\u672c\u6b21\u91cd\u8dd1\u53e6\u5b58\u5feb\u7167：based_on_period=%s", analysis["latest_draw"]["period"])
        else:
            logging.info("\u6b63\u5f0f\u9810\u6e2c\u7d00\u9304\u5df2\u7d50\u7b97，\u672c\u6b21\u91cd\u8dd1\u53e6\u5b58\u5feb\u7167：based_on_period=%s", analysis["latest_draw"]["period"])
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
