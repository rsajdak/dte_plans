"""
Load DTE hourly usage data and compute annual cost under each rate plan.
"""

import csv
from datetime import datetime
from pathlib import Path

from rate_plans import RATE_PLANS


def load_usage(csv_path: str) -> list[dict]:
    """Load hourly usage records from DTE export CSV.

    Returns list of dicts with keys: datetime, hour, kwh, daily_total
    """
    records = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            day_str = row["Day"].strip()
            hour_str = row["Hour of Day"].strip()
            kwh_str = row["Hourly Total"].strip()
            if kwh_str == "No Data" or kwh_str == "":
                continue
            kwh = float(kwh_str)
            daily_total = float(row["Daily Total"].strip())

            # Parse hour: "12:00 AM" -> 0, "1:00 AM" -> 1, "12:00 PM" -> 12, "1:00 PM" -> 13
            dt_day = datetime.strptime(day_str, "%m/%d/%Y")
            hour_dt = datetime.strptime(hour_str, "%I:%M %p")
            hour = hour_dt.hour

            records.append({
                "datetime": dt_day,
                "hour": hour,
                "kwh": kwh,
                "daily_total": daily_total,
            })
    return records


def compute_plan_cost(records: list[dict], plan: dict) -> dict:
    """Compute total cost and breakdown for a single rate plan.

    Returns dict with:
        total_cost, total_kwh, tier_breakdown (dict of tier_name -> {kwh, cost}),
        monthly_costs (dict of (year, month) -> cost)
    """
    get_rate = plan["get_rate"]
    total_cost = 0.0
    total_kwh = 0.0
    tier_breakdown: dict[str, dict] = {}
    monthly_costs: dict[tuple[int, int], float] = {}

    for rec in records:
        rate, tier = get_rate(rec["datetime"], rec["hour"])
        cost = rate * rec["kwh"]

        total_cost += cost
        total_kwh += rec["kwh"]

        if tier not in tier_breakdown:
            tier_breakdown[tier] = {"kwh": 0.0, "cost": 0.0}
        tier_breakdown[tier]["kwh"] += rec["kwh"]
        tier_breakdown[tier]["cost"] += cost

        key = (rec["datetime"].year, rec["datetime"].month)
        monthly_costs[key] = monthly_costs.get(key, 0.0) + cost

    return {
        "plan_name": plan["name"],
        "plan_key": plan["key"],
        "total_cost": total_cost,
        "total_kwh": total_kwh,
        "tier_breakdown": tier_breakdown,
        "monthly_costs": monthly_costs,
    }


def analyze_all_plans(csv_path: str) -> list[dict]:
    """Analyze usage against all rate plans. Returns results sorted by cost."""
    records = load_usage(csv_path)
    results = [compute_plan_cost(records, plan) for plan in RATE_PLANS]
    results.sort(key=lambda r: r["total_cost"])
    return results


def compute_date_range(records: list[dict]) -> tuple[datetime, datetime]:
    dates = [r["datetime"] for r in records]
    return min(dates), max(dates)
