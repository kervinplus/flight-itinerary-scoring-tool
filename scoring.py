"""
scoring.py — The reusable scoring engine.

Two layers, exactly as the brief specifies:
  Layer 1 (hard constraints): eliminate any flight that breaks a must-have rule.
  Layer 2 (soft scoring): score survivors 0..1 on a weighted blend of factors.

Nothing here is route-specific. Feed it a different parsed brief and it works,
because every rule and weight comes from the parsed constraints + config.WEIGHTS.

Public entry point:  evaluate_leg(leg, options, prefs) -> (ranked, eliminated)
"""

from datetime import datetime, timedelta

import config


# ---------- segment / option helpers ----------

def parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def first_seg(option):
    return option["flights"][0]


def last_seg(option):
    return option["flights"][-1]


def dep_dt(option):
    return parse_dt(first_seg(option)["departure_airport"]["time"])


def arr_dt(option):
    return parse_dt(last_seg(option)["arrival_airport"]["time"])


def num_stops(option):
    return len(option["flights"]) - 1


def price(option):
    return option["price"]


def duration(option):
    return option.get("total_duration") or sum(f.get("duration", 0) for f in option["flights"])


def airlines(option):
    return [f.get("airline", "") for f in option["flights"]]


def primary_airline(option):
    return first_seg(option).get("airline", "")


def is_star_alliance(option):
    return any(a in config.STAR_ALLIANCE for a in airlines(option))


def is_red_eye(option):
    """Departs 21:00–05:59 AND lands the next calendar day."""
    d, a = dep_dt(option), arr_dt(option)
    overnight = a.date() > d.date()
    late_or_early = d.hour >= 21 or d.hour < 6
    return overnight and late_or_early


def is_basic_economy(option):
    for f in option["flights"]:
        tc = (f.get("travel_class") or "").lower()
        if "basic" in tc:
            return True
        if any("basic economy" in str(e).lower() for e in f.get("extensions", [])):
            return True
    return False


def layover_minutes(option):
    """List of layover durations (minutes). Uses SerpAPI 'layovers' if present,
    otherwise computes gaps between consecutive segments."""
    if "layovers" in option and option["layovers"]:
        return [lay.get("duration", 0) for lay in option["layovers"]]
    gaps = []
    segs = option["flights"]
    for i in range(len(segs) - 1):
        gap = parse_dt(segs[i + 1]["departure_airport"]["time"]) \
            - parse_dt(segs[i]["arrival_airport"]["time"])
        gaps.append(int(gap.total_seconds() // 60))
    return gaps


# ---------- Layer 1: hard constraints ----------

def _deadline(date_str: str, hhmm: str) -> datetime:
    """Build a deadline datetime. '00:00' means end-of-day (next-day midnight)."""
    base = datetime.strptime(date_str, "%Y-%m-%d")
    h, m = map(int, hhmm.split(":"))
    if h == 0 and m == 0:
        return base + timedelta(days=1)   # before midnight = before next-day 00:00
    return base.replace(hour=h, minute=m)


def hard_violation(option, leg, prefs):
    """Return a human-readable reason string if a hard constraint is broken, else None."""
    # Per-leg constraints from the brief
    for c in leg.get("hard_constraints", []):
        ctype = c["type"]
        if ctype == "arrival_before":
            if not c.get("time"):
                continue  # unparseable time — skip rather than crash
            deadline = _deadline(leg["date"], c["time"])
            if arr_dt(option) > deadline:
                return (f"lands {arr_dt(option):%a %H:%M} "
                        f"(after {c['time']} {c.get('timezone','')} deadline)")
        elif ctype == "departure_after":
            if not c.get("time"):
                continue
            h, m = map(int, c["time"].split(":"))
            limit = datetime.strptime(leg["date"], "%Y-%m-%d").replace(hour=h, minute=m)
            if dep_dt(option) < limit:
                return f"departs {dep_dt(option):%H:%M} (before {c['time']} {c.get('timezone','')})"
        elif ctype == "arrive_same_day":
            if arr_dt(option).date() != dep_dt(option).date():
                return "arrives next day (must arrive same day)"
        # 'no_red_eye' is a preference (Layer 2), not a hard eliminator.

    # Global preference-driven hard rules
    if prefs.get("no_basic_economy") and is_basic_economy(option):
        return "basic economy fare (not allowed)"

    lo, hi = prefs["layover_min_minutes"], prefs["layover_max_minutes"]
    for mins in layover_minutes(option):
        if mins < lo:
            return f"layover {mins}m < {lo}m minimum"
        if mins > hi:
            return f"layover {mins}m > {hi}m maximum"

    return None


# ---------- Layer 2: soft scoring ----------

def _norm_lower_better(value, lo, hi):
    """Min-max so that a LOWER raw value -> HIGHER score (1.0). Flat range -> 1.0."""
    if hi <= lo:
        return 1.0
    return (hi - value) / (hi - lo)


def _timing_metric(leg):
    """Which scheduling signal earns the 'timing' bonus for this leg."""
    types = {c["type"] for c in leg.get("hard_constraints", [])}
    if "departure_after" in types:
        return "departure"   # earlier departure = more margin to arrive same day
    return "arrival"         # earlier arrival = more buffer / less red-eye risk


def evaluate_leg(leg, options, prefs):
    """
    Score every option for a leg.
    Returns (ranked_passing, eliminated) where:
      ranked_passing = list of {"option","score","breakdown"} sorted best-first
      eliminated     = list of {"option","reason"}
    """
    passing, eliminated = [], []
    for o in options:
        reason = hard_violation(o, leg, prefs)
        (eliminated if reason else passing).append((o, reason))
    eliminated = [{"option": o, "reason": r} for o, r in eliminated]

    survivors = [o for o, _ in passing]
    if not survivors:
        return [], eliminated

    prices = [price(o) for o in survivors]
    times = [duration(o) for o in survivors]
    nonstop_prices = [price(o) for o in survivors if num_stops(o) == 0]
    min_nonstop = min(nonstop_prices) if nonstop_prices else None

    metric = _timing_metric(leg)
    timing_vals = [(dep_dt(o).hour * 60 + dep_dt(o).minute) if metric == "departure"
                   else (arr_dt(o).hour * 60 + arr_dt(o).minute) for o in survivors]
    t_lo, t_hi = min(timing_vals), max(timing_vals)

    w = config.WEIGHTS
    scored = []
    for o in survivors:
        dep = dep_dt(o)

        f_price = _norm_lower_better(price(o), min(prices), max(prices))
        f_time = _norm_lower_better(duration(o), min(times), max(times))
        f_redeye = 0.0 if is_red_eye(o) else 1.0

        if num_stops(o) == 0:
            f_nonstop = 1.0
        else:
            saves = (min_nonstop - price(o)) if min_nonstop is not None else 0
            f_nonstop = 1.0 if saves > prefs["connection_ok_if_saves"] else 0.0

        f_airline = 1.0 if is_star_alliance(o) else 0.0

        if dep.hour < 7:
            f_early = 0.0
        elif dep.hour < 8:
            f_early = 0.5
        else:
            f_early = 1.0

        tval = (dep.hour * 60 + dep.minute) if metric == "departure" \
            else (arr_dt(o).hour * 60 + arr_dt(o).minute)
        f_timing = _norm_lower_better(tval, t_lo, t_hi)

        breakdown = {
            "price": w["price"] * f_price,
            "travel_time": w["travel_time"] * f_time,
            "redeye": w["redeye"] * f_redeye,
            "nonstop": w["nonstop"] * f_nonstop,
            "airline": w["airline"] * f_airline,
            "early_departure": w["early_departure"] * f_early,
            "timing": w["timing"] * f_timing,
        }
        scored.append({"option": o, "score": sum(breakdown.values()), "breakdown": breakdown})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored, eliminated
