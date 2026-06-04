import csv
import json
import re
import sqlite3
import ssl
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
MANUAL_CSV = DATA_DIR / "\u7db2\u8def\u4eba\u6c23\u4eba\u5de5\u532f\u5165.csv"
REPORT_JSON = REPORT_DIR / "crowd_consensus.json"
PUBLIC_SOURCES = [
    {
        "source_id": "pilio_public_share",
        "name": "\u5f69\u8ff7\u71b1\u9580\u865f\u78bc\u5206\u4eab",
        "url": "https://www.pilio.idv.tw/lto539/ltoshare539_Do.asp",
        "type": "public_crowd_share",
    },
]
RANDOM_TOP5_EXPECTATION = 25 / 39


def ensure_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crowd_sources_539 (
            source_id TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crowd_predictions_539 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_period INTEGER NOT NULL,
            based_on_period INTEGER NOT NULL,
            collected_at TEXT NOT NULL,
            numbers_json TEXT NOT NULL,
            engagement REAL,
            raw_text TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            actual_period INTEGER,
            actual_numbers_json TEXT,
            hits INTEGER,
            settled_at TEXT,
            UNIQUE(source_id, target_period)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crowd_target ON crowd_predictions_539(target_period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crowd_status ON crowd_predictions_539(status)")
    for source in PUBLIC_SOURCES:
        conn.execute(
            """
            INSERT INTO crowd_sources_539 (
                source_id, source_name, source_type, source_url, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                source_name=excluded.source_name,
                source_type=excluded.source_type,
                source_url=excluded.source_url
            """,
            (
                source["source_id"],
                source["name"],
                source["type"],
                source["url"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    conn.commit()


def parse_numbers(value):
    numbers = []
    for token in re.findall(r"(?<!\d)(?:0?[1-9]|[12]\d|3[0-9])(?!\d)", value or ""):
        number = int(token)
        if 1 <= number <= 39 and number not in numbers:
            numbers.append(number)
    return numbers


def fetch_public_share(source):
    request = urllib.request.Request(
        source["url"],
        headers={"User-Agent": "Mozilla/5.0 539-crowd-consensus/1.0"},
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        text = response.read().decode("utf-8", errors="ignore")
    marker = "\u672c\u671f\u4eca\u5f69539-\u5f69\u8ff7\u71b1\u9580\u5206\u4eab\u865f\u78bc\u53c3\u8003"
    start = text.find(marker)
    segment = text[start:start + 500] if start >= 0 else text[:1500]
    numbers = parse_numbers(segment)[:5]
    if len(numbers) != 5:
        raise RuntimeError("public crowd source did not expose exactly five current numbers")
    return numbers, segment[:500]


def ensure_manual_template():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if MANUAL_CSV.exists():
        return
    with MANUAL_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["target_period", "source_id", "source_name", "source_url", "numbers", "engagement", "collected_at"])


def upsert_source(conn, source_id, source_name, source_type, source_url):
    conn.execute(
        """
        INSERT INTO crowd_sources_539 (
            source_id, source_name, source_type, source_url, created_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_name=excluded.source_name,
            source_type=excluded.source_type,
            source_url=excluded.source_url
        """,
        (source_id, source_name, source_type, source_url, datetime.now().isoformat(timespec="seconds")),
    )


def store_prediction(conn, source_id, target_period, based_on_period, numbers, engagement=None, raw_text=""):
    if len(numbers) != 5:
        return False
    cursor = conn.execute(
        """
        INSERT INTO crowd_predictions_539 (
            source_id, target_period, based_on_period, collected_at,
            numbers_json, engagement, raw_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, target_period) DO NOTHING
        """,
        (
            source_id,
            target_period,
            based_on_period,
            datetime.now().isoformat(timespec="seconds"),
            json.dumps(numbers),
            engagement,
            raw_text,
        ),
    )
    return cursor.rowcount > 0


def import_manual(conn, target_period, based_on_period):
    ensure_manual_template()
    imported = 0
    with MANUAL_CSV.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            row_target = int(row.get("target_period") or target_period)
            if row_target != target_period:
                continue
            numbers = parse_numbers(row.get("numbers", ""))[:5]
            source_id = (row.get("source_id") or "").strip()
            if not source_id or len(numbers) != 5:
                continue
            upsert_source(
                conn,
                source_id,
                (row.get("source_name") or source_id).strip(),
                "manual_authorized_social",
                (row.get("source_url") or "").strip(),
            )
            engagement = float(row["engagement"]) if row.get("engagement") else None
            imported += int(store_prediction(conn, source_id, row_target, based_on_period, numbers, engagement, "manual_import"))
    return imported


def collect_current(conn):
    latest = conn.execute("SELECT period FROM draws_539 ORDER BY period DESC LIMIT 1").fetchone()
    if not latest:
        return {"collected": 0, "warnings": ["draw database empty"]}
    based_on_period = latest[0]
    target_period = based_on_period + 1
    collected = 0
    warnings = []
    for source in PUBLIC_SOURCES:
        try:
            numbers, raw_text = fetch_public_share(source)
            collected += int(store_prediction(conn, source["source_id"], target_period, based_on_period, numbers, raw_text=raw_text))
        except Exception as exc:
            warnings.append(f"{source['source_id']}: {exc}")
    collected += import_manual(conn, target_period, based_on_period)
    conn.commit()
    return {"collected": collected, "warnings": warnings, "target_period": target_period}


def settle_predictions(conn):
    pending = conn.execute(
        "SELECT id, target_period, numbers_json FROM crowd_predictions_539 WHERE status='pending'"
    ).fetchall()
    settled = 0
    for row in pending:
        actual = conn.execute(
            "SELECT period, n1, n2, n3, n4, n5 FROM draws_539 WHERE period=?",
            (row[1],),
        ).fetchone()
        if not actual:
            continue
        actual_numbers = set(actual[1:6])
        numbers = set(json.loads(row[2]))
        conn.execute(
            """
            UPDATE crowd_predictions_539
            SET status='settled', actual_period=?, actual_numbers_json=?,
                hits=?, settled_at=?
            WHERE id=?
            """,
            (
                actual[0],
                json.dumps(sorted(actual_numbers)),
                len(numbers & actual_numbers),
                datetime.now().isoformat(timespec="seconds"),
                row[0],
            ),
        )
        settled += 1
    conn.commit()
    return settled


def source_performance(conn):
    sources = conn.execute(
        "SELECT source_id, source_name, source_type, source_url FROM crowd_sources_539 WHERE enabled=1"
    ).fetchall()
    result = []
    for source in sources:
        hits = [
            row[0] for row in conn.execute(
                "SELECT hits FROM crowd_predictions_539 WHERE source_id=? AND status='settled' ORDER BY target_period",
                (source[0],),
            ).fetchall()
        ]
        average = sum(hits) / len(hits) if hits else 0
        recent = hits[-30:]
        recent_average = sum(recent) / len(recent) if recent else 0
        eligible = len(hits) >= 100 and average > RANDOM_TOP5_EXPECTATION and recent_average > RANDOM_TOP5_EXPECTATION
        result.append(
            {
                "source_id": source[0],
                "source_name": source[1],
                "source_type": source[2],
                "source_url": source[3],
                "settled_rounds": len(hits),
                "avg_hits": round(average, 3),
                "recent30_avg_hits": round(recent_average, 3),
                "edge_vs_random": round(average - RANDOM_TOP5_EXPECTATION, 3),
                "eligible_for_model": eligible,
                "model_weight_cap": 0.10 if eligible else 0.0,
            }
        )
    return result


def build_consensus(conn, collection=None):
    latest = conn.execute("SELECT period FROM draws_539 ORDER BY period DESC LIMIT 1").fetchone()
    target_period = latest[0] + 1 if latest else None
    rows = conn.execute(
        """
        SELECT p.source_id, s.source_name, s.source_type, s.source_url,
               p.numbers_json, p.engagement, p.collected_at
        FROM crowd_predictions_539 p
        JOIN crowd_sources_539 s ON s.source_id=p.source_id
        WHERE p.target_period=?
        ORDER BY p.source_id
        """,
        (target_period,),
    ).fetchall()
    votes = Counter()
    observations = []
    for row in rows:
        numbers = json.loads(row[4])
        votes.update(numbers)
        observations.append(
            {
                "source_id": row[0],
                "source_name": row[1],
                "source_type": row[2],
                "source_url": row[3],
                "numbers": numbers,
                "engagement": row[5],
                "collected_at": row[6],
            }
        )
    ranked = [
        {"number": number, "source_votes": count}
        for number, count in sorted(votes.items(), key=lambda item: (-item[1], item[0]))
    ]
    performance = source_performance(conn)
    eligible_sources = [item for item in performance if item["eligible_for_model"]]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_period": target_period,
        "source_count": len(observations),
        "observations": observations,
        "consensus_ranking": ranked,
        "source_performance": performance,
        "eligible_source_count": len(eligible_sources),
        "model_influence_status": "enabled_capped_10_percent" if eligible_sources else "observation_only_weight_zero",
        "random_top5_expected_hits": round(RANDOM_TOP5_EXPECTATION, 3),
        "collection": collection or {},
        "warning": "\u7db2\u8def\u4eba\u6c23\u4e0d\u7b49\u65bc\u958b\u51fa\u6a5f\u7387\uff0c\u672a\u901a\u904e100\u671f\u8207\u8fd1\u671f\u56de\u6e2c\u7684\u4f86\u6e90\u6b0a\u91cd\u70ba0",
    }


def save_report(report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cycle(db_path=DB_PATH):
    ensure_manual_template()
    with sqlite3.connect(db_path) as conn:
        ensure_tables(conn)
        settled = settle_predictions(conn)
        collection = collect_current(conn)
        collection["settled"] = settled
        report = build_consensus(conn, collection)
    save_report(report)
    return report


if __name__ == "__main__":
    result = run_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
