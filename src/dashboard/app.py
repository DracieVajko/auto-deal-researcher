"""Web dashboard HTTP server for the Auto Deal Searcher.

Serves search results from the results directory as a simple read-only HTML
dashboard. Uses only the Python standard library (http.server) — no heavy
frameworks.
"""

from __future__ import annotations

import html
import logging
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.dashboard.data import ResultsStore, SearchRun

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8765
DEFAULT_RESULTS_DIR = "results"


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_PAGE_STYLE = """
<style>
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f7; color: #1d1d1f; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; }
  h1 { font-size: 24px; font-weight: 600; margin: 0; letter-spacing: -0.5px; }
  h2 { font-size: 18px; font-weight: 600; margin: 24px 0 12px; }
  .subtitle { color: #86868b; font-size: 14px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 24px; }
  th { text-align: left; padding: 12px 16px; font-weight: 600; font-size: 13px; color: #86868b; text-transform: uppercase; letter-spacing: 0.5px; background: #f9f9f9; }
  td { padding: 12px 16px; font-size: 14px; border-bottom: 1px solid #f2f2f7; }
  tr:last-child td { border-bottom: none; }
  tr:hover { background: #fafafa; }
  .price { font-weight: 600; color: #1d1d1f; }
  .effective { color: #0071e3; font-weight: 600; }
  .score { font-weight: 600; }
  .score.buy { color: #34c759; }
  .score.watch { color: #ff9f0a; }
  .score.skip { color: #ff3b30; }
  .verdict { font-size: 12px; font-weight: 600; padding: 4px 8px; border-radius: 6px; display: inline-block; }
  .verdict.buy { background: #e6f4ea; color: #34c759; }
  .verdict.watch { background: #fdf0e0; color: #ff9f0a; }
  .verdict.skip { background: #fee2e2; color: #ff3b30; }
  .condition { font-size: 12px; color: #86868b; text-transform: uppercase; letter-spacing: 0.5px; }
  .domain { font-size: 12px; color: #86868b; }
  .links a { margin-right: 12px; color: #0071e3; text-decoration: none; font-size: 13px; }
  .links a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; }
  .badge.active { background: #e6f4ea; color: #34c759; }
  .badge.inactive { background: #f2f2f7; color: #86868b; }
  .empty { text-align: center; padding: 60px 24px; color: #86868b; }
  .empty h2 { margin-bottom: 8px; }
  .nav-link { color: #0071e3; text-decoration: none; font-size: 14px; }
  .nav-link:hover { text-decoration: underline; }
  .alert { background: #fdf0e0; border-left: 4px solid #ff9f0a; padding: 12px 16px; margin-bottom: 16px; border-radius: 0 8px 8px 0; }
  .alert-title { font-weight: 600; margin-bottom: 4px; }
  .specs-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
  .spec { background: #f9f9f9; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
  .spec-label { color: #86868b; }
  .spec-value { font-weight: 600; }
  .pros-cons { display: flex; gap: 24px; margin-top: 16px; }
  .pros-cons > div { flex: 1; }
  .pros-cons h4 { font-size: 13px; margin: 0 0 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  .pros-cons .pros h4 { color: #34c759; }
  .pros-cons .cons h4 { color: #ff3b30; }
  .pros-cons ul { margin: 0; padding-left: 18px; color: #1d1d1f; }
  .pros-cons li { margin-bottom: 6px; font-size: 14px; }
  .breadcrumb { color: #86868b; font-size: 13px; margin-bottom: 16px; }
  .breadcrumb a { color: #0071e3; text-decoration: none; }
  .breadcrumb a:hover { text-decoration: underline; }
</style>
"""


def _index_page(runs: list[SearchRun]) -> str:
    rows = ""
    if not runs:
        rows = """
        <tr><td colspan="5" style="text-align:center; padding: 40px; color: #86868b;">
            No search results found. Run a search first with <code>ads run --prompt "..."</code>.
        </td></tr>
        """
    else:
        for r in runs:
            rows += f"""
            <tr>
                <td><a href="/run/{r.timestamp}/{r.slug}">{html.escape(r.prompt[:60])}{'…' if len(r.prompt) > 60 else ''}</a></td>
                <td><span class="condition">{r.timestamp}</span></td>
                <td>{r.deal_count}</td>
                <td>{r.filtered_out_count}</td>
                <td><a href="/run/{r.timestamp}/{r.slug}" class="nav-link">View &rarr;</a></td>
            </tr>
            """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Auto Deal Searcher — Results</title>
{_PAGE_STYLE}
</head>
<body>
<div class="container">
<header>
<h1>Auto Deal Searcher</h1>
<span class="subtitle">Search results dashboard &middot; {len(runs)} run{'s' if len(runs) != 1 else ''}</span>
</header>

<h2>Search runs</h2>
<table>
<thead>
<tr><th>Prompt</th><th>Date</th><th>Deals</th><th>Filtered out</th><th></th></tr>
</thead>
<tbody>{rows}</tbody>
</table>

<p class="subtitle">Tip: click a deal title in a run to see its full details, specs, and price breakdown.</p>
</div>
</body>
</html>"""


def _detail_page(run: SearchRun) -> str:
    deal_rows = ""
    if not run.deals:
        deal_rows = '<tr><td colspan="7" style="text-align:center; padding: 30px; color: #86868b;">No deals found in this run.</td></tr>'
    else:
        for d in run.deals:
            verdict_class = d.verdict if d.verdict in ("buy", "watch", "skip") else "watch"
            deal_rows += f"""
            <tr>
                <td><strong>#{d.rank}</strong></td>
                <td>{html.escape(d.title)}</td>
                <td><span class="condition">{d.condition}</span></td>
                <td><span class="price">{d.effective_price_eur:.2f} €</span><span class="domain" title="Listed {d.price_eur:.2f} EUR"> ({d.price_eur:.2f} € listed)</span></td>
                <td><span class="score {verdict_class}">{d.score:.0f}</span></td>
                <td><span class="verdict {verdict_class}">{d.verdict.title()}</span></td>
                <td><a href="{html.escape(d.url)}" class="nav-link" target="_blank" rel="noopener">Open &rarr;</a></td>
            </tr>
            """

    alert_rows = ""
    if run.price_alerts:
        for a in run.price_alerts:
            alert_rows += f"""
            <div class="alert">
            <div class="alert-title">{html.escape(a.get('title', 'Price alert'))}</div>
            <div>{html.escape(a.get('message', ''))}</div>
            </div>
            """

    deal_details = ""
    for d in run.deals[:5]:
        deal_details += f"""
        <div class="specs-row">
        <div class="spec"><span class="spec-label">Site</span><span class="spec-value">{html.escape(d.site_name)}</span></div>
        <div class="spec"><span class="spec-label">Price</span><span class="spec-value">{d.effective_price_eur:.2f} €</span></div>
        <div class="spec"><span class="spec-label">Score</span><span class="spec-value">{d.score:.0f}/100</span></div>
        <div class="spec"><span class="spec-label">Condition</span><span class="spec-value">{d.condition}</span></div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Auto Deal Searcher — {html.escape(run.prompt[:50])}</title>
{_PAGE_STYLE}
</head>
<body>
<div class="container">
<div class="breadcrumb"><a href="/" class="nav-link">&larr; Back to results</a> &middot; {html.escape(run.prompt)}</div>

<h2>{html.escape(run.prompt)}</h2>
<p class="subtitle">{run.deal_count} deal{'s' if run.deal_count != 1 else ''} found &middot; {run.filtered_out_count} filtered out &middot; {run.site_count} site{'s' if run.site_count != 1 else ''} searched &middot; {run.timestamp}</p>

{alert_rows if alert_rows else ''}

<h2>Deals</h2>
<table>
<thead>
<tr><th>#</th><th>Title</th><th>Condition</th><th>Price</th><th>Score</th><th>Verdict</th><th>Link</th></tr>
</thead>
<tbody>{deal_rows}</tbody>
</table>

<h2>Details</h2>
{deal_details}

<p class="subtitle">Generated {run.generated_at}. View source: <a href="{html.escape(str(run.path))}" class="nav-link">{run.path.name}</a></p>
</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    server_version = "AutoDealSearcher/1.0"

    def __init__(self, *args, store: ResultsStore, **kwargs):
        self.store = store
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send_html(self, html_str: str, status: int = 200):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            runs = self.store.list_runs()
            self._send_html(_index_page(runs))
            return

        if path.startswith("/run/"):
            parts = path.split("/")
            if len(parts) >= 4:
                timestamp = parts[2]
                slug = parts[3]
                run = self.store.get_run(timestamp, slug)
                if run is not None:
                    self._send_html(_detail_page(run))
                    return
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not found")


def run_server(port: int = DEFAULT_PORT, results_dir: str = DEFAULT_RESULTS_DIR):
    """Start the dashboard HTTP server on *port* serving *results_dir*."""
    store = ResultsStore(results_dir)

    def handler(*args, **kwargs):
        Handler(*args, store=store, **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    logger.info("Dashboard server listening on http://127.0.0.1:%d (results: %s)", port, results_dir)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Dashboard server stopped")
    finally:
        server.server_close()
