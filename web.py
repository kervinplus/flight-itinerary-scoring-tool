"""
web.py — Localhost web UI for the flight scoring tool.

Same engine as the CLI (scoring.py / config.py / api.py) — this only adds an HTML
presentation layer. Edit the brief in the browser and re-score live.

    py web.py            # serve at http://127.0.0.1:5000
    py web.py --selftest # render once headless and print status (no server)
"""

import html
import sys

try:
    from flask import Flask, request
except ImportError:
    sys.exit("Flask is required for the web UI. Run:  py -m pip install flask")

import api
import brief_parser
import config
import main as cli   # reuse fmt_time / fmt_dur / fmt_date / stops_label / runner-up / tradeoffs
import scoring

app = Flask(__name__)

BRIEF_FILE = "flight_brief.txt"


def _load_default_brief() -> str:
    try:
        with open(BRIEF_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def gather(brief: dict) -> list:
    """parse -> fetch -> score, per leg (same flow as the CLI)."""
    results = []
    for leg in brief["legs"]:
        options, source = api.get_flights(leg)
        ranked, eliminated = scoring.evaluate_leg(leg, options, brief["preferences"])
        results.append({"leg": leg, "ranked": ranked,
                        "eliminated": eliminated, "source": source})
    return results


def _leg_card(leg: dict, entry: dict) -> str:
    o = entry["option"]
    fs, ls = scoring.first_seg(o), scoring.last_seg(o)
    dep_id = fs["departure_airport"]["id"]
    arr_id = ls["arrival_airport"]["id"]
    tags = ""
    if scoring.is_red_eye(o):
        tags += '<span class="tag red">RED-EYE</span>'
    if scoring.is_star_alliance(o):
        tags += '<span class="tag ua">United/Star</span>'
    if scoring.num_stops(o) == 0:
        tags += '<span class="tag ok">Nonstop</span>'
    return f"""
      <div class="card">
        <div class="legno">LEG {leg['leg_number']} · {cli.fmt_date(leg['date'])}</div>
        <div class="route">{dep_id} &rarr; {arr_id}</div>
        <div class="airline">{html.escape(scoring.primary_airline(o))} {html.escape(fs['flight_number'])}</div>
        <div class="times">{cli.fmt_time(fs['departure_airport']['time'], dep_id)}
            &rarr; {cli.fmt_time(ls['arrival_airport']['time'], arr_id)}</div>
        <div class="meta">{cli.stops_label(o)} · {cli.fmt_dur(scoring.duration(o))} · {html.escape(fs['travel_class'])}</div>
        <div class="tags">{tags}</div>
        <div class="bottom"><span class="price">${o['price']}</span>
            <span class="match">match {entry['score']*100:.0f}%</span></div>
      </div>"""


def _infeasible_card(leg: dict, count: int) -> str:
    return f"""
      <div class="card bad">
        <div class="legno">LEG {leg['leg_number']} · {cli.fmt_date(leg['date'])}</div>
        <div class="route">{api._airport(leg['from'])} &rarr; {api._airport(leg['to'])}</div>
        <div class="airline">No feasible option</div>
        <div class="meta">all {count} flights broke a hard constraint</div>
      </div>"""


def render(brief_text: str, brief: dict, results: list) -> str:
    prefs = brief["preferences"]
    legs = brief["legs"]
    feasible = all(r["ranked"] for r in results)

    route = " &rarr; ".join(
        [api._airport(legs[0]["from"])] + [api._airport(l["to"]) for l in legs]
    ) if legs else "?"
    span = (f"{cli.fmt_date(legs[0]['date'])} &ndash; {cli.fmt_date(legs[-1]['date'])}"
            if legs else "")
    source = results[0]["source"] if results else "n/a"

    cards, total_price, total_time = [], 0, 0
    for r in results:
        if r["ranked"]:
            best = r["ranked"][0]
            total_price += best["option"]["price"]
            total_time += scoring.duration(best["option"])
            cards.append(_leg_card(r["leg"], best))
        else:
            cards.append(_infeasible_card(r["leg"], len(r["eliminated"])))

    budget = prefs["budget_total"]
    delta = budget - total_price
    badge = (f'<span class="badge good">${delta:,} under ${budget:,}</span>'
             if delta >= 0 else f'<span class="badge over">${-delta:,} over ${budget:,}</span>')

    runner = "\n".join(cli._runner_up(results, total_price, total_time)) if feasible else \
        "No complete itinerary."
    tradeoffs = "\n".join(cli._tradeoffs(results, prefs))
    w = config.WEIGHTS
    weights = (f"Price {w['price']:.0%} · Time {w['travel_time']:.0%} · "
               f"Red-eye {w['redeye']:.0%} · Nonstop {w['nonstop']:.0%} · "
               f"United {w['airline']:.0%} · Early {w['early_departure']:.0%} · "
               f"Timing {w['timing']:.0%}")

    summary = (f'<div class="summary"><b>${total_price:,}</b> total · '
               f'{cli.fmt_dur(total_time)} travel · {badge}</div>') if feasible else ""

    return PAGE.format(
        route=route, span=span, source=source,
        brief=html.escape(brief_text),
        cards="".join(cards), summary=summary,
        runner=html.escape(runner), tradeoffs=html.escape(tradeoffs), weights=weights,
    )


@app.route("/", methods=["GET", "POST"])
def index():
    brief_text = request.form.get("brief") if request.method == "POST" else _load_default_brief()
    brief = brief_parser.parse_text(brief_text)
    results = gather(brief)
    return render(brief_text, brief, results)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flight Itinerary Scoring Tool</title>
<style>
  :root {{ --bg:#0f1320; --card:#1a2032; --ink:#e8ecf6; --mut:#9aa6c0; --acc:#5b8cff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:28px 20px 60px; }}
  h1 {{ font-size:22px; margin:0 0 2px; }}
  .sub {{ color:var(--mut); margin-bottom:20px; }}
  .src {{ font-size:12px; color:var(--mut); border:1px solid #2a3350; border-radius:20px;
    padding:2px 10px; }}
  form {{ margin:0 0 24px; }}
  textarea {{ width:100%; height:170px; background:#0c0f1a; color:var(--ink);
    border:1px solid #2a3350; border-radius:10px; padding:12px; font-family:ui-monospace,
    Consolas,monospace; font-size:13px; resize:vertical; }}
  button {{ margin-top:10px; background:var(--acc); color:#fff; border:0; border-radius:8px;
    padding:10px 18px; font-size:14px; font-weight:600; cursor:pointer; }}
  .summary {{ font-size:18px; margin:8px 0 18px; }}
  .badge {{ font-size:13px; padding:3px 10px; border-radius:20px; margin-left:8px; }}
  .good {{ background:#13351f; color:#7be0a0; }}
  .over {{ background:#3a1620; color:#ff8aa0; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; }}
  .card {{ background:var(--card); border:1px solid #2a3350; border-radius:12px; padding:16px; }}
  .card.bad {{ border-color:#5a2030; }}
  .legno {{ font-size:12px; color:var(--mut); letter-spacing:.04em; }}
  .route {{ font-size:20px; font-weight:700; margin:4px 0; }}
  .airline {{ font-weight:600; }}
  .times {{ color:var(--ink); margin:4px 0; }}
  .meta {{ color:var(--mut); font-size:13px; }}
  .tags {{ margin:8px 0 4px; min-height:22px; }}
  .tag {{ font-size:11px; padding:2px 8px; border-radius:20px; margin-right:5px; }}
  .tag.red {{ background:#3a1620; color:#ff8aa0; }}
  .tag.ua {{ background:#1d2c4d; color:#9bbcff; }}
  .tag.ok {{ background:#13351f; color:#7be0a0; }}
  .bottom {{ display:flex; justify-content:space-between; align-items:baseline; margin-top:6px; }}
  .price {{ font-size:22px; font-weight:700; }}
  .match {{ font-size:12px; color:var(--mut); }}
  h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:.06em; color:var(--mut);
    margin:28px 0 8px; }}
  pre {{ background:#0c0f1a; border:1px solid #2a3350; border-radius:10px; padding:14px;
    white-space:pre-wrap; font-family:ui-monospace,Consolas,monospace; font-size:13px;
    color:#cdd6ee; }}
  .weights {{ color:var(--mut); font-size:13px; }}
</style></head>
<body><div class="wrap">
  <h1>Flight Itinerary Scoring Tool</h1>
  <div class="sub">{route} · {span} &nbsp; <span class="src">data: {source}</span></div>

  <form method="post">
    <textarea name="brief" spellcheck="false">{brief}</textarea>
    <button type="submit">Score itinerary</button>
  </form>

  {summary}
  <div class="cards">{cards}</div>

  <h2>Runner-up</h2><pre>{runner}</pre>
  <h2>Constraints &amp; tradeoffs</h2><pre>{tradeoffs}</pre>
  <h2>Scoring weights</h2><div class="weights">{weights}</div>
</div></body></html>"""


def _free_port(start=5000, end=5050):
    """Find a port nothing is listening on (avoids 'address in use' / blocked 5000)."""
    import socket
    for p in range(start, end):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        with app.test_client() as c:
            resp = c.get("/")
            print(f"selftest: HTTP {resp.status_code}, {len(resp.data)} bytes")
            sys.exit(0 if resp.status_code == 200 else 1)

    import threading
    import webbrowser

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 50)
    print(f"  Flight tool running at:  {url}")
    print("  Opening your browser... (Ctrl+C here to stop)")
    print("=" * 50)
    # open the browser a moment after the server starts listening
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
