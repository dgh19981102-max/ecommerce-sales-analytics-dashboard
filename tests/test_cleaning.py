"""Unit tests for the cleaning rules and key analysis functions. Run: pytest -q"""
import pandas as pd
import pytest

from src import analysis as an
from src import cleaning as cl


def make_df(rows):
    cols = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
    df = pd.DataFrame(rows, columns=cols)
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    df["Customer ID"] = df["Customer ID"].astype("Int64")
    return df


@pytest.fixture
def raw():
    return make_df([
        ["500001", "85123A", "white heart", 6, "2010-01-04 10:00", 2.55, 17850, "United Kingdom"],
        ["500001", "85123A", "white heart", 6, "2010-01-04 10:00", 2.55, 17850, "United Kingdom"],  # duplicate
        ["500002", "POST", "POSTAGE", 1, "2010-01-04 11:00", 18.0, 12345, "Germany"],               # non-product
        ["500003", "gift_0001_20", "voucher", 1, "2010-01-05 11:00", 17.0, None, "United Kingdom"],  # voucher
        ["500004", "22423", "cake stand", 2, "2010-01-05 12:00", 0.0, None, "United Kingdom"],       # price 0
        ["500005", "22423", "Regency cake stand", 2, "2010-02-01 09:00", 12.75, 12345, "EIRE"],
        ["C500006", "22423", "REGENCY CAKE STAND", -1, "2010-02-02 09:00", 12.75, 12345, "EIRE"],    # return
        ["500007", "23843", "PAPER CRAFT", 80995, "2011-12-09 09:15", 2.08, 16446, "United Kingdom"],  # mistake
        ["C500008", "23843", "PAPER CRAFT", -80995, "2011-12-09 09:27", 2.08, 16446, "United Kingdom"],
        ["500009", "21212", "cake cases", 24, "2010-03-01 09:00", 0.55, None, "United Kingdom"],      # guest
    ])


def test_drop_duplicates(raw):
    assert len(cl.drop_duplicates(raw)) == len(raw) - 1


def test_drop_non_products(raw):
    out = cl.drop_non_products(raw)
    assert not out["StockCode"].isin(["POST", "gift_0001_20"]).any()
    assert len(out) == len(raw) - 2


def test_drop_non_positive_price(raw):
    assert (cl.drop_non_positive_price(raw)["Price"] > 0).all()


def test_stock_adjustments_keep_cancellations():
    df = make_df([
        ["1", "A", "x", -5, "2010-01-01", 1.0, 1, "UK"],   # adjustment -> drop
        ["C2", "A", "x", -5, "2010-01-01", 1.0, 1, "UK"],  # return -> keep
        ["3", "A", "x", 5, "2010-01-01", 1.0, 1, "UK"],    # sale -> keep
    ])
    assert list(cl.drop_stock_adjustments(df)["Invoice"]) == ["C2", "3"]


def test_reversed_bulk_orders_removes_both_sides(raw):
    out = cl.drop_reversed_bulk_orders(raw)
    assert not out["StockCode"].eq("23843").any()
    # small returns are untouched
    assert out["Invoice"].eq("C500006").any()


def test_full_pipeline(raw):
    sales, returns, log = cl.clean(raw)
    assert (sales["Quantity"] > 0).all() and (sales["Price"] > 0).all()
    assert (returns["Quantity"] < 0).all()
    assert len(sales) == 3 and len(returns) == 1
    # canonical description: most frequent spelling, upper-cased
    assert sales.loc[sales["StockCode"] == "22423", "Description"].iat[0] == "REGENCY CAKE STAND"
    assert "Ireland" in set(sales["Country"])
    assert sales["IsGuest"].sum() == 1
    # the log accounts for every removed row
    removed = log["rows_removed"].sum()
    assert removed == len(raw) - len(sales) - len(returns)


def test_revenue_column(raw):
    sales, _, _ = cl.clean(raw)
    assert sales["Revenue"].equals((sales["Quantity"] * sales["Price"]).round(2))


# ---- analysis ----
def test_top_share_and_pareto():
    v = pd.Series([80, 10, 5, 5, 0])
    assert an.top_share(v, 0.2) == pytest.approx(0.8)
    assert an.share_needed_for(v, 0.8) == pytest.approx(0.2)


def test_rfm_scores_in_range(raw):
    sales, _, _ = cl.clean(raw)
    rfm = an.rfm_table(sales)
    assert rfm[["R", "F", "M"]].isin(range(1, 6)).all().all()
    assert rfm["Customer ID"].notna().all()  # guests excluded


def test_cohort_month0_is_100pct(raw):
    sales, _, _ = cl.clean(raw)
    ret = an.cohort_retention(sales)
    assert (ret[0] == 1).all()


def test_duplicates_differing_only_in_spelling_are_removed():
    df = make_df([
        ["554084", "23298", "SPOTTY BUNTING", 3, "2011-05-22 11:52", 4.95, 12909, "United Kingdom"],
        ["554084", "23298", "BUNTING , SPOTTY", 3, "2011-05-22 11:52", 4.95, 12909, "United Kingdom"],
        ["554085", "23298", "SPOTTY BUNTING", 1, "2011-05-23 11:52", 4.95, 12909, "United Kingdom"],
    ])
    sales, _, _ = cl.clean(df)
    assert len(sales) == 2
