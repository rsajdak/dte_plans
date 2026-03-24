#!/usr/bin/env python3
"""
DTE Rate Plan Analyzer

Analyzes hourly electricity usage data and compares costs across
DTE Energy's residential rate plans to find the cheapest option.

Usage:
    python main.py [path_to_usage.csv]
"""

import sys
from pathlib import Path

from usage_analyzer import load_usage, analyze_all_plans, compute_date_range


def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def format_month(year: int, month: int) -> str:
    from datetime import datetime
    return datetime(year, month, 1).strftime("%b %Y")


def print_separator(char: str = "=", width: int = 70):
    print(char * width)


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "data/usage.csv"

    if not Path(csv_path).exists():
        print(f"Error: Usage file not found: {csv_path}")
        sys.exit(1)

    print_separator()
    print("  DTE Energy Rate Plan Analyzer")
    print_separator()

    # Load data and show summary
    records = load_usage(csv_path)
    date_min, date_max = compute_date_range(records)
    total_kwh = sum(r["kwh"] for r in records)
    num_days = (date_max - date_min).days + 1

    print(f"\nData range:    {date_min.strftime('%m/%d/%Y')} - {date_max.strftime('%m/%d/%Y')} ({num_days} days)")
    print(f"Total records: {len(records):,} hourly readings")
    print(f"Total usage:   {total_kwh:,.1f} kWh")
    print(f"Avg daily:     {total_kwh / num_days:,.1f} kWh/day")

    # Analyze EV charging pattern (heavy overnight usage)
    night_kwh = sum(r["kwh"] for r in records if r["hour"] >= 22 or r["hour"] < 7)
    night_pct = night_kwh / total_kwh * 100
    print(f"\nOvernight usage (10pm-7am): {night_kwh:,.1f} kWh ({night_pct:.1f}% of total)")
    print("  ^ Includes EV charging window")

    # Run analysis
    print()
    print_separator()
    print("  RATE PLAN COMPARISON (sorted cheapest to most expensive)")
    print_separator()

    results = analyze_all_plans(csv_path)
    cheapest_cost = results[0]["total_cost"]

    for i, result in enumerate(results):
        rank = i + 1
        diff = result["total_cost"] - cheapest_cost

        print(f"\n{'#' + str(rank)}  {result['plan_name']}")
        print(f"    Annual Cost: {format_currency(result['total_cost'])}", end="")
        if diff > 0:
            print(f"  (+{format_currency(diff)} vs cheapest)")
        else:
            print(f"  ** CHEAPEST **")

        print(f"    Avg rate:    {result['total_cost'] / result['total_kwh'] * 100:.2f} cents/kWh")

        # Tier breakdown
        print("    Tier breakdown:")
        for tier_name, data in sorted(result["tier_breakdown"].items(), key=lambda x: -x[1]["kwh"]):
            pct = data["kwh"] / result["total_kwh"] * 100
            avg_rate = data["cost"] / data["kwh"] * 100 if data["kwh"] > 0 else 0
            print(f"      {tier_name:30s} {data['kwh']:>10,.1f} kWh ({pct:5.1f}%)  {format_currency(data['cost']):>10s}  @ {avg_rate:.2f}c/kWh")

    # Monthly cost comparison table
    print()
    print_separator()
    print("  MONTHLY COST COMPARISON")
    print_separator()

    # Collect all months
    all_months = set()
    for result in results:
        all_months.update(result["monthly_costs"].keys())
    all_months = sorted(all_months)

    # Print header
    header = f"{'Month':<10}"
    for result in results:
        short_name = result["plan_key"]
        header += f"  {short_name:>15}"
    print(header)
    print("-" * len(header))

    for ym in all_months:
        row = f"{format_month(*ym):<10}"
        costs = []
        for result in results:
            cost = result["monthly_costs"].get(ym, 0)
            costs.append(cost)
            row += f"  {format_currency(cost):>15}"
        print(row)

    # Annualized estimates (data may span more or fewer than 12 months)
    annualization_factor = 365.0 / num_days
    print()
    print_separator()
    print(f"  ANNUALIZED ESTIMATES (data covers {num_days} days, projected to 365)")
    print_separator()
    for result in results:
        annual = result["total_cost"] * annualization_factor
        print(f"  {result['plan_name']:<50s} {format_currency(annual):>10s}/yr")

    # Recommendation
    print()
    print_separator()
    print("  RECOMMENDATION")
    print_separator()

    # Separate enrollable vs closed plans
    enrollable = [r for r in results if r["plan_key"] != "dynamic_peak"]
    best_enrollable = enrollable[0]
    best_overall = results[0]

    if best_overall["plan_key"] == "dynamic_peak":
        annual_dp = best_overall["total_cost"] * annualization_factor
        print(f"\n  Note: Dynamic Peak Pricing is CLOSED to new enrollments.")
        print(f"  (If you're already on it, projected annual cost: {format_currency(annual_dp)})")

    annual_best = best_enrollable["total_cost"] * annualization_factor
    print(f"\n  Best enrollable plan: {best_enrollable['plan_name']}")
    print(f"  Projected annual cost: {format_currency(annual_best)}")

    if len(enrollable) > 1:
        second = enrollable[1]
        savings = (second["total_cost"] - best_enrollable["total_cost"]) * annualization_factor
        print(f"  Saves {format_currency(savings)}/yr vs {second['plan_name']}")

    # EV-specific advice
    print(f"\n  With {night_pct:.0f}% of your usage during overnight hours (EV charging),")
    overnight_result = next((r for r in results if r["plan_key"] == "overnight_savers"), None)
    tod_11_7_result = next((r for r in results if r["plan_key"] == "tod_11_7"), None)
    if best_enrollable["plan_key"] == "overnight_savers":
        print("  the Overnight Savers plan rewards your charging pattern with the")
        print("  lowest super off-peak rate of 11.74 cents/kWh from 1am-7am.")
    elif best_enrollable["plan_key"] == "tod_11_7":
        print("  the Time of Day 11am-7pm plan gives you the best deal because its")
        print("  low off-peak rate (14.97-15.18c/kWh) applies to all your overnight hours.")
        if overnight_result:
            os_annual = overnight_result["total_cost"] * annualization_factor
            print(f"  Overnight Savers would cost {format_currency(os_annual)}/yr -- its summer")
            print("  off-peak and peak rates offset the super off-peak savings.")

    print()


if __name__ == "__main__":
    main()
