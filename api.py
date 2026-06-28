"""
api.py — Fetch flights from SerpAPI (Google Flights), with a local JSON cache
and a realistic sample-data fallback.

Order of precedence per leg:
  1. cache/legN.json  (so you can iterate on scoring for free)
  2. live SerpAPI call (only if SERPAPI_KEY is set and no cache exists)
  3. built-in SAMPLE data (so the tool always runs — great for the Loom demo)

Every option returned is in SerpAPI's native shape:
  {"flights": [<segment>, ...], "total_duration": int, "price": int, "type": str}
so the scoring engine doesn't care where the data came from.
"""

import json
import os

try:
    import requests
except ImportError:  # requests is optional — sample/cache paths don't need it
    requests = None

import config


def _load_dotenv():
    """Minimal .env loader (no dependency). Reads KEY=VALUE lines from a .env
    file next to this script and sets any var not already in the environment."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()  # load .env as soon as this module is imported


def _airport(value):
    """A leg endpoint may be a string or a list of alternates — pick the first."""
    return value[0] if isinstance(value, list) else value


def _airport_list(value):
    """Normalize a leg endpoint to a list (single airport -> 1-element list)."""
    return list(value) if isinstance(value, list) else [value]


def _cache_path(leg_number: int) -> str:
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, f"leg{leg_number}.json")


def _flatten(payload: dict):
    """Merge SerpAPI 'best_flights' + 'other_flights' into one list of options."""
    return list(payload.get("best_flights", [])) + list(payload.get("other_flights", []))


def _fetch_serpapi(dep_id: str, arr_id: str, date: str, api_key: str) -> dict:
    if requests is None:
        raise RuntimeError("The 'requests' package is required for live API calls. "
                           "Run: py -m pip install requests")
    params = {
        "engine": "google_flights",
        "departure_id": dep_id,
        "arrival_id": arr_id,
        "outbound_date": date,
        "type": "2",          # one-way
        "currency": "USD",
        "hl": "en",
        "adults": "1",
        "api_key": api_key,
    }
    resp = requests.get(config.SERPAPI_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_flights(leg: dict) -> tuple[list, str]:
    """
    Return (options, source) for a leg.
    source is one of: 'cache', 'serpapi', 'sample'.
    """
    leg_no = leg["leg_number"]
    cache_file = _cache_path(leg_no)

    # 1. Cache
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return _flatten(json.load(f)), "cache"

    # 2. Live API — one search per (origin, destination) pair so alternate
    #    airports (e.g. JFK/LGA/EWR) are all considered, not just the primary.
    api_key = os.environ.get("SERPAPI_KEY")
    if api_key and requests is not None:
        combos = [(f, t) for f in _airport_list(leg["from"])
                  for t in _airport_list(leg["to"])]
        try:
            merged = []
            for dep_id, arr_id in combos:
                payload = _fetch_serpapi(dep_id, arr_id, leg["date"], api_key)
                merged.extend(_flatten(payload))
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"best_flights": merged, "other_flights": []}, f, indent=2)
            if len(combos) > 1:
                pairs = ", ".join(f"{f}->{t}" for f, t in combos)
                print(f"  [api] Leg {leg_no}: searched {len(combos)} airport pairs ({pairs})")
            return merged, "serpapi"
        except Exception as exc:  # network/quota/whatever — fall back gracefully
            print(f"  [api] live call failed ({exc}); using sample data.")

    # 3. Sample fallback (also cached so re-runs are deterministic)
    payload = SAMPLE.get(leg_no, {"best_flights": [], "other_flights": []})
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return _flatten(payload), "sample"


def _seg(dep_id, dep_time, arr_id, arr_time, duration, airline, number,
         travel_class="Economy", legroom="31 in", extensions=None):
    return {
        "departure_airport": {"id": dep_id, "time": dep_time},
        "arrival_airport": {"id": arr_id, "time": arr_time},
        "duration": duration,
        "airline": airline,
        "flight_number": number,
        "travel_class": travel_class,
        "legroom": legroom,
        "extensions": extensions or ["Carry-on included", "Wi-Fi for a fee"],
    }


# --- Realistic sample data (prices researched on Google Flights for these routes). ---
SAMPLE = {
    1: {  # SFO -> BOS, Mon Jul 13 2026, must land by 5:00pm ET
        "best_flights": [
            {"flights": [_seg("SFO", "2026-07-13 07:15", "BOS", "2026-07-13 15:45",
                              330, "United", "UA 1234")],
             "total_duration": 330, "price": 289, "type": "One way"},
            {"flights": [_seg("SFO", "2026-07-13 06:00", "BOS", "2026-07-13 14:30",
                              330, "JetBlue", "B6 680")],
             "total_duration": 330, "price": 245, "type": "One way"},
        ],
        "other_flights": [
            {"flights": [_seg("SFO", "2026-07-13 09:10", "BOS", "2026-07-13 17:40",
                              330, "Delta", "DL 410")],
             "total_duration": 330, "price": 268, "type": "One way"},
            {"flights": [
                _seg("SFO", "2026-07-13 06:30", "ORD", "2026-07-13 12:30", 240, "American", "AA 200"),
                _seg("ORD", "2026-07-13 13:30", "BOS", "2026-07-13 16:50", 140, "American", "AA 318"),
             ],
             "layovers": [{"duration": 60, "name": "Chicago O'Hare", "id": "ORD"}],
             "total_duration": 380, "price": 215, "type": "One way"},
        ],
    },
    2: {  # BOS -> NYC (JFK/LGA/EWR), Wed Jul 15 2026, depart after 3:00pm, same day
        "best_flights": [
            {"flights": [_seg("BOS", "2026-07-15 16:00", "JFK", "2026-07-15 17:20",
                              80, "JetBlue", "B6 1205")],
             "total_duration": 80, "price": 89, "type": "One way"},
            {"flights": [_seg("BOS", "2026-07-15 15:30", "LGA", "2026-07-15 16:55",
                              85, "Delta", "DL 1820")],
             "total_duration": 85, "price": 112, "type": "One way"},
        ],
        "other_flights": [
            {"flights": [_seg("BOS", "2026-07-15 18:00", "EWR", "2026-07-15 19:35",
                              95, "United", "UA 2511")],
             "total_duration": 95, "price": 134, "type": "One way"},
            {"flights": [_seg("BOS", "2026-07-15 14:00", "JFK", "2026-07-15 15:20",
                              80, "American", "AA 4402")],
             "total_duration": 80, "price": 78, "type": "One way"},
            {"flights": [
                _seg("BOS", "2026-07-15 16:30", "DCA", "2026-07-15 18:00", 90, "JetBlue", "B6 614"),
                _seg("DCA", "2026-07-15 18:50", "EWR", "2026-07-15 21:30", 75, "JetBlue", "B6 920"),
             ],
             "layovers": [{"duration": 50, "name": "Washington Reagan", "id": "DCA"}],
             "total_duration": 300, "price": 75, "type": "One way"},
        ],
    },
    3: {  # NYC (JFK/LGA/EWR) -> SFO, Fri Jul 17 2026, land before midnight PT, no red-eye
        "best_flights": [
            {"flights": [_seg("JFK", "2026-07-17 08:00", "SFO", "2026-07-17 11:30",
                              390, "United", "UA 525")],
             "total_duration": 390, "price": 349, "type": "One way"},
            {"flights": [_seg("JFK", "2026-07-17 17:00", "SFO", "2026-07-17 20:45",
                              405, "Delta", "DL 711")],
             "total_duration": 405, "price": 312, "type": "One way"},
        ],
        "other_flights": [
            {"flights": [_seg("JFK", "2026-07-17 21:30", "SFO", "2026-07-18 01:15",
                              405, "JetBlue", "B6 915",
                              extensions=["Overnight flight", "Carry-on included"])],
             "total_duration": 405, "price": 279, "type": "One way"},
            {"flights": [_seg("EWR", "2026-07-17 10:00", "SFO", "2026-07-17 13:20",
                              380, "United", "UA 1701")],
             "total_duration": 380, "price": 389, "type": "One way"},
            {"flights": [
                _seg("LGA", "2026-07-17 12:00", "DFW", "2026-07-17 15:00", 240, "American", "AA 1180"),
                _seg("DFW", "2026-07-17 16:30", "SFO", "2026-07-17 19:30", 240, "American", "AA 660"),
             ],
             "layovers": [{"duration": 90, "name": "Dallas/Fort Worth", "id": "DFW"}],
             "total_duration": 510, "price": 265, "type": "One way"},
        ],
    },
}
