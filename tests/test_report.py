import pandas as pd

from src.report_excel import latest_complete, period_bounds


def test_week_bounds_monday_to_monday():
    s, e = period_bounds("week", pd.Timestamp("2011-12-01"))  # a Thursday
    assert s == pd.Timestamp("2011-11-28") and e == pd.Timestamp("2011-12-05")


def test_month_bounds():
    s, e = period_bounds("month", pd.Timestamp("2011-11-15 13:00"))
    assert s == pd.Timestamp("2011-11-01") and e == pd.Timestamp("2011-12-01")


def test_latest_complete_skips_partial_period():
    last = pd.Timestamp("2011-12-09 12:50")  # data ends mid-December, on a Friday
    assert period_bounds("month", latest_complete("month", last))[0] == pd.Timestamp("2011-11-01")
    assert period_bounds("week", latest_complete("week", last))[0] == pd.Timestamp("2011-11-28")
