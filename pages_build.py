import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
REPORT = REPORTS / "539\u6700\u65b0\u5f37\u5316\u6230\u5831.html"
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPOSITORY")


def repository_url(path=""):
    return f"https://github.com/{REPOSITORY}/{path}".rstrip("/")


def build():
    SITE.mkdir(parents=True, exist_ok=True)
    html = REPORT.read_text(encoding="utf-8")
    controls = f"""
    <section class="band">
      <h2>\u624b\u6a5f\u7368\u7acb\u64cd\u4f5c</h2>
      <p><a class="mobile-action" href="{repository_url('actions/workflows/daily-update.yml')}">\u7acb\u5373\u66f4\u65b0\u8207\u91cd\u65b0\u904b\u7b97</a></p>
      <p><a class="mobile-action secondary" href="{repository_url('issues/new?template=crowd-numbers.yml')}">\u63d0\u4ea4 Facebook / \u793e\u5718\u4eba\u6c23\u865f\u78bc</a></p>
      <p>\u6bcf\u65e5\u53f0\u5317\u6642\u9593 21:10\u300121:40\u300122:10 \u81ea\u52d5\u5617\u8a66\u66f4\u65b0\u3002\u7db2\u8def\u4eba\u6c23\u672a\u901a\u904e100\u671f\u56de\u6e2c\u524d\u6b0a\u91cd\u70ba0\u3002</p>
    </section>
    """
    style = """
    <style>
      .mobile-action{display:block;text-align:center;padding:14px;background:#166534;color:#fff!important;text-decoration:none;border-radius:6px;font-weight:800}
      .mobile-action.secondary{background:#0f766e}
    </style>
    <link rel="manifest" href="manifest.webmanifest">
    <meta name="theme-color" content="#111827">
    """
    html = html.replace("</head>", style + "</head>")
    html = html.replace("<main>", "<main>" + controls, 1)
    html = html.replace("</body>", '<script>if("serviceWorker" in navigator)navigator.serviceWorker.register("service-worker.js");</script></body>')
    (SITE / "index.html").write_text(html, encoding="utf-8")
    for name in ["latest_analysis.json", "crowd_consensus.json", "health_status.json", "model_competition.json"]:
        source = REPORTS / name
        if source.exists():
            shutil.copy2(source, SITE / name)
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
    (SITE / "service-worker.js").write_text(
        'const CACHE="539-v1";self.addEventListener("install",e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(["./","index.html"]))));self.addEventListener("fetch",e=>e.respondWith(fetch(e.request).catch(()=>caches.match(e.request))));',
        encoding="utf-8",
    )
    (SITE / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="72" fill="#111827"/><circle cx="256" cy="256" r="174" fill="#f8fafc"/><text x="256" y="300" text-anchor="middle" font-family="Arial" font-size="150" font-weight="700" fill="#b91c1c">539</text></svg>',
        encoding="utf-8",
    )
    (SITE / ".nojekyll").write_text("", encoding="ascii")


if __name__ == "__main__":
    build()
