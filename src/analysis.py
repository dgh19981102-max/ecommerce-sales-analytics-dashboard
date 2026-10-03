"""Step 2 - reusable analysis functions.

The same functions feed the notebook, the dashboard and the Excel report, so the
numbers are identical everywhere. Each function takes the cleaned `sales`
(and sometimes `returns`) DataFrame and returns a small, tidy DataFrame or dict.

Usage (writes reports/insights.md):
    python -m src.analysis
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import INSIGHTS_MD, RETURNS_PARQUET, SALES_PARQUET

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def load_clean() -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.read_parquet(SALES_PARQUET), pd.read_parquet(RETURNS_PARQUET)


# --------------------------------------------------------------------------- #
# Headline KPIs
# --------------------------------------------------------------------------- #
def kpis(sales: pd.DataFrame, returns: pd.DataFrame | None = None) -> dict:
    revenue = float(sales["Revenue"].sum())
    orders = int(sales["Invoice"].nunique())
    returned_value = float(-returns["Revenue"].sum()) if returns is not None and len(returns) else 0.0
    return {
        "revenue": revenue,
        "orders": orders,
        "customers": int(sales["Customer ID"].nunique()),
        "units": int(sales["Quantity"].sum()),
        "aov": revenue / orders if orders else 0.0,             # average order value
        "returned_value": returned_value,
        "return_rate": returned_value / revenue if revenue else 0.0,  # share of sales value returned
    }


# --------------------------------------------------------------------------- #
# Sales trends
# --------------------------------------------------------------------------- #
def sales_trend(sales: pd.DataFrame, freq: str = "MS") -> pd.DataFrame:
    """Revenue, orders and customers per period. freq: 'D' day, 'W-MON' week, 'MS' month."""
    g = sales.groupby(pd.Grouper(key="InvoiceDate", freq=freq))
    out = g.agg(revenue=("Revenue", "sum"), orders=("Invoice", "nunique"),
                customers=("Customer ID", "nunique")).reset_index()
    out = out.rename(columns={"InvoiceDate": "period"})
    out["aov"] = out["revenue"] / out["orders"].replace(0, np.nan)
    return out


def sales_by_weekday(sales: pd.DataFrame) -> pd.DataFrame:
    s = sales.assign(dow=sales["InvoiceDate"].dt.dayofweek)  # 0 = Monday
    out = s.groupby("dow").agg(revenue=("Revenue", "sum"), orders=("Invoice", "nunique")).reindex(range(7)).fillna(0)
    out.insert(0, "weekday", WEEKDAYS)
    return out.reset_index(drop=True)


def sales_by_hour(sales: pd.DataFrame) -> pd.DataFrame:
    s = sales.assign(hour=sales["InvoiceDate"].dt.hour)
    return s.groupby("hour").agg(revenue=("Revenue", "sum"), orders=("Invoice", "nunique")).reset_index()


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
def product_summary(sales: pd.DataFrame) -> pd.DataFrame:
    out = (sales.groupby("StockCode", observed=True)
           .agg(description=("Description", "first"), revenue=("Revenue", "sum"),
                units=("Quantity", "sum"), orders=("Invoice", "nunique"))
           .sort_values("revenue", ascending=False).reset_index())
    out["StockCode"] = out["StockCode"].astype(str)
    out["description"] = out["description"].astype(str)
    return out


def top_products(sales: pd.DataFrame, n: int = 10, by: str = "revenue") -> pd.DataFrame:
    return product_summary(sales).nlargest(n, by).reset_index(drop=True)


def pareto(values: pd.Series) -> pd.DataFrame:
    """Cumulative share curve for any 'amount per entity' series (products or customers)."""
    v = values.sort_values(ascending=False).to_numpy()
    total = v.sum()
    return pd.DataFrame({
        "rank_share": np.arange(1, len(v) + 1) / len(v),     # x: top x% of entities
        "value_share": np.cumsum(v) / total if total else 0, # y: share of total value
    })


def top_share(values: pd.Series, top_fraction: float = 0.2) -> float:
    """Share of total value contributed by the top `top_fraction` of entities."""
    v = values.sort_values(ascending=False)
    k = max(int(np.ceil(len(v) * top_fraction)), 1)
    return float(v.iloc[:k].sum() / v.sum()) if v.sum() else 0.0


def share_needed_for(values: pd.Series, target: float = 0.8) -> float:
    """Smallest fraction of entities that together make `target` of the total."""
    curve = pareto(values)
    return float(curve.loc[curve["value_share"] >= target, "rank_share"].iloc[0])


def product_return_rates(sales: pd.DataFrame, returns: pd.DataFrame, min_units: int = 500) -> pd.DataFrame:
    """Returned units / sold units per product. Products with < min_units sold are ignored (too noisy)."""
    sold = sales.groupby("StockCode", observed=True).agg(
        description=("Description", "first"), units_sold=("Quantity", "sum"), revenue=("Revenue", "sum"))
    ret = returns.groupby("StockCode", observed=True).agg(
        units_returned=("Quantity", lambda q: -q.sum()), value_returned=("Revenue", lambda r: -r.sum()))
    out = sold.join(ret, how="left").fillna({"units_returned": 0, "value_returned": 0})
    out = out[out["units_sold"] >= min_units]
    out["return_rate"] = out["units_returned"] / out["units_sold"]
    out = out.sort_values("return_rate", ascending=False).reset_index()
    out["StockCode"] = out["StockCode"].astype(str)
    out["description"] = out["description"].astype(str)
    return out


# --------------------------------------------------------------------------- #
# Customers: RFM segmentation
# --------------------------------------------------------------------------- #
# Classic RFM segment map keyed on (Recency score, Frequency score), each 1..5.
SEGMENT_MAP = [
    (r"[1-2][1-2]", "Hibernating"),
    (r"[1-2][3-4]", "At Risk"),
    (r"[1-2]5", "Can't Lose Them"),
    (r"3[1-2]", "About to Sleep"),
    (r"33", "Need Attention"),
    (r"[3-4][4-5]", "Loyal Customers"),
    (r"41", "Promising"),
    (r"51", "New Customers"),
    (r"[4-5][2-3]", "Potential Loyalists"),
    (r"5[4-5]", "Champions"),
]
SEGMENT_ORDER = ["Champions", "Loyal Customers", "Potential Loyalists", "New Customers", "Promising",
                 "Need Attention", "About to Sleep", "At Risk", "Can't Lose Them", "Hibernating"]


def rfm_table(sales: pd.DataFrame, snapshot: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per known customer with Recency (days), Frequency (orders), Monetary (GBP),
    1-5 scores (5 = best) and a named segment."""
    known = sales[sales["Customer ID"].notna()]
    if known.empty:
        return pd.DataFrame(columns=["Customer ID", "recency", "frequency", "monetary",
                                     "R", "F", "M", "segment"])
    if snapshot is None:
        snapshot = known["InvoiceDate"].max().normalize() + pd.Timedelta(days=1)
    rfm = known.groupby("Customer ID").agg(
        last_purchase=("InvoiceDate", "max"),
        frequency=("Invoice", "nunique"),
        monetary=("Revenue", "sum"),
    )
    rfm["recency"] = (snapshot - rfm["last_purchase"]).dt.days

    def score(s: pd.Series, ascending: bool) -> pd.Series:
        # rank first to break ties, then cut into 5 equal-sized groups
        r = s.rank(method="first", ascending=ascending)
        q = min(5, len(s))
        return pd.qcut(r, q, labels=range(1, q + 1)).astype(int)

    rfm["R"] = score(rfm["recency"], ascending=False)   # recent = high score
    rfm["F"] = score(rfm["frequency"], ascending=True)
    rfm["M"] = score(rfm["monetary"], ascending=True)
    rf = rfm["R"].astype(str) + rfm["F"].astype(str)
    rfm["segment"] = "Other"
    for pattern, name in SEGMENT_MAP:
        rfm.loc[rf.str.fullmatch(pattern), "segment"] = name
    return rfm.drop(columns="last_purchase").reset_index()


def rfm_segments(rfm: pd.DataFrame) -> pd.DataFrame:
    seg = rfm.groupby("segment").agg(
        customers=("Customer ID", "count"), revenue=("monetary", "sum"),
        avg_recency=("recency", "mean"), avg_frequency=("frequency", "mean"),
        avg_monetary=("monetary", "mean"))
    seg["customer_share"] = seg["customers"] / seg["customers"].sum()
    seg["revenue_share"] = seg["revenue"] / seg["revenue"].sum()
    order = [s for s in SEGMENT_ORDER if s in seg.index]
    return seg.reindex(order).reset_index()


# --------------------------------------------------------------------------- #
# Customers: monthly cohort retention
# --------------------------------------------------------------------------- #
def cohort_retention(sales: pd.DataFrame, max_months: int = 12) -> pd.DataFrame:
    """Rows = month of first purchase, columns = months since first purchase (0..max_months),
    values = share of the cohort that bought again in that month."""
    known = sales.loc[sales["Customer ID"].notna(), ["Customer ID", "InvoiceDate"]]
    if known.empty:
        return pd.DataFrame()
    # month number as an integer (e.g. 2010*12 + 1) -> fast arithmetic on "months since"
    month = known["InvoiceDate"].dt.year * 12 + known["InvoiceDate"].dt.month - 1
    first = month.groupby(known["Customer ID"]).transform("min")
    age = month - first
    counts = (pd.DataFrame({"cohort": first, "age": age, "cid": known["Customer ID"]})
              .drop_duplicates()
              .groupby(["cohort", "age"]).size().unstack(fill_value=0))
    if 0 not in counts.columns:
        return pd.DataFrame()
    retention = counts.div(counts[0], axis=0).astype(float)
    # months that lie after the end of the data are unknown, not 0% -> blank them out
    last = int(month.max())
    for cohort in retention.index:
        retention.loc[cohort, [a for a in retention.columns if cohort + a > last]] = np.nan
    retention = retention.loc[:, [c for c in retention.columns if c <= max_months]]
    retention.index = [f"{m // 12}-{m % 12 + 1:02d}" for m in retention.index]  # e.g. "2010-01"
    retention.index.name = "cohort"
    return retention


# --------------------------------------------------------------------------- #
# Geography
# --------------------------------------------------------------------------- #
def country_summary(sales: pd.DataFrame) -> pd.DataFrame:
    out = (sales.groupby("Country", observed=True)
           .agg(revenue=("Revenue", "sum"), orders=("Invoice", "nunique"),
                customers=("Customer ID", "nunique"))
           .sort_values("revenue", ascending=False).reset_index())
    out["Country"] = out["Country"].astype(str)
    out["aov"] = out["revenue"] / out["orders"]
    out["revenue_share"] = out["revenue"] / out["revenue"].sum()
    return out


# --------------------------------------------------------------------------- #
# Executive insights (every sentence carries a number)
# --------------------------------------------------------------------------- #
def executive_insights(sales: pd.DataFrame, returns: pd.DataFrame) -> list[str]:
    insights = []

    # 1. Customer concentration
    cust_rev = sales.dropna(subset=["Customer ID"]).groupby("Customer ID")["Revenue"].sum()
    rfm = rfm_table(sales)
    seg = rfm_segments(rfm).set_index("segment")
    champ = seg.loc["Champions"] if "Champions" in seg.index else None
    txt = (f"**Customers are highly concentrated:** the top 20% of identified customers generate "
           f"{top_share(cust_rev, 0.2):.0%} of identified-customer revenue")
    if champ is not None:
        txt += (f", and the {int(champ.customers):,} 'Champions' ({champ.customer_share:.0%} of customers) "
                f"alone bring in {champ.revenue_share:.0%}. Losing a handful of key accounts is the "
                f"single biggest revenue risk.")
    insights.append(txt)

    # 2. Product long tail
    prod_rev = sales.groupby("StockCode", observed=True)["Revenue"].sum()
    insights.append(
        f"**A small catalogue core drives sales:** {share_needed_for(prod_rev, 0.8):.0%} of the "
        f"{len(prod_rev):,} products produce 80% of revenue; the top 20% produce "
        f"{top_share(prod_rev, 0.2):.0%}. The long tail is a candidate for stock rationalisation.")

    # 3. Seasonality: Sep-Nov vs the rest (use full year 2010 and 2011 through Nov)
    m = sales_trend(sales, "MS").set_index("period")["revenue"]
    full = m[(m.index >= "2010-01-01") & (m.index < "2011-12-01")]
    q4 = full[full.index.month.isin([9, 10, 11])]
    rest = full[~full.index.month.isin([9, 10, 11])]
    peak = full.idxmax()
    insights.append(
        f"**Strong pre-Christmas season:** September-November months average "
        f"£{q4.mean():,.0f} in revenue vs £{rest.mean():,.0f} in other months "
        f"(+{q4.mean() / rest.mean() - 1:.0%}). The peak month was {peak:%B %Y} "
        f"(£{full.max():,.0f}). Stock and staffing should be planned from August.")

    # 4. Retention
    ret = cohort_retention(sales)
    m1 = ret[1].mean() if 1 in ret.columns else np.nan
    one_time = (rfm["frequency"] == 1).mean()
    insights.append(
        f"**Retention is the growth lever:** on average only {m1:.0%} of new customers buy again in "
        f"their second month, and {one_time:.0%} of identified customers ordered only once. "
        f"A welcome / second-order campaign targets the largest leak.")

    # 5. Geography & returns
    cs = country_summary(sales)
    uk = cs.loc[cs["Country"] == "United Kingdom"].iloc[0]
    intl = cs[cs["Country"] != "United Kingdom"]
    k = kpis(sales, returns)
    insights.append(
        f"**UK-heavy, but overseas orders are bigger:** the UK is {uk.revenue_share:.0%} of revenue, "
        f"yet the average non-UK order is £{intl['revenue'].sum() / intl['orders'].sum():,.0f} vs "
        f"£{uk.aov:,.0f} for the UK. Returns cost £{k['returned_value']:,.0f} "
        f"({k['return_rate']:.1%} of sales value).")
    return insights


def main() -> None:
    sales, returns = load_clean()
    k = kpis(sales, returns)
    lines = ["# Key findings", "",
             f"Data: {sales['InvoiceDate'].min():%d %b %Y} - {sales['InvoiceDate'].max():%d %b %Y}, "
             f"£{k['revenue']:,.0f} revenue, {k['orders']:,} orders, {k['customers']:,} identified customers.",
             ""]
    for i, s in enumerate(executive_insights(sales, returns), 1):
        lines.append(f"{i}. {s}")
    INSIGHTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
