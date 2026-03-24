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
from ev_analyzer import (
    load_chargepoint,
    build_ev_hourly_map,
    separate_ev_from_household,
    compute_ev_optimized_cost,
    get_cheapest_rate_for_plan,
)
from rate_plans import RATE_PLANS


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

    # ===================================================================
    # EV-OPTIMIZED ANALYSIS using ChargePoint data
    # ===================================================================
    cp_path = str(Path(csv_path).parent / "chargepoint.csv")
    if Path(cp_path).exists():
        print()
        print_separator("*")
        print("  EV-OPTIMIZED ANALYSIS (using ChargePoint data)")
        print_separator("*")

        sessions = load_chargepoint(cp_path)
        ev_hourly = build_ev_hourly_map(sessions)
        household_records, daily_ev_kwh = separate_ev_from_household(records, ev_hourly)

        total_ev_kwh = sum(daily_ev_kwh.values())
        total_household_kwh = sum(r["kwh"] for r in household_records)
        ev_days_with_charging = sum(1 for v in daily_ev_kwh.values() if v > 0)

        print(f"\n  ChargePoint sessions:  {len(sessions)}")
        print(f"  Total EV energy:       {total_ev_kwh:,.1f} kWh ({total_ev_kwh / total_kwh * 100:.1f}% of total DTE usage)")
        print(f"  Household energy:      {total_household_kwh:,.1f} kWh")
        print(f"  Days with EV charging: {ev_days_with_charging}")
        print(f"  Avg charge per day:    {total_ev_kwh / max(ev_days_with_charging, 1):,.1f} kWh")

        # Show cheapest charging window per plan
        from datetime import datetime as dt_cls
        sample_summer = dt_cls(2025, 7, 15)  # Tuesday in summer
        sample_winter = dt_cls(2025, 1, 15)  # Wednesday in winter
        print(f"\n  Cheapest EV charging rate per plan:")
        print(f"  {'Plan':<45s} {'Summer':>12s} {'Non-Summer':>12s}  Charge Window")
        print(f"  {'-'*44} {'-'*12} {'-'*12}  {'-'*20}")
        for plan in RATE_PLANS:
            s_rate, s_tier, s_window = get_cheapest_rate_for_plan(plan, sample_summer)
            w_rate, w_tier, w_window = get_cheapest_rate_for_plan(plan, sample_winter)
            print(f"  {plan['name']:<45s} {s_rate*100:>10.2f}c  {w_rate*100:>10.2f}c  {w_window}")

        # Compute optimized costs per plan
        ev_results = []
        for plan in RATE_PLANS:
            result = compute_ev_optimized_cost(household_records, daily_ev_kwh, plan)
            ev_results.append(result)
        ev_results.sort(key=lambda r: r["total_cost"])

        cheapest_ev = ev_results[0]["total_cost"]

        print()
        print_separator()
        print("  EV-OPTIMIZED PLAN COMPARISON")
        print("  (Household at actual times + EV at cheapest hours per plan)")
        print_separator()

        for i, result in enumerate(ev_results):
            rank = i + 1
            diff = result["total_cost"] - cheapest_ev

            print(f"\n  #{rank}  {result['plan_name']}")
            print(f"      Total Cost:     {format_currency(result['total_cost'])}", end="")
            if diff > 0:
                print(f"  (+{format_currency(diff)})")
            else:
                print(f"  ** CHEAPEST **")

            print(f"      Household:      {format_currency(result['household_cost'])}  ({result['household_kwh']:,.1f} kWh)")
            print(f"      EV Charging:    {format_currency(result['ev_cost'])}  ({result['ev_kwh']:,.1f} kWh)")
            if result["ev_kwh"] > 0:
                avg_ev_rate = result["ev_cost"] / result["ev_kwh"] * 100
                print(f"      Avg EV rate:    {avg_ev_rate:.2f} cents/kWh")

            # Show EV rate tiers used
            for tier, rate in sorted(result["ev_rate_info"].items(), key=lambda x: x[1]):
                print(f"        -> {tier}: {rate*100:.2f}c/kWh")

        # Annualized EV-optimized
        print()
        print_separator()
        print(f"  EV-OPTIMIZED ANNUALIZED ESTIMATES ({num_days} days -> 365)")
        print_separator()

        for result in ev_results:
            annual = result["total_cost"] * annualization_factor
            annual_ev = result["ev_cost"] * annualization_factor
            print(f"  {result['plan_name']:<45s} {format_currency(annual):>10s}/yr  (EV: {format_currency(annual_ev)}/yr)")

        # Final recommendation
        print()
        print_separator("*")
        print("  FINAL RECOMMENDATION (EV-OPTIMIZED)")
        print_separator("*")

        ev_enrollable = [r for r in ev_results if r["plan_key"] != "dynamic_peak"]
        best_ev = ev_enrollable[0]
        best_ev_annual = best_ev["total_cost"] * annualization_factor
        best_ev_annual_ev_only = best_ev["ev_cost"] * annualization_factor

        print(f"\n  Best plan for your EV + household: {best_ev['plan_name']}")
        print(f"  Projected annual cost: {format_currency(best_ev_annual)}")
        print(f"    - Household: {format_currency((best_ev['household_cost']) * annualization_factor)}/yr")
        print(f"    - EV charging: {format_currency(best_ev_annual_ev_only)}/yr")

        if len(ev_enrollable) > 1:
            second_ev = ev_enrollable[1]
            savings = (second_ev["total_cost"] - best_ev["total_cost"]) * annualization_factor
            print(f"  Saves {format_currency(savings)}/yr vs {second_ev['plan_name']}")

        # Show what time to charge
        sample_date = dt_cls(2025, 7, 15)
        _, _, best_window = get_cheapest_rate_for_plan(
            next(p for p in RATE_PLANS if p["key"] == best_ev["plan_key"]),
            sample_date,
        )
        print(f"\n  Schedule your EV to charge during: {best_window}")

    print()


if __name__ == "__main__":
    main()
