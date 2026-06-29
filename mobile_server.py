import html
import json
import mimetypes
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
SITE_DIR = BASE_DIR / "site"
TOKEN_PATH = DATA_DIR / "mobile_access_token.txt"
REPORT_PATH = REPORT_DIR / "539\u6700\u65b0\u5f37\u5316\u6230\u5831.html"
LATEST_REPORT_PATH = REPORT_DIR / "latest_battle_report.html"
PORT = int(os.environ.get("PORT", "5390"))
RUN_STATE = {"running": False, "message": "ready", "finished_at": None}
MOBILE_REPORT_ENTRY_PATHS = {
    "/site",
    "/site/",
    "/site/index.html",
    "/site/latest.html",
    "/site/clear-cache.html",
    "/latest",
    "/latest.html",
    "/clear-cache.html",
}


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


def current_report_path():
    if REPORT_PATH.exists():
        return REPORT_PATH
    return LATEST_REPORT_PATH


def latest_mobile_version():
    version_path = SITE_DIR / "version.json"
    if version_path.exists():
        try:
            return json.loads(version_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "version": datetime.now().strftime("%Y%m%d%H%M%S"),
        "mobile_built_at": datetime.now().isoformat(timespec="seconds"),
        "latest_period": None,
        "latest_draw_date": None,
    }


def mobile_urls():
    token = access_token()
    version = str(latest_mobile_version().get("version") or datetime.now().strftime("%Y%m%d%H%M%S"))
    base_url = f"http://{local_ip()}:{PORT}"
    query = f"token={urllib.parse.quote(token)}&v={urllib.parse.quote(version)}"
    return {
        "control_url": f"{base_url}/?{query}",
        "report_url": f"{base_url}/report?{query}",
        "site_url": f"{base_url}/site/index.html?{query}",
        "version": version,
    }


def write_mobile_entry_files():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    urls = mobile_urls()
    version = latest_mobile_version()
    independent_url_path = BASE_DIR / "\u624b\u6a5f\u7368\u7acb\u7248\u7db2\u5740.txt"
    independent_url = ""
    if independent_url_path.exists():
        independent_url = independent_url_path.read_text(encoding="utf-8").strip()
    entry_url = independent_url or urls["site_url"]
    payload = {
        "status": "ready",
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "report_url": urls["report_url"],
        "control_url": urls["control_url"],
        "site_url": entry_url,
        "lan_site_url": urls["site_url"],
        "version": urls["version"],
        "latest_period": version.get("latest_period"),
        "latest_draw_date": version.get("latest_draw_date"),
        "mobile_built_at": version.get("mobile_built_at"),
        "cache_policy": "independent_cloud_url_preserved_lan_report_no_store",
    }
    report_url_name = "\u624b\u6a5f\u6230\u5831\u5373\u6642\u7db2\u5740.txt"
    control_url_name = "\u624b\u6a5f\u63a7\u5236\u53f0\u7db2\u5740.txt"
    status_name = "\u624b\u6a5f\u6230\u5831\u66f4\u65b0\u72c0\u614b.json"
    (BASE_DIR / report_url_name).write_text(urls["report_url"], encoding="utf-8")
    (BASE_DIR / control_url_name).write_text(urls["control_url"], encoding="utf-8")
    (BASE_DIR / status_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (BASE_DIR / "\u6253\u958b\u6700\u65b0\u624b\u6a5f\u7248.html").write_text(
        f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>&#25171;&#38283;&#26368;&#26032;&#25163;&#27231;&#25136;&#22577;</title>
  <meta http-equiv="refresh" content="0; url={html.escape(entry_url, quote=True)}">
</head>
<body>
  <p>&#27491;&#22312;&#25171;&#38283;&#26368;&#26032;&#25163;&#27231;&#29544;&#31435;&#29256;...</p>
  <p><a href="{html.escape(entry_url, quote=True)}">&#33509;&#27794;&#26377;&#33258;&#21205;&#36339;&#36681;&#65292;&#35531;&#40670;&#36889;&#35041;</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )
    return payload


def run_python_step(name, script, args=None, timeout=900, required=False):
    args = args or []
    command = [sys.executable, str(BASE_DIR / script), *args]
    try:
        result = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "name": name,
            "returncode": result.returncode,
            "required": required,
            "stdout_tail": result.stdout[-3000:],
            "stderr_tail": result.stderr[-3000:],
        }
    except Exception as exc:
        return {
            "name": name,
            "returncode": 1,
            "required": required,
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }


def run_update():
    RUN_STATE.update({"running": True, "message": "updating", "finished_at": None})
    update_log = []
    try:
        steps = [
            ("update_latest_draw", "update_539.py", ["--latest", "--require-fresh", "--retry-until-fresh-minutes", "90", "--retry-interval-seconds", "45"], False),
            ("model_competition", "model_competition.py", [], False),
            ("rebuild_battle_report", "battle_report.py", [], True),
            ("health_check", "health_check.py", [], False),
            ("rebuild_battle_report_after_health", "battle_report.py", [], True),
            ("build_phone_site", "pages_build.py", [], False),
        ]
        failed_required = False
        for name, script, args, required in steps:
            result = run_python_step(name, script, args=args, required=required)
            update_log.append(result)
            if result["returncode"] != 0 and required:
                failed_required = True
        entry_payload = write_mobile_entry_files()
        update_log.append({"name": "write_mobile_entry_files", "returncode": 0, "required": False, "payload": entry_payload})
        RUN_STATE["message"] = "completed" if not failed_required else "failed"
    except Exception as exc:
        RUN_STATE["message"] = f"failed: {exc}"
    finally:
        RUN_STATE["running"] = False
        RUN_STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "mobile_update_status.json").write_text(
            json.dumps({"run_state": RUN_STATE, "steps": update_log}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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
    version = latest_mobile_version()
    urls = mobile_urls()
    report_exists = current_report_path().exists()
    status = RUN_STATE["message"]
    message_html = f'<p class="notice">{html.escape(message)}</p>' if message else ""
    report_link = f'/report?token={urllib.parse.quote(token)}&v={urllib.parse.quote(str(version.get("version", "")))}' if report_exists else "#"
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
  <p class="muted">\u624b\u6a5f\u5efa\u7acb\uff1a{html.escape(str(version.get("mobile_built_at", "-")))} / \u6700\u65b0\u671f\u6578\uff1a{html.escape(str(version.get("latest_period", "-")))} / {html.escape(str(version.get("latest_draw_date", "-")))}</p>
  <p class="muted">\u5373\u6642\u6230\u5831\u7db2\u5740\uff1a{html.escape(urls["report_url"])}</p>
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

    def report_location(self):
        token = urllib.parse.quote(access_token())
        version = str(latest_mobile_version().get("version") or datetime.now().strftime("%Y%m%d%H%M%S"))
        return f"/report?token={token}&v={urllib.parse.quote(version)}"

    def redirect_to_report(self):
        self.send_response(302)
        self.send_header("Location", self.report_location())
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()

    def send_bytes(self, content, content_type="text/html; charset=utf-8", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
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
        if parsed.path in MOBILE_REPORT_ENTRY_PATHS:
            self.redirect_to_report()
            return
        if parsed.path == "/manifest.webmanifest":
            manifest = {
                "name": "539 \u7368\u7acb\u624b\u6a5f\u7cfb\u7d71",
                "short_name": "539\u7cfb\u7d71",
                "start_url": self.report_location(),
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
        site_file = self.resolve_site_file(parsed.path)
        if site_file:
            content_type = mimetypes.guess_type(str(site_file))[0] or "application/octet-stream"
            if content_type.startswith("text/") or site_file.suffix in {".json", ".js", ".webmanifest", ".svg"}:
                content_type += "; charset=utf-8"
            self.send_bytes(site_file.read_bytes(), content_type)
            return
        report_path = current_report_path()
        if parsed.path == "/report" and report_path.exists():
            self.send_bytes(report_path.read_bytes())
            return
        if parsed.path == "/api/status":
            self.send_bytes(json.dumps(RUN_STATE).encode("utf-8"), "application/json; charset=utf-8")
            return
        self.send_bytes(page().encode("utf-8"))

    def resolve_site_file(self, path_text):
        if path_text in {"/site", "/site/", "/latest", "/latest.html"}:
            relative = "index.html"
        elif path_text.startswith("/site/"):
            relative = urllib.parse.unquote(path_text[len("/site/"):])
        else:
            return None
        target = (SITE_DIR / relative).resolve()
        try:
            target.relative_to(SITE_DIR.resolve())
        except ValueError:
            return None
        if target.is_dir():
            target = target / "index.html"
        if target.exists() and target.is_file():
            return target
        return None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        values = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        if not self.authorized(values):
            self.send_bytes(b"Forbidden", "text/plain; charset=utf-8", 403)
            return
        if self.path == "/run":
            if not RUN_STATE["running"]:
                threading.Thread(target=run_update, daemon=True).start()
            token = access_token()
            wait_page = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <title>539 Update Running</title>
  <style>body{{font-family:"Microsoft JhengHei",Arial,sans-serif;background:#f8fafc;color:#0f172a;padding:20px}}.box{{max-width:620px;margin:auto;background:white;border:1px solid #cbd5e1;border-radius:8px;padding:18px}}.big{{font-size:24px;font-weight:900;color:#b91c1c}}</style>
</head>
<body>
  <div class="box">
    <div class="big">&#20027;&#31995;&#32113;&#27491;&#22312;&#21363;&#26178;&#26356;&#26032;</div>
    <p id="status">&#27491;&#22312;&#37325;&#26032;&#25235;&#21462;&#38283;&#29518;&#36039;&#26009;&#12289;&#37325;&#31639;&#27169;&#22411;&#12289;&#37325;&#24314;&#25163;&#27231;&#25136;&#22577;...</p>
    <p>&#23436;&#25104;&#24460;&#26371;&#33258;&#21205;&#36339;&#21040;&#26368;&#26032;&#25136;&#22577;&#12290;</p>
  </div>
  <script>
    async function poll(){{
      try{{
        const r=await fetch("/api/status?token={urllib.parse.quote(token)}&v="+Date.now(),{{cache:"no-store"}});
        const data=await r.json();
        document.getElementById("status").textContent="\\u72c0\\u614b\\uff1a"+data.message+" / running="+data.running;
        if(!data.running){{
          location.replace("/report?token={urllib.parse.quote(token)}&v="+Date.now());
          return;
        }}
      }}catch(e){{}}
      setTimeout(poll,3000);
    }}
    poll();
  </script>
</body>
</html>"""
            self.send_bytes(wait_page.encode("utf-8"))
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
    if "--write-url" in sys.argv:
        payload = write_mobile_entry_files()
        print(payload["report_url"])
        return
    token = access_token()
    address = local_ip()
    write_mobile_entry_files()
    print(f"Mobile control: http://{address}:{PORT}/?token={token}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
