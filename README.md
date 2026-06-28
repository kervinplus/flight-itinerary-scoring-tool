# Flight Itinerary Scoring Tool

A reusable command-line tool that turns a plain-text **trip brief** into a ranked
flight itinerary. It parses the brief, pulls real flights from Google Flights
(via SerpAPI), eliminates options that break hard constraints, and scores the
survivors with a configurable, weighted engine — then prints a clear recommendation
with a runner-up and the reasoning behind it.

```bash
py main.py flight_brief.txt
```

The whole tool runs at **$0**: free-tier SerpAPI + Python + regex parsing.

---

## Why it's built this way

- **Paste a brief, get an answer.** The tool reads a `.txt` brief, so anyone can drop
  in a new trip (different routes, dates, constraints) and run it — no code changes.
- **Real scoring, not vibes.** A two-layer engine separates *must-haves* (hard
  constraints that eliminate) from *preferences* (soft weighted scoring).
- **Tunable, not hard-coded.** Every weight and threshold lives in `config.py`.
  Change a number, re-run — the logic never moves.
- **Considers alternates.** When the brief allows alternate airports (e.g. JFK / LGA /
  EWR), the tool searches each one and picks the best across all of them.
- **Cheap to iterate.** API responses are cached locally, so tuning the scoring
  costs zero extra calls. It also falls back to realistic sample data, so it runs
  even without an API key.

---

## Architecture

```
flight_tool/
├── main.py            # Orchestrator: parse -> fetch -> filter -> score -> report
├── brief_parser.py    # Regex parser: .txt brief -> structured JSON ($0, no API)
├── config.py          # Scoring weights, thresholds, airport metadata (tune here)
├── api.py             # SerpAPI calls + local JSON cache + sample-data fallback
├── scoring.py         # Scoring engine: hard constraints + soft weighted scoring
├── flight_brief.txt   # Input brief
├── cache/             # Cached API responses (cache/leg1.json, leg2.json, ...)
├── .env.example       # Copy to .env and add your SerpAPI key
└── requirements.txt
```

**Flow**

```
python main.py flight_brief.txt
        │
        ▼  brief_parser.py — regex → {legs, dates, hard_constraints, preferences}
        ▼  api.py — SerpAPI (1+ calls per leg, alternates included) → cache/legN.json
        ▼  scoring.py — eliminate hard violations → score survivors → rank
        ▼  main.py — formatted recommendation + runner-up + tradeoffs
```

---

## Scoring engine

### Layer 1 — Hard constraints (eliminate if violated)
Driven entirely by the parsed brief, e.g.:
- Arrive by a deadline (`arrival_before`)
- Depart after a time / arrive same day (`departure_after`, `arrive_same_day`)
- Layovers within `[min, max]` minutes
- No basic economy

### Layer 2 — Soft scoring (0–1, higher is better)
Each surviving flight is scored on a weighted blend. Defaults (configurable in
`config.py`, sum to 1.0):

| Factor | Weight | Logic |
|---|---|---|
| Price | 35% | Cheaper is better (min-max normalized within the leg) |
| Travel time | 25% | Faster is better (normalized within the leg) |
| Red-eye | 15% | Full credit if **not** a red-eye |
| Nonstop | 10% | Nonstop, or a connection that saves more than the threshold |
| Airline | 5% | United / Star Alliance loyalty bonus |
| Early departure | 5% | Penalize departures before 7am (half-penalty 7–8am) |
| Timing | 5% | Schedule margin (earlier arrival / earlier departure) |

The report surfaces tradeoffs explicitly (e.g. *"Leg 1 departs before 7am — took the
early-departure penalty, but still won on price + travel time"*) instead of hiding them.

---

## Setup & usage

1. **Python 3.10+.** On Windows, run with the `py` launcher.
2. **(Optional) live data** — for real flights, install `requests` and add a key:
   ```bash
   py -m pip install requests
   cp .env.example .env          # then paste your SerpAPI key into .env
   ```
   Get a free key (100 searches/month, no card) at https://serpapi.com.
3. **Run:**
   ```bash
   py main.py flight_brief.txt
   ```

**No API key? It still runs** on built-in sample data. To force fresh live data,
delete the cache first: `rm cache/*.json`.

---

## Reusability

To score a different trip, edit `flight_brief.txt` (or pass another file:
`py main.py my_other_brief.txt`). The parser extracts legs, dates, constraints, and
preferences automatically — no code changes needed.
