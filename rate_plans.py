"""
DTE Energy residential electric rate plan definitions.

Rate data sourced from:
https://www.dteenergy.com/us/en/residential/service-request/pricing/rate-options/residential-pricing-options.html

All rates are in dollars per kWh.
"""

from datetime import datetime


def _is_summer_jun_sep(dt: datetime) -> bool:
    """June 1 - September 30."""
    return 6 <= dt.month <= 9


def _is_summer_jun_oct(dt: datetime) -> bool:
    """June 1 - October 31."""
    return 6 <= dt.month <= 10


def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5  # Mon=0 .. Fri=4


# ---------------------------------------------------------------------------
# Each plan is a dict with:
#   "name": display name
#   "get_rate": function(dt: datetime, hour: int) -> (rate_dollars, tier_name)
# ---------------------------------------------------------------------------


def _tod_3_7_rate(dt: datetime, hour: int) -> tuple[float, str]:
    """Time of Day Rate 3 p.m. - 7 p.m.

    Peak: 3pm-7pm weekdays
    Off-Peak: all other times
    """
    is_peak = _is_weekday(dt) and 15 <= hour < 19

    if is_peak:
        if _is_summer_jun_sep(dt):
            return (0.2413, "Peak (Summer)")
        else:
            return (0.2005, "Peak (Non-Summer)")
    else:
        return (0.1844, "Off-Peak")


def _tod_11_7_rate(dt: datetime, hour: int) -> tuple[float, str]:
    """Time of Day Rate 11 a.m. - 7 p.m.

    Peak: 11am-7pm weekdays
    Off-Peak: all other times
    """
    is_peak = _is_weekday(dt) and 11 <= hour < 19

    if is_peak:
        if _is_summer_jun_oct(dt):
            return (0.2593, "Peak (Summer)")
        else:
            return (0.2341, "Peak (Non-Summer)")
    else:
        if _is_summer_jun_oct(dt):
            return (0.1518, "Off-Peak (Summer)")
        else:
            return (0.1497, "Off-Peak (Non-Summer)")


def _overnight_savers_rate(dt: datetime, hour: int) -> tuple[float, str]:
    """Overnight Savers.

    Super Off-Peak: 1am-7am daily
    Off-Peak: 7am-3pm and 7pm-1am weekdays; all non-super-off-peak on weekends
    Peak: 3pm-7pm weekdays only
    """
    is_super_off_peak = 1 <= hour < 7

    if is_super_off_peak:
        return (0.1174, "Super Off-Peak")

    is_peak = _is_weekday(dt) and 15 <= hour < 19

    if is_peak:
        if _is_summer_jun_sep(dt):
            return (0.3556, "Peak (Summer)")
        else:
            return (0.1906, "Peak (Non-Summer)")
    else:
        if _is_summer_jun_sep(dt):
            return (0.2546, "Off-Peak (Summer)")
        else:
            return (0.1555, "Off-Peak (Non-Summer)")


def _dynamic_peak_pricing_rate(dt: datetime, hour: int) -> tuple[float, str]:
    """Dynamic Peak Pricing.

    Off-Peak: 11pm-7am weekdays, all day weekends/holidays
    Mid-Peak: 7am-3pm and 7pm-11pm weekdays
    Peak: 3pm-7pm weekdays
    Critical Peak: 3pm-7pm on select weekdays (max 14 days/year) - $1.05/kWh
      We model this conservatively assuming 14 critical peak days in summer.
      On non-critical weekdays, 3-7pm is regular Peak.

    Note: No longer accepting new enrollments.
    """
    is_weekend = not _is_weekday(dt)

    if is_weekend or hour >= 23 or hour < 7:
        return (0.1431, "Off-Peak")

    if 15 <= hour < 19 and not is_weekend:
        return (0.2692, "Peak")

    # Weekday 7am-3pm or 7pm-11pm
    return (0.1861, "Mid-Peak")


RATE_PLANS = [
    {
        "name": "Time of Day 3pm-7pm (Standard)",
        "key": "tod_3_7",
        "get_rate": _tod_3_7_rate,
    },
    {
        "name": "Time of Day 11am-7pm",
        "key": "tod_11_7",
        "get_rate": _tod_11_7_rate,
    },
    {
        "name": "Overnight Savers",
        "key": "overnight_savers",
        "get_rate": _overnight_savers_rate,
    },
    {
        "name": "Dynamic Peak Pricing (closed to new enrollments)",
        "key": "dynamic_peak",
        "get_rate": _dynamic_peak_pricing_rate,
    },
]
