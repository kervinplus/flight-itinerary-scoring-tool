"""
brief_parser.py — Turn a free-text trip brief (.txt) into structured JSON.

Pure regex, zero paid APIs, $0 cost. The goal: anyone can paste a new brief with
different routes/dates and the tool just works, no code changes. Whatever the
parser can't confidently extract falls back to config.DEFAULT_PREFERENCES.

Public entry point:  parse_brief(path) -> dict
"""

import re
from datetime import datetime

import config


def _to_24h(text: str):
    """'5:00pm' -> '17:00', 'midnight' -> '00:00', '7am' -> '07:00'."""
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if "midnight" in t:
        return "00:00"
    if "noon" in t:
        return "12:00"
    m = re.match(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", t)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ap = m.group(3)
    if ap == "pm" and hour != 12:
        hour += 12
    if ap == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _parse_date(text: str):
    """'Mon Jul 13, 2026' -> '2026-07-13'. Tolerant of extra trailing words."""
    m = re.search(r"([A-Za-z]{3})\s+([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})", text)
    if not m:
        return None
    cleaned = f"{m.group(1)} {m.group(2)} {int(m.group(3))}, {m.group(4)}"
    try:
        return datetime.strptime(cleaned, "%a %b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _airports(text: str):
    """
    Extract airport codes from a leg endpoint string.

    Prefers explicit codes in parentheses ('NYC (JFK or LGA; EWR acceptable)'
    -> [JFK, LGA, EWR]); otherwise expands metro codes ('NYC' -> [JFK, LGA, EWR]).
    """
    paren = re.search(r"\(([^)]*)\)", text)
    if paren:
        codes = re.findall(r"\b[A-Z]{3}\b", paren.group(1))
        if codes:
            return _dedupe(codes)
    head = re.sub(r"\([^)]*\)", "", text)
    codes = re.findall(r"\b[A-Z]{3}\b", head)
    expanded = []
    for c in codes:
        expanded.extend(config.METRO_CODES.get(c, [c]))
    return _dedupe(expanded)


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _leg_constraints(block: str, from_codes, to_codes):
    """Pull hard constraints (and the no-red-eye preference) out of a leg block."""
    constraints = []
    dep_tz = config.airport_tz(from_codes[0])
    arr_tz = config.airport_tz(to_codes[0])

    # "land ... by 5:00pm ET"  /  "land at SFO before midnight"
    # (midnight/noon listed first so they win over the numeric pattern)
    m = re.search(
        r"(?:land|arrive)[^.\n]*?\b(?:by|before)\s+(midnight|noon|\d{1,2}(?::\d{2})?\s*[ap]m)",
        block, re.I)
    if m:
        constraints.append({"type": "arrival_before", "time": _to_24h(m.group(1)), "timezone": arr_tz})

    # "depart after 3:00pm"
    m = re.search(r"depart(?:ing)?\s+after\s+([\d:apm]+)", block, re.I)
    if m:
        constraints.append({"type": "departure_after", "time": _to_24h(m.group(1)), "timezone": dep_tz})

    # "Must arrive ... by end of day"
    if re.search(r"by\s+end\s+of\s+day", block, re.I):
        constraints.append({"type": "arrive_same_day"})

    # "no red-eye" — a preference, not a hard eliminator
    if re.search(r"no\s+red[-\s]?eye", block, re.I):
        constraints.append({"type": "no_red_eye", "strength": "preference"})

    return constraints


def _parse_preferences(text: str):
    """Extract soft preferences; fall back to config defaults for anything missing."""
    prefs = dict(config.DEFAULT_PREFERENCES)

    m = re.search(r"under\s*\$([\d,]+)", text, re.I)
    if m:
        prefs["budget_total"] = int(m.group(1).replace(",", ""))

    m = re.search(r"\$(\d+)\s*MORE\s+to\s+avoid\s+a\s+red[-\s]?eye", text, re.I)
    if m:
        prefs["premium_for_no_redeye"] = int(m.group(1))

    m = re.search(r"save\s+(\d+)\+?\s*hours", text, re.I)
    if m:
        prefs["premium_for_time_savings"] = {
            "amount": prefs["premium_for_no_redeye"],
            "min_hours_saved": int(m.group(1)),
        }

    m = re.search(r"saves?\s*>?\s*\$(\d+)", text, re.I)
    if m:
        prefs["connection_ok_if_saves"] = int(m.group(1))

    m = re.search(r"(\d+)\s*min(?:ute)?s?\s+minimum", text, re.I)
    if m:
        prefs["layover_min_minutes"] = int(m.group(1))
    m = re.search(r"([\d.]+)\s*hrs?\s+maximum", text, re.I)
    if m:
        prefs["layover_max_minutes"] = int(float(m.group(1)) * 60)

    if re.search(r"no\s+basic\s+economy", text, re.I):
        prefs["no_basic_economy"] = True

    m = re.search(r"departures?\s+before\s+([\d:apm]+)", text, re.I)
    if m:
        prefs["no_departure_before"] = _to_24h(m.group(1))

    return prefs


def parse_brief(path: str) -> dict:
    """Parse a trip-brief .txt file into the structured dict the tool consumes."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # Traveler
    count_m = re.search(r"(\d+)\s+passenger", text, re.I)
    home_m = re.search(r"HOME AIRPORT:\s*([A-Z]{3})", text)
    alt_m = re.search(r"HOME AIRPORT:[^\n]*\(([^)]*)\)", text)
    alternates = re.findall(r"\b[A-Z]{3}\b", alt_m.group(1)) if alt_m else []

    traveler = {
        "count": int(count_m.group(1)) if count_m else 1,
        "home_airport": home_m.group(1) if home_m else "SFO",
        "alternate_airports": alternates,
    }

    # Legs — capture each "LEG N: A -> B ...<block>" until the next LEG or SCORING.
    leg_pat = re.compile(
        r"LEG\s+(\d+):\s*([A-Z]{3}[^\n]*?)\s*(?:→|->)\s*([^\n]+)\n(.*?)"
        r"(?=\nLEG\s+\d+:|\nSCORING|\Z)",
        re.S,
    )

    legs = []
    for m in leg_pat.finditer(text):
        leg_no = int(m.group(1))
        from_codes = _airports(m.group(2))
        to_codes = _airports(m.group(3))
        block = m.group(0)
        date = _parse_date(block)
        legs.append({
            "leg_number": leg_no,
            "from": from_codes[0] if len(from_codes) == 1 else from_codes,
            "to": to_codes[0] if len(to_codes) == 1 else to_codes,
            "date": date,
            "hard_constraints": _leg_constraints(block, from_codes, to_codes),
        })

    legs.sort(key=lambda x: x["leg_number"])

    return {
        "traveler": traveler,
        "legs": legs,
        "preferences": _parse_preferences(text),
    }


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "flight_brief.txt"
    print(json.dumps(parse_brief(path), indent=2))
