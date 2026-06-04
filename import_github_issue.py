import csv
import os
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "data" / "\u7db2\u8def\u4eba\u6c23\u4eba\u5de5\u532f\u5165.csv"


def field(body, title):
    match = re.search(rf"### {re.escape(title)}\s*\n+(.+?)(?=\n+### |\Z)", body, re.S)
    return match.group(1).strip() if match else ""


def main():
    body = os.environ.get("ISSUE_BODY", "")
    source_name = field(body, "\u4f86\u6e90\u540d\u7a31")
    source_url = field(body, "\u516c\u958b\u8cbc\u6587\u7db2\u5740")
    numbers = field(body, "\u4e94\u500b\u4eba\u6c23\u865f\u78bc")
    engagement = field(body, "\u4e92\u52d5\u6578")
    target_period = field(body, "\u76ee\u6a19\u671f\u5225")
    parsed = []
    for token in re.findall(r"(?<!\d)(?:0?[1-9]|[12]\d|3[0-9])(?!\d)", numbers):
        number = int(token)
        if number not in parsed:
            parsed.append(number)
    if len(parsed) != 5 or not source_name or not target_period.isdigit():
        raise SystemExit("Issue form values are invalid.")
    source_id = "github_" + re.sub(r"[^a-zA-Z0-9]+", "_", source_name).strip("_").lower()[:40]
    with CSV_PATH.open("a", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerow(
            [
                target_period,
                source_id,
                source_name,
                "" if source_url == "_No response_" else source_url,
                " ".join(f"{number:02d}" for number in parsed),
                "" if engagement == "_No response_" else engagement,
                datetime.now().isoformat(timespec="seconds"),
            ]
        )


if __name__ == "__main__":
    main()
