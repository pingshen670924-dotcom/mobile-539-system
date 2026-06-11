import html
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from crowd_consensus import (
    DB_PATH,
    build_consensus,
    ensure_tables,
    parse_numbers,
    save_report,
    store_prediction,
    upsert_source,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
TOKEN_PATH = DATA_DIR / "mobile_access_token.txt"
REPORT_PATH = REPORT_DIR / "539\u6700\u65b0\u5f37\u5316\u6230\u5831.html"
PORT = int(os.environ.get("PORT", "5390"))
RUN_STATE = {"running": False, "message": "ready", "finished_at": None}


def access_token():
    configured = os.environ.get("MOBILE_ACCESS_TOKEN", "").strip()
    if configured:
        return configured
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN_PATH.exists():
        TOKEN_PATH.write_text(secrets.token_urlsafe(10), encoding="ascii")
    return TOKEN_PATH.read_text(encoding="ascii").strip()


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def run_update():
    RUN_STATE.update({"running": True, "message": "updating", "finished_at": None})
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "update_539.py"), "--latest", "--require-fresh"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=900,
        )
        RUN_STATE["message"] = "completed" if result.returncode == 0 else "failed"
    except Exception as exc:
        RUN_STATE["message"] = f"failed: {exc}"
    finally:
        RUN_STATE["running"] = False
        RUN_STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")


def add_crowd_prediction(source_name, source_url, numbers_text, engagement_text):
    numbers = parse_numbers(numbers_text)[:5]
    if len(numbers) != 5:
        raise ValueError("exactly five unique numbers from 1 to 39 are required")
    source_id = "mobile_" + "".join(ch for ch in source_name.lower() if ch.isalnum())[:30]
    source_id = source_id or "mobile_authorized_social"
    engagement = float(engagement_text) if engagement_text else None
    with sqlite3.connect(DB_PATH) as conn:
        ensure_tables(conn)
        latest = conn.execute("SELECT period FROM draws_539 ORDER BY period DESC LIMIT 1").fetchone()
        if not latest:
            raise RuntimeError("draw database is empty")
        target_period = latest[0] + 1
        upsert_source(conn, source_id, source_name, "mobile_authorized_social", source_url)
        inserted = store_prediction(
            conn,
            source_id,
            target_period,
            latest[0],
            numbers,
            engagement,
            "mobile_authorized_import",
        )
        conn.commit()
        report = build_consensus(conn, {"mobile_imported": int(inserted)})
    save_report(report)
    return inserted


def page(message=""):
    token = access_token()
    report_exists = REPORT_PATH.exists()
    status = RUN_STATE["message"]
    message_html = f'<p class="notice">{html.escape(message)}</p>' if message else ""
    report_link = f'/report?token={urllib.parse.quote(token)}' if report_exists else "#"
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#111827">
  <link rel="manifest" href="/manifest.webmanifest?token={urllib.parse.quote(token)}">
  <title>539 Mobile Control</title>
  <style>
    body {{ margin:0; font-family:"Microsoft JhengHei",Arial,sans-serif; background:#f4f6f8; color:#17202a; }}
    header {{ background:#111827; color:white; padding:18px; }}
    main {{ max-width:700px; margin:auto; padding:14px; }}
    section {{ background:white; border:1px solid #dfe4ea; border-radius:8px; padding:16px; margin-bottom:14px; }}
    h1,h2 {{ margin:0 0 12px; }}
    input,button {{ box-sizing:border-box; width:100%; min-height:46px; margin:6px 0; padding:10px; font-size:16px; }}
    button {{ background:#166534; color:white; border:0; border-radius:6px; font-weight:700; }}
    a {{ display:block; text-align:center; background:#0f766e; color:white; padding:13px; border-radius:6px; text-decoration:none; font-weight:700; }}
    .muted {{ color:#64748b; }}
    .notice {{ background:#fff7ed; border-left:4px solid #ea580c; padding:10px; }}
  </style>
</head>
<body>
<header><h1>539 \u624b\u6a5f\u63a7\u5236\u53f0</h1><div>\u4e3b\u7cfb\u7d71\u72c0\u614b\uff1a{html.escape(status)}</div></header>
<main>
{message_html}
<section>
  <h2>\u6700\u65b0\u6230\u5831</h2>
  <a href="{report_link}">\u958b\u555f539\u6700\u65b0\u5f37\u5316\u6230\u5831</a>
</section>
<section>
  <h2>\u7acb\u5373\u66f4\u65b0\u8207\u91cd\u65b0\u904b\u7b97</h2>
  <form method="post" action="/run">
    <input type="hidden" name="token" value="{html.escape(token)}">
    <button type="submit">\u57f7\u884c\u4e3b\u7cfb\u7d71\u5168\u90e8\u66f4\u65b0</button>
  </form>
  <p class="muted">\u82e5\u53f0\u5f69\u5c1a\u672a\u516c\u5e03\u6216\u7db2\u8def\u4e0d\u901a\uff0c\u7cfb\u7d71\u6703\u7981\u6b62\u7528\u820a\u8cc7\u6599\u767c\u5e03\u65b0\u9810\u6e2c\u3002</p>
</section>
<section>
  <h2>\u532f\u5165 Facebook / \u793e\u5718\u4eba\u6c23\u865f\u78bc</h2>
  <form method="post" action="/crowd">
    <input type="hidden" name="token" value="{html.escape(token)}">
    <input name="source_name" placeholder="\u4f86\u6e90\u540d\u7a31\uff0c\u4f8b\uff1aFB 539\u8a0e\u8ad6\u793e" required>
    <input name="source_url" placeholder="\u516c\u958b\u8cbc\u6587\u7db2\u5740\uff08\u53ef\u7559\u7a7a\uff09">
    <input name="numbers" placeholder="\u4e94\u500b\u865f\u78bc\uff0c\u4f8b\uff1a03 11 18 25 36" required>
    <input name="engagement" inputmode="numeric" placeholder="\u4e92\u52d5\u6578\uff08\u8b9a+\u7559\u8a00\uff0c\u53ef\u7559\u7a7a\uff09">
    <button type="submit">\u532f\u5165\u4eba\u6c23\u89c0\u5bdf</button>
  </form>
  <p class="muted">\u4eba\u6c23\u865f\u78bc\u672a\u901a\u904e100\u671f\u56de\u6e2c\u524d\uff0c\u6b0a\u91cd\u70ba0\uff0c\u4e0d\u5f71\u97ff\u6b63\u5f0f\u5019\u9078\u3002</p>
</section>
</main>
</body>
<script>if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js?token={urllib.parse.quote(token)}");</script>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def authorized(self, values):
        return values.get("token", [""])[0] == access_token()

    def send_bytes(self, content, content_type="text/html; charset=utf-8", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        values = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/health":
            self.send_bytes(b'{"status":"ok"}', "application/json; charset=utf-8")
            return
        if not self.authorized(values):
            self.send_bytes(b"Forbidden", "text/plain; charset=utf-8", 403)
            return
        if parsed.path == "/manifest.webmanifest":
            manifest = {
                "name": "539 \u7368\u7acb\u624b\u6a5f\u7cfb\u7d71",
                "short_name": "539\u7cfb\u7d71",
                "start_url": f"/?token={access_token()}",
                "display": "standalone",
                "background_color": "#f4f6f8",
                "theme_color": "#111827",
                "icons": [{"src": f"/icon.svg?token={access_token()}", "sizes": "any", "type": "image/svg+xml"}],
            }
            self.send_bytes(json.dumps(manifest, ensure_ascii=False).encode("utf-8"), "application/manifest+json; charset=utf-8")
            return
        if parsed.path == "/service-worker.js":
            script = "self.addEventListener('fetch',event=>event.respondWith(fetch(event.request)));"
            self.send_bytes(script.encode("utf-8"), "application/javascript; charset=utf-8")
            return
        if parsed.path == "/icon.svg":
            icon = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="72" fill="#111827"/><circle cx="256" cy="256" r="174" fill="#f8fafc"/><text x="256" y="300" text-anchor="middle" font-family="Arial" font-size="150" font-weight="700" fill="#b91c1c">539</text></svg>"""
            self.send_bytes(icon.encode("utf-8"), "image/svg+xml")
            return
        if parsed.path == "/report" and REPORT_PATH.exists():
            self.send_bytes(REPORT_PATH.read_bytes())
            return
        if parsed.path == "/api/status":
            self.send_bytes(json.dumps(RUN_STATE).encode("utf-8"), "application/json; charset=utf-8")
            return
        self.send_bytes(page().encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        values = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        if not self.authorized(values):
            self.send_bytes(b"Forbidden", "text/plain; charset=utf-8", 403)
            return
        if self.path == "/run":
            if not RUN_STATE["running"]:
                threading.Thread(target=run_update, daemon=True).start()
            self.send_bytes(page("\u5df2\u555f\u52d5\u4e3b\u7cfb\u7d71\u66f4\u65b0\uff0c\u8acb\u7a0d\u5f8c\u91cd\u65b0\u6574\u7406\u3002").encode("utf-8"))
            return
        if self.path == "/crowd":
            try:
                inserted = add_crowd_prediction(
                    values.get("source_name", [""])[0],
                    values.get("source_url", [""])[0],
                    values.get("numbers", [""])[0],
                    values.get("engagement", [""])[0],
                )
                message = "\u5df2\u532f\u5165\u4eba\u6c23\u865f\u78bc\u3002" if inserted else "\u6b64\u4f86\u6e90\u672c\u671f\u5df2\u532f\u5165\uff0c\u672a\u91cd\u8907\u8986\u84cb\u3002"
            except Exception as exc:
                message = f"\u532f\u5165\u5931\u6557\uff1a{exc}"
            self.send_bytes(page(message).encode("utf-8"))
            return
        self.send_bytes(b"Not Found", "text/plain; charset=utf-8", 404)

    def log_message(self, format_string, *args):
        return


def main():
    token = access_token()
    address = local_ip()
    print(f"Mobile control: http://{address}:{PORT}/?token={token}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
