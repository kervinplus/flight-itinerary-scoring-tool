"""
main.py — Orchestrator.

    python main.py flight_brief.txt

Flow:  parse brief -> fetch flights per leg (cache/API/sample)
       -> filter hard constraints -> score survivors -> print report.
"""

import sys

import api
import config
import scoring


# ---------- display helpers ----------

def fmt_time(dt_str: str, airport: str) -> str:
    dt = scoring.parse_dt(dt_str)
    h = dt.hour % 12 or 12
    ap = "am" if dt.hour < 12 else "pm"
    return f"{h}:{dt.minute:02d}{ap} {config.airport_tz(airport)}"


def fmt_dur(mins: int) -> str:
    return f"{mins // 60}h {mins % 60:02d}m"


def fmt_date(date_str: str) -> str:
    return scoring.datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %b %d")


def stops_label(option) -> str:
    n = scoring.num_stops(option)
    if n == 0:
        return "Nonstop"
    vias = ",".join(f["arrival_airport"]["id"] for f in option["flights"][:-1])
    return f"{n} stop via {vias}"


def _airport(value):
    return value[0] if isinstance(value, list) else value


def leg_lines(leg_no: int, date: str, entry: dict) -> str:
    """Render one leg of the itinerary (3 lines)."""
    o = entry["option"]
    fs, ls = scoring.first_seg(o), scoring.last_seg(o)
    dep_id = fs["departure_airport"]["id"]
    arr_id = ls["arrival_airport"]["id"]
    redeye = " | RED-EYE" if scoring.is_red_eye(o) else ""
    return (
        f"LEG {leg_no}: {dep_id} -> {arr_id} | {fmt_date(date)}\n"
        f"  {scoring.primary_airline(o)} {fs['flight_number']} | "
        f"Depart {fmt_time(fs['departure_airport']['time'], dep_id)} -> "
        f"Arrive {fmt_time(ls['arrival_airport']['time'], arr_id)}\n"
        f"  {stops_label(o)} | {fmt_dur(scoring.duration(o))} | "
        f"{fs['travel_class']} | ${o['price']}{redeye}"
    )


# ---------- report ----------

def build_report(brief: dict, results: list) -> str:
    """results: list of dicts per leg: {leg, ranked, eliminated, source}."""
    legs = brief["legs"]
    prefs = brief["preferences"]
    out = []

    route = " -> ".join(
        [_airport(legs[0]["from"])] + [_airport(l["to"]) for l in legs]
    )
    span = f"{fmt_date(legs[0]['date'])} - {fmt_date(legs[-1]['date'])}"

    bar = "=" * 55
    out.append(bar)
    out.append("   FLIGHT ITINERARY RECOMMENDATION")
    out.append(f"   Trip: {route} | {span}")
    out.append(bar)

    feasible = all(r["ranked"] for r in results)
    if not feasible:
        out.append("\n[!] No complete itinerary — at least one leg has no option "
                   "that satisfies the hard constraints. See details below.\n")

    # Recommended itinerary (best per leg)
    out.append("\nRECOMMENDED ITINERARY")
    out.append("-" * 24)
    total_price = total_time = 0
    for r in results:
        leg = r["leg"]
        if not r["ranked"]:
            out.append(f"LEG {leg['leg_number']}: {_airport(leg['from'])} -> "
                       f"{_airport(leg['to'])} | NO FEASIBLE OPTION")
            continue
        best = r["ranked"][0]
        total_price += best["option"]["price"]
        total_time += scoring.duration(best["option"])
        out.append(leg_lines(leg["leg_number"], leg["date"], best))
        out.append("")

    budget = prefs["budget_total"]
    delta = budget - total_price
    status = (f"OK Under ${budget:,} (${delta:,} under budget)" if delta >= 0
              else f"OVER by ${-delta:,} (budget ${budget:,})")
    out.append(f"TOTAL: ${total_price:,} | Travel time: {fmt_dur(total_time)}")
    out.append(f"Budget: {status}")

    # Runner-up (smallest score drop from a single leg swap)
    out.append("\n" + "-" * 24)
    out.append("RUNNER-UP")
    runner = _runner_up(results, total_price, total_time)
    out.extend(runner)

    # Constraints & tradeoffs
    out.append("\n" + "-" * 24)
    out.append("CONSTRAINTS & TRADEOFFS")
    out.extend(_tradeoffs(results, prefs))

    # Scoring weights
    out.append("\n" + "-" * 24)
    out.append("SCORING WEIGHTS")
    w = config.WEIGHTS
    out.append(f"  Price: {w['price']:.0%} | Time: {w['travel_time']:.0%} | "
               f"Red-eye: {w['redeye']:.0%} | Nonstop: {w['nonstop']:.0%}")
    out.append(f"  United: {w['airline']:.0%} | Early departure: "
               f"{w['early_departure']:.0%} | Timing: {w['timing']:.0%}")
    out.append("\n" + bar)
    return "\n".join(out)


def _runner_up(results, rec_price, rec_time):
    """Swap the single leg with the smallest score gap to its #2 option."""
    best_swap = None
    for idx, r in enumerate(results):
        if len(r["ranked"]) >= 2:
            gap = r["ranked"][0]["score"] - r["ranked"][1]["score"]
            if best_swap is None or gap < best_swap[0]:
                best_swap = (gap, idx)
    if best_swap is None:
        return ["  (No alternative — each leg had a single viable option.)"]

    idx = best_swap[1]
    r = results[idx]
    leg = r["leg"]
    alt = r["ranked"][1]
    pick = r["ranked"][0]

    alt_price = rec_price - pick["option"]["price"] + alt["option"]["price"]
    alt_time = rec_time - scoring.duration(pick["option"]) + scoring.duration(alt["option"])
    dp = alt_price - rec_price
    dt = alt_time - rec_time

    price_word = (f"costs ${abs(dp)} more" if dp > 0
                  else f"saves ${abs(dp)}" if dp < 0 else "same price")
    time_word = (f"adds {fmt_dur(abs(dt))} travel" if dt > 0
                 else f"saves {fmt_dur(abs(dt))} travel" if dt < 0 else "same travel time")

    lines = [leg_lines(leg["leg_number"], leg["date"], alt)]
    lines.append(f'  "Runner-up swaps Leg {leg["leg_number"]} to '
                 f'{scoring.primary_airline(alt["option"])} — {price_word}, '
                 f'{time_word} vs the recommended pick."')
    return lines


def _tradeoffs(results, prefs):
    notes = []
    feasible = all(r["ranked"] for r in results)
    notes.append("  - All hard constraints satisfied: " + ("yes" if feasible else "NO"))

    for r in results:
        if not r["ranked"]:
            notes.append(f"  - Leg {r['leg']['leg_number']}: infeasible — "
                         f"all {len(r['eliminated'])} options eliminated")
            continue
        o = r["ranked"][0]["option"]
        ln = r["leg"]["leg_number"]
        dep = scoring.dep_dt(o)
        if dep.hour < 7:
            notes.append(f"  - Leg {ln} departs {dep.hour}:{dep.minute:02d} "
                         f"(before 7am — took the early-departure penalty, but still "
                         f"won on price + travel time)")
        elif dep.hour < 8:
            notes.append(f"  - Leg {ln} departs {dep.hour}:{dep.minute:02d} "
                         f"(7-8am window — half early-departure penalty)")
        if scoring.num_stops(o) > 0:
            saved = ""
            notes.append(f"  - Leg {ln} uses a connection ({stops_label(o)}) — "
                         f"chosen because it cleared the >${prefs['connection_ok_if_saves']} "
                         f"savings bar")
        if scoring.is_star_alliance(o):
            notes.append(f"  - Leg {ln} on {scoring.primary_airline(o)} "
                         f"(United/Star Alliance status bonus applied)")

    # Notable eliminations (e.g., red-eyes, after-deadline) — show up to 3
    notable = []
    for r in results:
        for e in r["eliminated"]:
            notable.append(f"  - Dropped {scoring.primary_airline(e['option'])} "
                           f"${e['option']['price']} on Leg {r['leg']['leg_number']}: {e['reason']}")
    notes.extend(notable[:3])
    return notes


# ---------- entry point ----------

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # so the report prints cleanly
    except Exception:
        pass

    import brief_parser  # imported here so --help style runs are cheap

    path = sys.argv[1] if len(sys.argv) > 1 else "flight_brief.txt"
    print(f"Parsing brief: {path}")
    brief = brief_parser.parse_brief(path)
    print(f"  Found {len(brief['legs'])} legs. Budget target: "
          f"${brief['preferences']['budget_total']:,}\n")

    results = []
    for leg in brief["legs"]:
        options, source = api.get_flights(leg)
        ranked, eliminated = scoring.evaluate_leg(leg, options, brief["preferences"])
        print(f"  Leg {leg['leg_number']} ({_airport(leg['from'])}->{_airport(leg['to'])}): "
              f"{len(options)} options [{source}] -> {len(ranked)} pass, "
              f"{len(eliminated)} eliminated")
        results.append({"leg": leg, "ranked": ranked,
                        "eliminated": eliminated, "source": source})

    print("\n" + build_report(brief, results))


if __name__ == "__main__":
    main()
