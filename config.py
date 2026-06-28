"""
config.py — Defaults, scoring weights, and airport metadata.

Everything tunable lives here. Change a weight or a threshold and the rest of the
tool picks it up; the scoring logic in scoring.py never hard-codes a number.
"""

# --- Scoring weights. MUST sum to 1.0. Tune here without touching the engine. ---
WEIGHTS = {
    "price": 0.35,            # cheaper is better (normalized within each leg)
    "travel_time": 0.25,     # faster is better (normalized within each leg)
    "redeye": 0.15,          # full credit if NOT a red-eye
    "nonstop": 0.10,         # nonstop, or a connection that saves > threshold
    "airline": 0.05,         # United / Star Alliance loyalty bonus
    "early_departure": 0.05, # penalize departures before 7am
    "timing": 0.05,          # schedule margin (earlier arrival / earlier departure)
}

# --- Default preferences. The brief parser overrides whatever it can extract. ---
DEFAULT_PREFERENCES = {
    "budget_total": 1500,
    "premium_for_no_redeye": 400,
    "premium_for_time_savings": {"amount": 400, "min_hours_saved": 3},
    "nonstop_preferred": True,
    "connection_ok_if_saves": 250,
    "layover_min_minutes": 45,
    "layover_max_minutes": 150,
    "preferred_airlines": ["UA"],
    "no_basic_economy": True,
    "bags": "carry_on_only",
    "seat_preference": "aisle",
    "no_departure_before": "07:00",
}

# Airlines that earn the loyalty bonus (United + Star Alliance partners).
STAR_ALLIANCE = {
    "United", "Lufthansa", "Air Canada", "Avianca", "Copa Airlines",
    "Brussels Airlines", "EVA Air", "Air New Zealand", "ANA", "Asiana Airlines",
    "Austrian", "SWISS", "TAP Air Portugal", "Turkish Airlines",
    "Singapore Airlines", "Thai Airways", "SAS", "LOT Polish Airlines",
}

PREFERRED_AIRLINE_CODES = {"UA"}

# City/metro codes that should expand to the actual airports the brief allows.
METRO_CODES = {
    "NYC": ["JFK", "LGA", "EWR"],
}

# Timezone label per airport — used for display and red-eye / constraint reasoning.
AIRPORT_TZ = {
    "SFO": "PT", "OAK": "PT", "SJC": "PT",
    "BOS": "ET", "JFK": "ET", "LGA": "ET", "EWR": "ET", "DCA": "ET",
    "ORD": "CT", "DFW": "CT",
}

SERPAPI_ENDPOINT = "https://serpapi.com/search"
CACHE_DIR = "cache"


def airport_tz(code: str) -> str:
    """Return the timezone label for an airport code (defaults to ET)."""
    return AIRPORT_TZ.get(code, "ET")
