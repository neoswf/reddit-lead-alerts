"""A small results page, served only on this computer (127.0.0.1)."""
import html
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from .store import STATUSES

CSS = """
:root { --bg:#f6f6f3; --surface:#fff; --text:#1c1c1a; --muted:#6a6a64; --line:#e3e3dd;
        --accent:#2d5c4f; --new:#a8521c; --chip:#eeeee8; --warn:#8a2d1c; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151514; --surface:#1e1e1c; --text:#ebebe8; --muted:#9b9b94; --line:#33332f;
          --accent:#86bfad; --new:#e39a63; --chip:#2a2a27; --warn:#e48a74; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width:860px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:22px; margin:0; }
h2 { font-size:15px; margin:32px 0 8px; color:var(--muted); font-weight:600; }
header { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; }
.state { font-size:13px; color:var(--muted); }
.state b { color:var(--warn); }
nav { display:flex; flex-wrap:wrap; gap:6px; margin:20px 0 12px; }
nav a { padding:5px 12px; border-radius:999px; background:var(--chip); color:var(--text);
        text-decoration:none; font-size:13px; }
nav a.on { background:var(--accent); color:var(--surface); }
article { background:var(--surface); border:1px solid var(--line); border-radius:10px;
          padding:14px 16px; margin-bottom:10px; }
.meta { font-size:12.5px; color:var(--muted); }
.meta .status-new { color:var(--new); font-weight:600; }
article h3 { font-size:16px; margin:4px 0 6px; overflow-wrap:anywhere; }
article h3 a { color:var(--text); }
.excerpt { margin:0 0 6px; color:var(--text); overflow-wrap:anywhere; }
.why { font-size:13px; color:var(--muted); margin:0 0 10px; }
form { display:inline; }
button { font:inherit; font-size:13px; padding:4px 12px; border-radius:6px; cursor:pointer;
         border:1px solid var(--line); background:var(--chip); color:var(--text); }
button.primary { background:var(--accent); color:var(--surface); border-color:var(--accent); }
.empty { color:var(--muted); padding:24px 0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
td, th { text-align:left; padding:6px 8px 6px 0; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:500; }
.err { color:var(--warn); white-space:pre-wrap; }
.scroll { overflow-x:auto; }
"""


def _local(ts: str | None) -> str:
    return datetime.fromisoformat(ts).astimezone().strftime("%d %b %H:%M") if ts else ""


def _button(label, action, fields, back, primary=False):
    hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(str(v))}">' for k, v in fields.items())
    cls = ' class="primary"' if primary else ""
    return (f'<form method="post" action="{action}">{hidden}'
            f'<input type="hidden" name="back" value="{html.escape(back)}">'
            f"<button{cls}>{label}</button></form>")


def render(store, status: str, client: str | None, back: str) -> str:
    e = html.escape
    paused = store.is_paused()
    counts = store.status_counts()
    tabs = []
    for s in STATUSES + ("all",):
        query = urlencode({k: v for k, v in (("status", s), ("client", client)) if v})
        n = sum(counts.values()) if s == "all" else counts[s]
        cls = ' class="on"' if s == status else ""
        tabs.append(f'<a{cls} href="/?{query}">{s.capitalize()} ({n})</a>')

    cards = []
    for m in store.list_matches(status, client):
        buttons = " ".join(
            _button(label, "/status", {"id": m["id"], "status": s}, back, primary=(s == "reviewed"))
            for s, label in (("reviewed", "Reviewed"), ("ignored", "Not relevant"), ("new", "Back to new"))
            if s != m["status"]
        )
        cards.append(f"""<article>
  <div class="meta">{e(m['client_name'])} · {e(m['community'])} · posted {_local(m['published'])}
    · found {_local(m['matched_at'])} · <span class="status-{e(m['status'])}">{e(m['status'])}</span></div>
  <h3><a href="{e(m['url'])}" target="_blank" rel="noopener noreferrer">{e(m['title'])}</a></h3>
  <p class="excerpt">{e(m['excerpt'])}</p>
  <p class="why">Why: {e(m['reason'])}</p>
  {buttons}
</article>""")

    runs = "".join(
        f"<tr><td>{_local(r['started'])}</td><td>{e(r['client'])}</td><td>{r['fetched']}</td>"
        f"<td>{r['new_items']}</td><td>{r['matches']}</td><td>{r['alerts_sent']}</td>"
        f"<td class='err'>{e(r['errors'] or '')}</td></tr>"
        for r in store.recent_runs(15)
    )
    pause_ctl = (_button("Resume monitoring", "/resume", {}, back, primary=True) if paused
                 else _button("Pause monitoring", "/pause", {}, back))
    state = "<b>Paused.</b> No checks will run." if paused else "Running on schedule."

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Lead monitor</title>
<style>{CSS}</style></head><body><main>
<header><div><h1>Lead monitor</h1><div class="state">{state}</div></div>{pause_ctl}</header>
<nav>{''.join(tabs)}</nav>
{''.join(cards) or '<p class="empty">Nothing here yet.</p>'}
<h2>Recent checks</h2>
<div class="scroll"><table><tr><th>When</th><th>Client</th><th>Posts read</th><th>New</th><th>Matches</th>
<th>Alerts</th><th>Problems</th></tr>{runs or '<tr><td colspan="7">No checks yet.</td></tr>'}</table></div>
</main></body></html>"""


def serve(store, port: int = 8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, content_type="text/plain; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path != "/":
                return self._send(404, "Not found")
            query = parse_qs(url.query)
            status = query.get("status", ["new"])[0]
            client = query.get("client", [""])[0] or None
            self._send(200, render(store, status, client, self.path), "text/html; charset=utf-8")

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            back = form.get("back", ["/"])[0]
            back = back if back.startswith("/") and not back.startswith("//") else "/"
            path = urlparse(self.path).path
            try:
                if path == "/status":
                    store.set_status(int(form["id"][0]), form["status"][0])
                elif path == "/pause":
                    store.set_paused(None, True)
                elif path == "/resume":
                    store.set_paused(None, False)
                else:
                    return self._send(404, "Not found")
            except (KeyError, ValueError) as e:
                return self._send(400, f"Bad request: {e}")
            self.send_response(303)
            self.send_header("Location", back)
            self.end_headers()

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Dashboard: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
