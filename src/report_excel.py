"""Step 3 - one command builds a formatted weekly or monthly Excel sales report.

Usage:
    python -m src.report_excel                         # latest complete month
    python -m src.report_excel --period week           # latest complete week (Mon-Sun)
    python -m src.report_excel --period month --date 2011-11-15   # the month containing that date

Output: reports/sales_report_<period>_<label>.xlsx with
    Summary   - KPI table vs previous period (with % change), native Excel charts
    Daily     - one row per day
    Products  - every product sold in the period, with returns
    Countries - revenue by country
    Customers - top customers with their RFM segment
    Order lines - the raw cleaned lines (filterable)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src import analysis as an
from src.config import REPORTS_DIR

NAVY, BLUE, LIGHT, GREY = "#0d366b", "#2a78d6", "#eef4fc", "#52514e"


# --------------------------------------------------------------------------- #
# Period logic
# --------------------------------------------------------------------------- #
def period_bounds(period: str, anchor: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive start, exclusive end of the week (Mon-Sun) or month containing `anchor`."""
    anchor = anchor.normalize()
    if period == "week":
        start = anchor - pd.Timedelta(days=anchor.dayofweek)
        return start, start + pd.Timedelta(days=7)
    start = anchor.replace(day=1)
    return start, start + pd.offsets.MonthBegin(1)


def latest_complete(period: str, last_ts: pd.Timestamp) -> pd.Timestamp:
    """Anchor date of the most recent period that is fully covered by the data."""
    start, end = period_bounds(period, last_ts)
    if last_ts.normalize() + pd.Timedelta(days=1) >= end:  # the period containing the last date is complete
        return start
    return start - pd.Timedelta(days=1)


def slice_period(df: pd.DataFrame, start, end) -> pd.DataFrame:
    return df[(df["InvoiceDate"] >= start) & (df["InvoiceDate"] < end)]


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def build_report(sales: pd.DataFrame, returns: pd.DataFrame, period: str = "month",
                 anchor: pd.Timestamp | None = None, out_dir: Path = REPORTS_DIR) -> Path:
    if anchor is None:
        anchor = latest_complete(period, sales["InvoiceDate"].max())
    start, end = period_bounds(period, pd.Timestamp(anchor))
    prev_start, prev_end = period_bounds(period, start - pd.Timedelta(days=1))

    s, r = slice_period(sales, start, end), slice_period(returns, start, end)
    ps, pr = slice_period(sales, prev_start, prev_end), slice_period(returns, prev_start, prev_end)
    if s.empty:
        raise SystemExit(f"No sales between {start:%Y-%m-%d} and {end:%Y-%m-%d}.")

    label = f"{start:%Y-%m}" if period == "month" else f"{start:%Y}-W{start.isocalendar().week:02d}"
    title_period = (f"{start:%B %Y}" if period == "month"
                    else f"Week {start.isocalendar().week}, {start:%d %b} – {(end - pd.Timedelta(days=1)):%d %b %Y}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"sales_report_{period}_{label}.xlsx"

    k, kp = an.kpis(s, r), an.kpis(ps, pr)
    daily = an.sales_trend(s, "D")
    daily = daily[daily["orders"] > 0]
    daily["units"] = s.groupby(s["InvoiceDate"].dt.normalize())["Quantity"].sum().reindex(daily["period"]).values
    products = an.product_summary(s)
    ret_units = r.groupby("StockCode", observed=True)["Quantity"].sum().abs()
    ret_units.index = ret_units.index.astype(str)
    products["units_returned"] = products["StockCode"].map(ret_units).fillna(0).astype(int)
    products["revenue_share"] = products["revenue"] / products["revenue"].sum()
    countries = an.country_summary(s)
    rfm = an.rfm_table(sales[sales["InvoiceDate"] < end], snapshot=end).set_index("Customer ID")
    cust = (s.dropna(subset=["Customer ID"]).groupby("Customer ID")
            .agg(country=("Country", "first"), orders=("Invoice", "nunique"), revenue=("Revenue", "sum"))
            .sort_values("revenue", ascending=False).head(50))
    cust["country"] = cust["country"].astype(str)
    cust["segment"] = rfm["segment"].reindex(cust.index).values
    cust = cust.reset_index()

    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        f = {
            "title": wb.add_format({"bold": True, "font_size": 18, "font_color": NAVY}),
            "sub": wb.add_format({"font_color": GREY, "italic": True}),
            "h": wb.add_format({"bold": True, "font_color": "white", "bg_color": NAVY, "border": 1,
                                "border_color": "#d0d0d0", "valign": "vcenter", "text_wrap": True}),
            "section": wb.add_format({"bold": True, "font_size": 12, "font_color": NAVY, "bottom": 2,
                                      "bottom_color": BLUE}),
            "txt": wb.add_format({"border": 1, "border_color": "#d0d0d0"}),
            "gbp": wb.add_format({"num_format": "£#,##0", "border": 1, "border_color": "#d0d0d0"}),
            "gbp2": wb.add_format({"num_format": "£#,##0.00", "border": 1, "border_color": "#d0d0d0"}),
            "int": wb.add_format({"num_format": "#,##0", "border": 1, "border_color": "#d0d0d0"}),
            "pct": wb.add_format({"num_format": "0.0%", "border": 1, "border_color": "#d0d0d0"}),
            "chg": wb.add_format({"num_format": "+0.0%;-0.0%;0.0%", "border": 1, "border_color": "#d0d0d0"}),
            "date": wb.add_format({"num_format": "ddd dd mmm yyyy", "border": 1, "border_color": "#d0d0d0"}),
            "dt": wb.add_format({"num_format": "yyyy-mm-dd hh:mm", "border": 1, "border_color": "#d0d0d0"}),
            "kpi_lbl": wb.add_format({"bold": True, "bg_color": LIGHT, "border": 1, "border_color": "#d0d0d0"}),
        }
        green = wb.add_format({"font_color": "#0a7a3d", "bg_color": "#e3f4ea"})
        red = wb.add_format({"font_color": "#b42318", "bg_color": "#fde8e7"})

        def table(ws, df: pd.DataFrame, row: int, col: int, fmts: dict, widths: dict | None = None,
                  autofilter=False):
            for j, name in enumerate(df.columns):
                ws.write(row, col + j, name, f["h"])
            for i, rec in enumerate(df.itertuples(index=False), start=1):
                for j, (name, val) in enumerate(zip(df.columns, rec)):
                    fmt = f[fmts.get(name, "txt")]
                    if pd.isna(val):
                        ws.write_blank(row + i, col + j, None, fmt)
                    elif isinstance(val, pd.Timestamp):
                        ws.write_datetime(row + i, col + j, val.to_pydatetime(), fmt)
                    else:
                        ws.write(row + i, col + j, val, fmt)
            for j, name in enumerate(df.columns):
                ws.set_column(col + j, col + j, (widths or {}).get(name, max(12, len(name) + 2)))
            if autofilter:
                ws.autofilter(row, col, row + len(df), col + len(df.columns) - 1)
            return row + len(df)

        # ---------------- Summary ----------------
        ws = wb.add_worksheet("Summary")
        ws.hide_gridlines(2)
        ws.set_landscape(); ws.set_paper(9); ws.fit_to_pages(1, 1)  # prints on one A4 page
        ws.set_column("A:A", 2)
        ws.write("B2", f"Sales report – {title_period}", f["title"])
        ws.write("B3", f"Period {start:%d %b %Y} – {(end - pd.Timedelta(days=1)):%d %b %Y}, compared with "
                       f"{prev_start:%d %b %Y} – {(prev_end - pd.Timedelta(days=1)):%d %b %Y}. "
                       f"Generated by src/report_excel.py. Amounts in GBP.", f["sub"])
        ws.write("B5", "Key metrics", f["section"])
        rows = [("Revenue", k["revenue"], kp["revenue"], "gbp"),
                ("Orders", k["orders"], kp["orders"], "int"),
                ("Customers (identified)", k["customers"], kp["customers"], "int"),
                ("Units sold", k["units"], kp["units"], "int"),
                ("Average order value", k["aov"], kp["aov"], "gbp2"),
                ("Returned value", k["returned_value"], kp["returned_value"], "gbp"),
                ("Return rate", k["return_rate"], kp["return_rate"], "pct")]
        for j, h in enumerate(["Metric", "This period", "Previous period", "Change"]):
            ws.write(6, 1 + j, h, f["h"])
        for i, (name, cur, prev, fmt) in enumerate(rows, start=7):
            ws.write(i, 1, name, f["kpi_lbl"])
            ws.write(i, 2, cur, f[fmt])
            ws.write(i, 3, prev, f[fmt])
            # a live Excel formula, so the sheet stays correct if someone edits a number
            cached = (cur / prev - 1) if prev else ""
            ws.write_formula(i, 4, f"=IF(D{i + 1}=0,\"\",C{i + 1}/D{i + 1}-1)", f["chg"], cached)
        last_kpi = 7 + len(rows) - 1
        # green = good, red = bad (for returns, an increase is bad)
        ws.conditional_format(7, 4, last_kpi - 2, 4, {"type": "cell", "criteria": ">", "value": 0, "format": green})
        ws.conditional_format(7, 4, last_kpi - 2, 4, {"type": "cell", "criteria": "<", "value": 0, "format": red})
        ws.conditional_format(last_kpi - 1, 4, last_kpi, 4, {"type": "cell", "criteria": ">", "value": 0, "format": red})
        ws.conditional_format(last_kpi - 1, 4, last_kpi, 4, {"type": "cell", "criteria": "<", "value": 0, "format": green})
        ws.set_column("B:B", 26); ws.set_column("C:E", 16)

        top = products.head(10)[["description", "revenue", "units"]].rename(
            columns={"description": "Product", "revenue": "Revenue", "units": "Units"})
        top["Product"] = top["Product"].str.title()
        r0 = last_kpi + 3
        ws.write(r0 - 1, 1, "Top 10 products", f["section"])
        end_top = table(ws, top, r0, 1, {"Revenue": "gbp", "Units": "int"}, {"Product": 38})
        ws.set_column("B:B", 38)

        topc = countries.head(10)[["Country", "revenue", "orders", "revenue_share"]].rename(
            columns={"revenue": "Revenue", "orders": "Orders", "revenue_share": "Share"})
        c0 = end_top + 3
        ws.write(c0 - 1, 1, "Top 10 countries", f["section"])
        table(ws, topc, c0, 1, {"Revenue": "gbp", "Orders": "int", "Share": "pct"}, {"Country": 38})
        ws.set_column("B:B", 38)

        # ---------------- Daily ----------------
        d = daily.rename(columns={"period": "Date", "revenue": "Revenue", "orders": "Orders",
                                  "customers": "Customers", "aov": "Avg order value", "units": "Units"})
        d = d[["Date", "Revenue", "Orders", "Customers", "Units", "Avg order value"]]
        wd = wb.add_worksheet("Daily")
        wd.freeze_panes(1, 0)
        n_daily = table(wd, d, 0, 0, {"Date": "date", "Revenue": "gbp", "Orders": "int", "Customers": "int",
                                      "Units": "int", "Avg order value": "gbp2"}, {"Date": 18})
        wd.write(n_daily + 1, 0, "Total", f["kpi_lbl"])
        wd.write_formula(n_daily + 1, 1, f"=SUM(B2:B{n_daily + 1})", f["gbp"], float(d["Revenue"].sum()))
        wd.write_formula(n_daily + 1, 2, f"=SUM(C2:C{n_daily + 1})", f["int"], int(d["Orders"].sum()))
        wd.write_formula(n_daily + 1, 4, f"=SUM(E2:E{n_daily + 1})", f["int"], int(d["Units"].sum()))
        wd.conditional_format(1, 1, n_daily, 1, {"type": "data_bar", "bar_color": "#9ec5f4", "bar_solid": True})

        # ---------------- Charts on Summary (native Excel charts) ----------------
        ch = wb.add_chart({"type": "column"})
        ch.add_series({"name": "Revenue", "categories": ["Daily", 1, 0, n_daily, 0],
                       "values": ["Daily", 1, 1, n_daily, 1], "fill": {"color": BLUE}, "gap": 60})
        ch.set_title({"name": "Daily revenue", "name_font": {"size": 12, "color": NAVY}})
        ch.set_legend({"none": True})
        ch.set_x_axis({"text_axis": True, "num_format": "ddd dd mmm", "num_font": {"rotation": -45, "size": 8}})
        ch.set_y_axis({"num_format": "£#,##0", "major_gridlines": {"visible": True, "line": {"color": "#e8e7e3"}}})
        ch.set_size({"width": 620, "height": 300})
        ws.insert_chart("G6", ch)

        bar = wb.add_chart({"type": "bar"})
        bar.add_series({"name": "Revenue", "categories": ["Summary", r0 + 1, 1, r0 + len(top), 1],
                        "values": ["Summary", r0 + 1, 2, r0 + len(top), 2], "fill": {"color": BLUE}, "gap": 50})
        bar.set_title({"name": "Top 10 products by revenue", "name_font": {"size": 12, "color": NAVY}})
        bar.set_legend({"none": True})
        bar.set_y_axis({"reverse": True, "crossing": "max", "num_font": {"size": 8}})
        bar.set_x_axis({"num_format": "£#,##0", "major_gridlines": {"visible": True, "line": {"color": "#e8e7e3"}}})
        bar.set_size({"width": 620, "height": 330})
        ws.insert_chart("G22", bar)

        # ---------------- Products ----------------
        p = products[["StockCode", "description", "revenue", "revenue_share", "units", "orders", "units_returned"]]
        p = p.rename(columns={"StockCode": "Stock code", "description": "Product", "revenue": "Revenue",
                              "revenue_share": "Share of revenue", "units": "Units sold", "orders": "Orders",
                              "units_returned": "Units returned"})
        wp = wb.add_worksheet("Products")
        wp.freeze_panes(1, 0)
        n = table(wp, p, 0, 0, {"Revenue": "gbp", "Share of revenue": "pct", "Units sold": "int", "Orders": "int",
                                "Units returned": "int"}, {"Product": 40}, autofilter=True)
        wp.conditional_format(1, 2, n, 2, {"type": "data_bar", "bar_color": "#9ec5f4", "bar_solid": True})

        # ---------------- Countries ----------------
        c = countries.rename(columns={"revenue": "Revenue", "orders": "Orders", "customers": "Customers",
                                      "aov": "Avg order value", "revenue_share": "Share of revenue"})
        wc = wb.add_worksheet("Countries")
        wc.freeze_panes(1, 0)
        table(wc, c, 0, 0, {"Revenue": "gbp", "Orders": "int", "Customers": "int", "Avg order value": "gbp2",
                            "Share of revenue": "pct"}, {"Country": 22}, autofilter=True)

        # ---------------- Customers ----------------
        cu = cust.rename(columns={"Customer ID": "Customer ID", "country": "Country", "orders": "Orders",
                                  "revenue": "Revenue", "segment": "RFM segment"})
        cu["Customer ID"] = cu["Customer ID"].astype(int)
        wcu = wb.add_worksheet("Top customers")
        wcu.freeze_panes(1, 0)
        table(wcu, cu, 0, 0, {"Orders": "int", "Revenue": "gbp", "Customer ID": "txt"},
              {"RFM segment": 20, "Country": 18}, autofilter=True)

        # ---------------- Order lines (fast path: pandas writer + formats) ----------------
        lines = s[["InvoiceDate", "Invoice", "StockCode", "Description", "Quantity", "Price", "Revenue",
                   "Customer ID", "Country"]].copy()
        for col in ["Invoice", "StockCode", "Description", "Country"]:
            lines[col] = lines[col].astype(str)
        lines["Customer ID"] = lines["Customer ID"].astype("float")
        lines.sort_values("InvoiceDate").to_excel(xw, sheet_name="Order lines", index=False)
        wl = xw.sheets["Order lines"]
        wl.freeze_panes(1, 0)
        wl.autofilter(0, 0, len(lines), len(lines.columns) - 1)
        wl.set_column("A:A", 17, wb.add_format({"num_format": "yyyy-mm-dd hh:mm"}))
        wl.set_column("B:C", 10)
        wl.set_column("D:D", 38)
        wl.set_column("E:E", 9, wb.add_format({"num_format": "#,##0"}))
        wl.set_column("F:G", 11, wb.add_format({"num_format": "£#,##0.00"}))
        wl.set_column("H:H", 11, wb.add_format({"num_format": "0"}))
        wl.set_column("I:I", 16)

        ws.activate()
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a weekly or monthly Excel sales report.")
    ap.add_argument("--period", choices=["week", "month"], default="month")
    ap.add_argument("--date", help="any date inside the wanted period (YYYY-MM-DD); default = latest complete")
    ap.add_argument("--out", default=str(REPORTS_DIR), help="output folder")
    args = ap.parse_args()
    sales, returns = an.load_clean()
    anchor = pd.Timestamp(args.date) if args.date else None
    path = build_report(sales, returns, args.period, anchor, Path(args.out))
    print(f"Report written: {path}")


if __name__ == "__main__":
    main()
