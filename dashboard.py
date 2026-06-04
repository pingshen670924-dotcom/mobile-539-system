import json
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "539.sqlite"
DASHBOARD_HTML = REPORT_DIR / "dashboard.html"


def load_json(name):
    path = REPORT_DIR / name
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return {}
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def fmt_numbers(numbers):
    return " ".join(f"{int(n):02d}" for n in numbers)


def recent_predictions(limit=20):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT based_on_period, target_period, status, actual_period,
                   top5_hits, top10_hits, top15_hits
            FROM predictions_539
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows


def render_dashboard():
    analysis = load_json("latest_analysis.json")
    health = load_json("health_status.json")
    competition = load_json("model_competition.json")
    latest = analysis.get("latest_draw", {})
    packs = analysis.get("strong_prediction_packs", {})
    industrial = analysis.get("industrial_engine", {})
    audit = industrial.get("model_audit", {})
    champion = competition.get("champion", {})
    predictions = recent_predictions()

    pack_rows = ""
    for key in ["strong_single", "two_hit_one", "three_hit_one", "five_hit_two", "nine_hit_three"]:
        pack = packs.get(key, {})
        if not pack:
            continue
        probability = pack.get("theoretical_probability", {})
        pack_rows += (
            "<tr>"
            f"<td>{pack.get('name')}</td><td>{fmt_numbers(pack.get('numbers', []))}</td>"
            f"<td>{probability.get('probability')}</td><td>1/{probability.get('odds_1_in')}</td>"
            "</tr>"
        )

    model_rows = ""
    for model in competition.get("models", []):
        model_rows += (
            "<tr>"
            f"<td>{model.get('model')}</td><td>{model.get('top10_avg_hits')}</td><td>{model.get('top15_avg_hits')}</td>"
            f"<td>{fmt_numbers(model.get('top10', []))}</td>"
            "</tr>"
        )

    prediction_rows = ""
    for row in predictions:
        prediction_rows += (
            "<tr>"
            f"<td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{row[3] or ''}</td>"
            f"<td>{row[4] if row[4] is not None else ''}</td><td>{row[5] if row[5] is not None else ''}</td><td>{row[6] if row[6] is not None else ''}</td>"
            "</tr>"
        )

    latest_numbers = fmt_numbers(latest.get("numbers", []))
    status = health.get("status", "unknown")
    risk = audit.get("risk_level", "\u672a\u77e5")
    verdict = audit.get("verdict", "")

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>539 \u4e3b\u7cfb\u7d71\u5100\u8868\u677f</title>
  <style>
    body {{ margin:0; font-family:"Microsoft JhengHei", Arial, sans-serif; background:#f5f6f8; color:#1f2937; }}
    header {{ background:#111827; color:white; padding:22px 28px; }}
    main {{ max-width:1280px; margin:auto; padding:20px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; }}
    .card,.panel {{ background:white; border:1px solid #e5e7eb; border-radius:8px; padding:16px; }}
    .card h2,.panel h2 {{ margin:0 0 10px; font-size:17px; color:#475569; }}
    .big {{ font-size:27px; font-weight:800; }}
    .muted {{ color:#64748b; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid #e5e7eb; padding:8px; text-align:left; }}
    th {{ background:#f1f5f9; }}
    .panel {{ margin-top:16px; }}
    .tag {{ display:inline-block; background:#e0f2fe; color:#075985; padding:4px 10px; border-radius:999px; font-weight:700; }}
  </style>
</head>
<body>
  <header>
    <h1>539 \u4e3b\u7cfb\u7d71\u5100\u8868\u677f</h1>
    <div>\u6700\u65b0\u671f\u5225 {latest.get('period')} / \u958b\u734e {latest_numbers}</div>
  </header>
  <main>
    <div class="grid">
      <section class="card"><h2>\u7cfb\u7d71\u72c0\u614b</h2><div class="big">{status}</div><p class="muted">\u5099\u4efd {health.get('backup_count', 0)} / \u8cc7\u6599 {health.get('draw_count', 0)} \u7b46</p></section>
      <section class="card"><h2>\u98a8\u96aa\u7b49\u7d1a</h2><div class="big">{risk}</div><p class="muted">{verdict}</p></section>
      <section class="card"><h2>\u7af6\u8cfd\u51a0\u8ecd</h2><div class="big">{champion.get('model')}</div><p class="muted">Top10 {champion.get('top10_avg_hits')} / Top15 {champion.get('top15_avg_hits')}</p></section>
      <section class="card"><h2>\u771f\u5be6\u8ffd\u8e64</h2><div class="big">{health.get('settled_predictions', 0)}</div><p class="muted">\u5df2\u7d50\u7b97\uff0c\u5f85\u7d50\u7b97 {health.get('pending_predictions', 0)}</p></section>
    </div>
    <section class="panel"><h2>\u5f37\u724c\u7d44</h2><table><thead><tr><th>\u9805\u76ee</th><th>\u865f\u78bc</th><th>\u7406\u8ad6\u6a5f\u7387</th><th>\u8ce0\u7387\u5f0f</th></tr></thead><tbody>{pack_rows}</tbody></table></section>
    <section class="panel"><h2>\u591a\u6a21\u578b\u7af6\u8cfd</h2><table><thead><tr><th>\u6a21\u578b</th><th>Top10</th><th>Top15</th><th>\u5019\u9078Top10</th></tr></thead><tbody>{model_rows}</tbody></table></section>
    <section class="panel"><h2>\u9810\u6e2c\u7d50\u7b97\u8ffd\u8e64</h2><table><thead><tr><th>\u4f9d\u64da\u671f</th><th>\u76ee\u6a19\u671f</th><th>\u72c0\u614b</th><th>\u5be6\u969b\u671f</th><th>Top5</th><th>Top10</th><th>Top15</th></tr></thead><tbody>{prediction_rows}</tbody></table></section>
    <section class="panel"><h2>\u6377\u5f91</h2><p><a href="539\u6700\u65b0\u5f37\u5316\u6230\u5831.html">\u958b\u555f539\u6700\u65b0\u5f37\u5316\u6230\u5831</a> / <a href="health_status.md">\u5065\u5eb7\u6aa2\u67e5</a> / <a href="model_competition.md">\u6a21\u578b\u7af6\u8cfd\u5831\u544a</a></p></section>
  </main>
</body>
</html>"""


def save_dashboard():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_HTML.write_text(render_dashboard(), encoding="utf-8")


def main():
    save_dashboard()
    print(f"dashboard saved: {DASHBOARD_HTML}")


if __name__ == "__main__":
    main()
