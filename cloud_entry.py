import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import mobile_server


TAIPEI = ZoneInfo("Asia/Taipei")
LAST_AUTO_RUN = {"date": None}


def bootstrap_persistent_data():
    root = Path(__file__).resolve().parent
    data_dir = root / "data"
    seed_dir = root / "seed"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ["539.sqlite", "539.csv", "\u7db2\u8def\u4eba\u6c23\u4eba\u5de5\u532f\u5165.csv"]:
        target = data_dir / name
        seed = seed_dir / name
        if not target.exists() and seed.exists():
            shutil.copy2(seed, target)


def auto_update_loop():
    while True:
        now = datetime.now(TAIPEI)
        should_run = now.weekday() < 6 and (now.hour > 21 or (now.hour == 21 and now.minute >= 5))
        if should_run and LAST_AUTO_RUN["date"] != now.date().isoformat():
            LAST_AUTO_RUN["date"] = now.date().isoformat()
            mobile_server.run_update()
        time.sleep(300)


def main():
    bootstrap_persistent_data()
    if os.environ.get("AUTO_UPDATE", "1") == "1":
        threading.Thread(target=auto_update_loop, daemon=True).start()
    mobile_server.main()


if __name__ == "__main__":
    main()
