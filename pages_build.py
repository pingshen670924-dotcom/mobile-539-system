import json
import os
import shutil
from pathlib import Path
from datetime import datetime


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
REPORT = REPORTS / "539\u6700\u65b0\u5f37\u5316\u6230\u5831.html"
HISTORY_REPORT = REPORTS / "539\u6bcf\u671f\u9810\u6e2c\u5c0d\u6bd4.html"
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPOSITORY")


def repository_url(path=""):
    return f"https://github.com/{REPOSITORY}/{path}".rstrip("/")


def build():
    SITE.mkdir(parents=True, exist_ok=True)
    html = REPORT.read_text(encoding="utf-8")
    analysis = {}
    analysis_path = REPORTS / "latest_analysis.json"
    if analysis_path.exists():
        try:
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            analysis = {}
    generated_at = analysis.get("generated_at") or datetime.now().isoformat(timespec="seconds")
    mobile_built_at = datetime.now().isoformat(timespec="seconds")
    latest_draw = analysis.get("latest_draw", {})
    version = datetime.now().strftime("%Y%m%d%H%M%S")
    controls = f"""
    <section class="band">
      <h2>\u624b\u6a5f\u7368\u7acb\u64cd\u4f5c</h2>
      <p><strong>\u624b\u6a5f\u7248\u6700\u5f8c\u5efa\u7acb\uff1a{mobile_built_at}</strong></p>
      <p>\u6700\u65b0\u8cc7\u6599\uff1a{latest_draw.get('period', '-')}\u671f / {latest_draw.get('draw_date', '-')} / \u7248\u672c {version}</p>
      <p><a class="mobile-action refresh" href="clear-cache.html?v={version}">\u6e05\u9664\u820a\u7248\u5feb\u53d6\u4e26\u6253\u958b\u6700\u65b0\u624b\u6a5f\u7248</a></p>
      <p><a class="mobile-action history" href="prediction-history.html?v={version}">\u67e5\u770b\u6bcf\u671f\u9810\u6e2c\u5c0d\u6bd4</a></p>
      <p><a class="mobile-action" href="{repository_url('actions/workflows/daily-update.yml')}">\u767b\u5165 GitHub \u5f8c\u7acb\u5373\u66f4\u65b0</a></p>
      <p><button class="mobile-action refresh" type="button" onclick="forceRefresh()">\u5f37\u5236\u91cd\u65b0\u8f09\u5165\u6700\u65b0\u624b\u6a5f\u6210\u679c</button></p>
      <p>\u514d\u8cbb\u624b\u6a5f\u7248\u6703\u81ea\u52d5\u66f4\u65b0\uff1a\u53f0\u5317\u6642\u9593 20:50 \u9810\u5099\u6aa2\u67e5\uff0c21:00-23:50 \u6bcf10\u5206\u9418\u91cd\u8a66\uff0c00:10 \u6700\u5f8c\u6aa2\u67e5\u3002\u624b\u52d5\u7acb\u5373\u66f4\u65b0\u9700\u767b\u5165 GitHub\u3002</p>
      <p>\u624b\u6a5f\u7248\u8207\u96fb\u8166\u7248\u53ef\u540c\u6642\u5b58\u5728\uff1a\u96fb\u8166\u7248\u5728\u672c\u6a5f\u8f38\u51fa\u5b8c\u6574\u6230\u5831\uff0c\u624b\u6a5f\u7248\u5728 GitHub \u96f2\u7aef\u7368\u7acb\u66f4\u65b0\uff0c\u4e92\u4e0d\u8986\u84cb\u3002</p>
    </section>
    """
    style = """
    <style>
      .mobile-action{display:block;text-align:center;padding:14px;background:#166534;color:#fff!important;text-decoration:none;border-radius:6px;font-weight:800}
      .mobile-action.secondary{background:#0f766e}
      .mobile-action.history{background:#1d4ed8}
      .mobile-action.refresh{border:0;width:100%;font-size:16px;cursor:pointer;background:#b91c1c}
      .band{overflow-x:auto}
      table{min-width:720px}
      @media (max-width:640px){
        header{padding:16px}
        header h1{font-size:22px}
        main{padding:10px}
        .band{padding:12px;margin-top:10px}
        .grid{grid-template-columns:1fr}
        .card{padding:12px}
        th,td{padding:8px;font-size:13px;white-space:normal;vertical-align:top}
        .value{font-size:20px}
      }
    </style>
    <link rel="manifest" href="manifest.webmanifest">
    <meta name="theme-color" content="#111827">
    <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    """
    html = html.replace("</head>", style + "</head>")
    html = html.replace("<main>", "<main>" + controls, 1)
    script = f'''
    <script>
      window.MOBILE_BUILD_VERSION="{version}";
      async function forceRefresh(){{
        try{{
          if("serviceWorker" in navigator){{
            const regs=await navigator.serviceWorker.getRegistrations();
            for(const reg of regs) await reg.unregister();
          }}
          if(window.caches){{
            const keys=await caches.keys();
            await Promise.all(keys.map(k=>caches.delete(k)));
          }}
        }}catch(e){{}}
          location.href="index.html?v="+Date.now();
        }}
      async function checkMobileVersion(){{
        try{{
          const r=await fetch("version.json?v="+Date.now(),{{cache:"no-store"}});
          const data=await r.json();
          if(data.version && data.version!==window.MOBILE_BUILD_VERSION){{
            location.href="clear-cache.html?v="+Date.now();
          }}
        }}catch(e){{}}
      }}
      if("serviceWorker" in navigator)navigator.serviceWorker.register("service-worker.js?v={version}");
      setInterval(checkMobileVersion, 120000);
      checkMobileVersion();
    </script>'''
    html = html.replace("</body>", script + "</body>")
    (SITE / "index.html").write_text(html, encoding="utf-8")
    for name in ["latest_analysis.json", "health_status.json", "model_competition.json", "prediction_history.json"]:
        source = REPORTS / name
        if source.exists():
            shutil.copy2(source, SITE / name)
    if HISTORY_REPORT.exists():
        shutil.copy2(HISTORY_REPORT, SITE / "prediction-history.html")
    manifest = {
        "name": "539 \u624b\u6a5f\u7368\u7acb\u7cfb\u7d71",
        "short_name": "539\u7cfb\u7d71",
        "start_url": "./",
        "display": "standalone",
        "background_color": "#f6f7fb",
        "theme_color": "#111827",
        "icons": [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    }
    (SITE / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    version_payload = {
        "version": version,
        "generated_at": generated_at,
        "mobile_built_at": mobile_built_at,
        "latest_period": latest_draw.get("period"),
        "latest_draw_date": latest_draw.get("draw_date"),
        "cache_policy": "network_first_no_store",
    }
    (SITE / "version.json").write_text(json.dumps(version_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>最新手機版</title>
  <script>location.replace("index.html?v={version}&t="+Date.now());</script>
</head>
<body>
  <p>正在打開最新手機版...</p>
  <p><a href="index.html?v={version}">若沒有自動跳轉，請點這裡</a></p>
</body>
</html>
"""
    (SITE / "latest.html").write_text(latest_html, encoding="utf-8")
    (SITE / "clear-cache.html").write_text(
        f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>清除舊版快取</title>
</head>
<body>
  <p>正在清除舊版快取並打開最新手機版...</p>
  <script>
    (async()=>{{
      try{{
        if("serviceWorker" in navigator){{
          const regs=await navigator.serviceWorker.getRegistrations();
          for(const reg of regs) await reg.unregister();
        }}
        if(window.caches){{
          const keys=await caches.keys();
          await Promise.all(keys.map(key=>caches.delete(key)));
        }}
      }}catch(e){{}}
      location.replace("index.html?v={version}&t="+Date.now());
    }})();
  </script>
  <p><a href="index.html?v={version}">若沒有自動跳轉，請點這裡</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )
    latest_entry = ROOT / "\u6253\u958b\u6700\u65b0\u624b\u6a5f\u7248.html"
    latest_entry.write_text(
        f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>打開最新手機版</title>
  <meta http-equiv="refresh" content="0; url=site/clear-cache.html?v={version}">
</head>
<body>
  <p>正在打開最新手機版...</p>
  <p><a href="site/clear-cache.html?v={version}">若沒有自動跳轉，請點這裡</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )
    (SITE / "service-worker.js").write_text(
        f'''const CACHE="539-mobile-{version}";
async function clearAllCaches(){{
  const keys=await caches.keys();
  await Promise.all(keys.map(key=>caches.delete(key)));
}}
self.addEventListener("install",event=>{{self.skipWaiting();event.waitUntil(clearAllCaches());}});
self.addEventListener("activate",event=>{{event.waitUntil(clearAllCaches().then(()=>self.clients.claim()));}});
self.addEventListener("fetch",event=>{{
  const req=event.request;
  if(req.method!=="GET") return;
  event.respondWith(fetch(req,{{cache:"no-store"}}));
}});''',
        encoding="utf-8",
    )
    (SITE / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="72" fill="#111827"/><circle cx="256" cy="256" r="174" fill="#f8fafc"/><text x="256" y="300" text-anchor="middle" font-family="Arial" font-size="150" font-weight="700" fill="#b91c1c">539</text></svg>',
        encoding="utf-8",
    )
    (SITE / ".nojekyll").write_text("", encoding="ascii")


if __name__ == "__main__":
    build()
