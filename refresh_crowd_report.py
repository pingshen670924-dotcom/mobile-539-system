import json

from analyze_539 import LATEST_JSON, save_analysis
from battle_report import save_battle_reports
from crowd_consensus import run_cycle
from dashboard import save_dashboard


def main():
    analysis = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    analysis["crowd_consensus"] = run_cycle()
    save_analysis(analysis)
    save_battle_reports()
    save_dashboard()


if __name__ == "__main__":
    main()
