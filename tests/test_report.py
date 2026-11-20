import openpyxl
import pandas as pd
import pytest

from src.report_excel import build_report, latest_complete, period_bounds, slice_period


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


def test_week_bounds_monday_and_sunday_anchors_agree():
    # a week is identified by any day inside it: its Monday and its Sunday
    # must give the same [start, end)
    mon = period_bounds("week", pd.Timestamp("2011-11-28"))
    sun = period_bounds("week", pd.Timestamp("2011-12-04"))
    assert mon == sun == (pd.Timestamp("2011-11-28"), pd.Timestamp("2011-12-05"))


def test_month_bounds_december_rolls_into_next_year():
    s, e = period_bounds("month", pd.Timestamp("2011-12-25"))
    assert s == pd.Timestamp("2011-12-01") and e == pd.Timestamp("2012-01-01")


def test_latest_complete_month_ending_exactly_at_midnight():
    # data stops at 23:59 on the last day of November: November is complete
    last = pd.Timestamp("2011-11-30 23:59")
    assert period_bounds("month", latest_complete("month", last))[0] == pd.Timestamp("2011-11-01")
    # data stops at 00:00 on 1 December: December has barely started, November still latest
    last = pd.Timestamp("2011-12-01 00:00")
    assert period_bounds("month", latest_complete("month", last))[0] == pd.Timestamp("2011-11-01")


def test_slice_period_is_start_inclusive_end_exclusive():
    df = pd.DataFrame({"InvoiceDate": pd.to_datetime(
        ["2011-10-31 23:59", "2011-11-01 00:00", "2011-11-15 12:00", "2011-12-01 00:00"])})
    start, end = period_bounds("month", pd.Timestamp("2011-11-15"))
    out = slice_period(df, start, end)
    assert list(out["InvoiceDate"]) == [pd.Timestamp("2011-11-01"), pd.Timestamp("2011-11-15 12:00")]


# --------------------------------------------------------------------------- #
# build_report end to end on a small synthetic dataset
# --------------------------------------------------------------------------- #
def _synthetic_sales() -> tuple[pd.DataFrame, pd.DataFrame]:
    cols = ["InvoiceDate", "Invoice", "StockCode", "Description", "Quantity",
            "Price", "Revenue", "Customer ID", "Country"]
    sales_rows = [
        # previous month (October) - only feeds the comparison column
        ["2011-10-10 09:00", "1001", "A1", "Widget", 2, 5.0, 10.0, 1.0, "United Kingdom"],
        # report month (November)
        ["2011-11-03 10:00", "1002", "A1", "Widget", 3, 5.0, 15.0, 1.0, "United Kingdom"],
        ["2011-11-03 11:00", "1003", "B2", "Gadget", 1, 20.0, 20.0, 2.0, "France"],
        ["2011-11-20 12:00", "1004", "A1", "Widget", 1, 5.0, 5.0, 3.0, "United Kingdom"],
    ]
    return_rows = [
        ["2011-11-05 09:00", "C1002", "A1", "Widget", -1, 5.0, -5.0, 1.0, "United Kingdom"],
    ]
    sales = pd.DataFrame(sales_rows, columns=cols)
    returns = pd.DataFrame(return_rows, columns=cols)
    for df in (sales, returns):
        df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    return sales, returns


def test_build_report_writes_expected_workbook(tmp_path):
    sales, returns = _synthetic_sales()
    path = build_report(sales, returns, period="month",
                        anchor=pd.Timestamp("2011-11-15"), out_dir=tmp_path)
    assert path.name == "sales_report_month_2011-11.xlsx" and path.exists()

    wb = openpyxl.load_workbook(path, data_only=True)
    assert set(wb.sheetnames) == {"Summary", "Daily", "Products", "Countries",
                                  "Top customers", "Order lines"}
    # Products: header + one row per product sold in November (A1 and B2)
    assert wb["Products"].max_row == 1 + 2
    # Order lines: header + the 3 November sales lines (October line excluded)
    assert wb["Order lines"].max_row == 1 + 3
    # Daily revenue total must equal November revenue 15 + 20 + 5
    daily = wb["Daily"]
    total_row = daily.max_row
    assert daily.cell(row=total_row, column=1).value == "Total"
    assert daily.cell(row=total_row, column=2).value == pytest.approx(40.0)


def test_build_report_rejects_period_without_sales(tmp_path):
    sales, returns = _synthetic_sales()
    with pytest.raises(SystemExit):
        build_report(sales, returns, period="month",
                     anchor=pd.Timestamp("2012-06-15"), out_dir=tmp_path)
