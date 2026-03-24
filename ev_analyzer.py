"""
EV charging analysis using ChargePoint data.

Separates EV charging from household usage in DTE data,
then computes optimal cost by charging EV at each plan's cheapest hours.
"""

import csv
from collections import defaultdict
from datetime import datetime, timedelta

from rate_plans import RATE_PLANS


def load_chargepoint(csv_path: str) -> list[dict]:
    """Load ChargePoint charging sessions.

    Returns list of dicts with keys: start, end, kwh
    """
    sessions = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kwh = float(row["Energy (kWh)"].strip())
            if kwh <= 0:
                continue

            # Parse start/end datetimes (strip timezone abbreviation)
            start_str = row["Start"].strip()
            end_str = row["End"].strip()
            # Format: "3/22/2026, 11:36 PM EDT" — remove timezone suffix
            start_str = " ".join(start_str.rsplit(" ", 1)[0:1])
            end_str = " ".join(end_str.rsplit(" ", 1)[0:1])
            start_dt = datetime.strptime(start_str, "%m/%d/%Y, %I:%M %p")
            end_dt = datetime.strptime(end_str, "%m/%d/%Y, %I:%M %p")

            sessions.append({"start": start_dt, "end": end_dt, "kwh": kwh})
    return sessions


def distribute_session_to_hours(session: dict) -> dict[tuple[str, int], float]:
    """Distribute a charging session's kWh evenly across its hours.

    Returns dict of (date_str "MM/DD/YYYY", hour) -> kwh
    """
    start = session["start"]
    end = session["end"]
    total_kwh = session["kwh"]

    duration_hours = (end - start).total_seconds() / 3600
    if duration_hours <= 0:
        return {}

    kwh_per_hour = total_kwh / duration_hours
    result: dict[tuple[str, int], float] = {}

    current = start
    while current < end:
        # How much of this hour is within the session?
        hour_end = current.replace(minute=0, second=0) + timedelta(hours=1)
        segment_end = min(hour_end, end)
        fraction_hours = (segment_end - current).total_seconds() / 3600

        date_str = current.strftime("%m/%d/%Y")
        hour = current.hour
        key = (date_str, hour)
        result[key] = result.get(key, 0) + kwh_per_hour * fraction_hours

        current = hour_end

    return result


def build_ev_hourly_map(sessions: list[dict]) -> dict[tuple[str, int], float]:
    """Build a map of (date_str, hour) -> ev_kwh from all ChargePoint sessions."""
    ev_map: dict[tuple[str, int], float] = defaultdict(float)
    for session in sessions:
        for key, kwh in distribute_session_to_hours(session).items():
            ev_map[key] += kwh
    return dict(ev_map)


def separate_ev_from_household(
    dte_records: list[dict], ev_hourly: dict[tuple[str, int], float]
) -> tuple[list[dict], dict[str, float]]:
    """Separate DTE hourly records into household-only records and daily EV totals.

    Subtracts EV kWh from matching DTE hours. If EV kWh exceeds DTE reading
    for that hour (timing misalignment), caps subtraction at DTE value.

    Returns:
        household_records: DTE records with EV subtracted
        daily_ev_kwh: dict of date_str -> total EV kWh for that day
    """
    household_records = []
    daily_ev_kwh: dict[str, float] = defaultdict(float)

    for rec in dte_records:
        date_str = rec["datetime"].strftime("%m/%d/%Y")
        hour = rec["hour"]
        key = (date_str, hour)

        ev_kwh = ev_hourly.get(key, 0)
        daily_ev_kwh[date_str] += ev_kwh

        # Subtract EV, but don't go below zero
        household_kwh = max(0, rec["kwh"] - ev_kwh)

        household_records.append({
            "datetime": rec["datetime"],
            "hour": rec["hour"],
            "kwh": household_kwh,
            "daily_total": rec["daily_total"],
        })

    return household_records, dict(daily_ev_kwh)


def get_cheapest_rate_for_plan(plan: dict, dt: datetime) -> tuple[float, str, str]:
    """Find the cheapest rate and its time window for a plan on a given date.

    Returns (rate, tier_name, charging_window_description)
    """
    get_rate = plan["get_rate"]

    # Check all 24 hours and find the cheapest
    best_rate = float("inf")
    best_tier = ""
    best_hours = []

    for hour in range(24):
        rate, tier = get_rate(dt, hour)
        if rate < best_rate:
            best_rate = rate
            best_tier = tier
            best_hours = [hour]
        elif rate == best_rate:
            best_hours.append(hour)

    return best_rate, best_tier, _format_hours(best_hours)


def _format_hours(hours: list[int]) -> str:
    """Format a list of hours into a readable range string."""
    if not hours:
        return ""
    ranges = []
    start = hours[0]
    end = hours[0]
    for h in hours[1:]:
        if h == end + 1:
            end = h
        else:
            ranges.append(_hour_range_str(start, end))
            start = end = h
    ranges.append(_hour_range_str(start, end))
    return ", ".join(ranges)


def _hour_range_str(start: int, end: int) -> str:
    def fmt(h):
        if h == 0:
            return "12am"
        elif h < 12:
            return f"{h}am"
        elif h == 12:
            return "12pm"
        else:
            return f"{h-12}pm"
    if start == end:
        return fmt(start)
    return f"{fmt(start)}-{fmt(end + 1)}"


def compute_ev_optimized_cost(
    household_records: list[dict],
    daily_ev_kwh: dict[str, float],
    plan: dict,
) -> dict:
    """Compute total cost with household at actual times and EV at cheapest times.

    Returns dict with total_cost, household_cost, ev_cost, ev_kwh, ev_rate_info, monthly breakdown.
    """
    get_rate = plan["get_rate"]

    household_cost = 0.0
    household_kwh = 0.0
    ev_cost = 0.0
    ev_kwh_total = 0.0
    monthly_costs: dict[tuple[int, int], dict] = {}
    ev_rate_samples: dict[str, float] = {}

    # Household cost at actual times
    for rec in household_records:
        rate, tier = get_rate(rec["datetime"], rec["hour"])
        cost = rate * rec["kwh"]
        household_cost += cost
        household_kwh += rec["kwh"]

        key = (rec["datetime"].year, rec["datetime"].month)
        if key not in monthly_costs:
            monthly_costs[key] = {"household": 0.0, "ev": 0.0}
        monthly_costs[key]["household"] += cost

    # EV cost at cheapest rate per day
    for date_str, ev_kwh in daily_ev_kwh.items():
        if ev_kwh <= 0:
            continue
        dt = datetime.strptime(date_str, "%m/%d/%Y")
        best_rate, best_tier, window = get_cheapest_rate_for_plan(plan, dt)

        cost = best_rate * ev_kwh
        ev_cost += cost
        ev_kwh_total += ev_kwh
        ev_rate_samples[best_tier] = best_rate

        key = (dt.year, dt.month)
        if key not in monthly_costs:
            monthly_costs[key] = {"household": 0.0, "ev": 0.0}
        monthly_costs[key]["ev"] += cost

    return {
        "plan_name": plan["name"],
        "plan_key": plan["key"],
        "total_cost": household_cost + ev_cost,
        "household_cost": household_cost,
        "household_kwh": household_kwh,
        "ev_cost": ev_cost,
        "ev_kwh": ev_kwh_total,
        "ev_rate_info": ev_rate_samples,
        "monthly_costs": monthly_costs,
    }
