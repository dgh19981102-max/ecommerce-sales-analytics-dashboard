"""Interactive sales dashboard.

Run locally:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `src` importable on Streamlit Cloud
from src import analysis as an  # noqa: E402
from src.config import CLEANING_LOG_CSV, RETURNS_PARQUET, SALES_PARQUET  # noqa: E402

st.set_page_config(page_title="E-commerce Sales Analytics", page_icon="📊", layout="wide")

# ----------------------------------------------------------------------------- #
# Style
# ----------------------------------------------------------------------------- #
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
TEXT, MUTED, GRID = "#0b0b0b", "#52514e", "#e8e7e3"
SEQ_BLUES = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
  [data-testid="stMetric"] {background: #f7f7f5; border: 1px solid #e8e7e3; border-radius: 10px;
                            padding: 12px 16px;}
  [data-testid="stMetricLabel"] p {font-size: 0.85rem; color: #52514e;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
  h1 {font-size: 1.9rem !important;}
</style>
""", unsafe_allow_html=True)


def style(fig: go.Figure, height: int = 340, title: str | None = None) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=10, r=10, t=50 if title else 20, b=10),
        title=dict(text=title, font=dict(size=15, color=TEXT), x=0, xanchor="left") if title else None,
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color=MUTED),
        hoverlabel=dict(bgcolor="white", font_size=12), showlegend=False,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, title=None)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title=None)
    return fig


def gbp(x: float) -> str:
    if abs(x) >= 1e6:
        return f"£{x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"£{x / 1e3:,.1f}K"
    return f"£{x:,.0f}"


# ----------------------------------------------------------------------------- #
# Data (loaded once, cached)
# ----------------------------------------------------------------------------- #
@st.cache_resource(show_spinner="Loading data ...")  # shared, read-only: not copied on every rerun
def load():
    sales = pd.read_parquet(SALES_PARQUET)
    returns = pd.read_parquet(RETURNS_PARQUET)
    products = an.product_summary(sales)
    products["label"] = products["StockCode"] + " · " + products["description"].str.title()
    log = pd.read_csv(CLEANING_LOG_CSV) if CLEANING_LOG_CSV.exists() else pd.DataFrame()
    return sales, returns, products, log


def apply_filters(start, end, countries: tuple, codes: tuple):
    sales, returns, _, _ = load()

    def f(df):
        m = (df["InvoiceDate"] >= pd.Timestamp(start)) & (df["InvoiceDate"] < pd.Timestamp(end) + pd.Timedelta(days=1))
        if countries:
            m &= df["Country"].isin(countries)
        if codes:
            m &= df["StockCode"].isin(codes)
        return df[m]

    return f(sales), f(returns)


@st.cache_data(show_spinner=False)
def to_csv(start, end, countries: tuple, codes: tuple) -> bytes:
    s, _ = apply_filters(start, end, countries, codes)
    return s.to_csv(index=False).encode("utf-8")


@st.cache_data(show_spinner=False)
def full_insights() -> list[str]:
    s, r, _, _ = load()
    return an.executive_insights(s, r)


sales_all, returns_all, products_all, clean_log = load()
min_d, max_d = sales_all["InvoiceDate"].min().date(), sales_all["InvoiceDate"].max().date()

# ----------------------------------------------------------------------------- #
# Sidebar filters
# ----------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Filters")
    date_range = st.date_input("Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d)
    start, end = (date_range if isinstance(date_range, tuple) and len(date_range) == 2 else (min_d, max_d))
    country_opts = an.country_summary(sales_all)["Country"].tolist()  # sorted by revenue
    countries = st.multiselect("Country", country_opts, placeholder="All countries")
    prod_choice = st.multiselect("Product", products_all["label"].tolist(), placeholder="All products",
                                 help="Type a product name or stock code to search.")
    codes = tuple(products_all.loc[products_all["label"].isin(prod_choice), "StockCode"])
    st.divider()
    st.caption("Data: UCI Online Retail II (CC BY 4.0) - a UK online gift retailer, "
               "Dec 2009 - Dec 2011. Amounts in GBP.")

sales, returns = apply_filters(start, end, tuple(countries), codes)

st.title("E-commerce Sales Analytics")
st.caption(f"{start:%d %b %Y} – {end:%d %b %Y} · "
           f"{'All countries' if not countries else ', '.join(countries)} · "
           f"{'All products' if not codes else f'{len(codes)} product(s)'}")

if sales.empty:
    st.warning("No sales match these filters. Widen the date range or clear a filter.")
    st.stop()

# ----------------------------------------------------------------------------- #
# KPI cards (delta = vs the previous period of the same length)
# ----------------------------------------------------------------------------- #
k = an.kpis(sales, returns)
span = pd.Timestamp(end) - pd.Timestamp(start) + pd.Timedelta(days=1)
prev_start, prev_end = pd.Timestamp(start) - span, pd.Timestamp(start) - pd.Timedelta(days=1)
prev_s, prev_r = apply_filters(prev_start.date(), prev_end.date(), tuple(countries), codes)
kp = an.kpis(prev_s, prev_r) if len(prev_s) else None


def delta(key, pct=True):
    if not kp or not kp[key]:
        return None
    if key == "return_rate":
        return f"{(k[key] - kp[key]) * 100:+.1f} pp"
    return f"{k[key] / kp[key] - 1:+.1%}"


c = st.columns(5)
c[0].metric("Revenue", gbp(k["revenue"]), delta("revenue"))
c[1].metric("Orders", f"{k['orders']:,}", delta("orders"))
c[2].metric("Customers", f"{k['customers']:,}", delta("customers"))
c[3].metric("Avg order value", f"£{k['aov']:,.0f}", delta("aov"))
c[4].metric("Return rate", f"{k['return_rate']:.1%}", delta("return_rate"), delta_color="inverse")
if kp:
    st.caption(f"Deltas compare with the previous {span.days} days "
               f"({prev_start:%d %b %Y} – {prev_end:%d %b %Y}).")

tab_over, tab_prod, tab_cust, tab_geo, tab_find, tab_dq = st.tabs(
    ["Overview", "Products", "Customers", "Countries", "Key findings", "Data quality"])

# ----------------------------------------------------------------------------- #
# Overview
# ----------------------------------------------------------------------------- #
with tab_over:
    gran = st.radio("Granularity", ["Monthly", "Weekly", "Daily"], horizontal=True, label_visibility="collapsed")
    freq = {"Monthly": "MS", "Weekly": "W-MON", "Daily": "D"}[gran]
    tr = an.sales_trend(sales, freq)
    fig = go.Figure(go.Scatter(
        x=tr["period"], y=tr["revenue"], mode="lines+markers" if gran == "Monthly" else "lines",
        line=dict(color=BLUE, width=2), marker=dict(size=8, line=dict(color="white", width=2)),
        fill="tozeroy", fillcolor="rgba(42,120,214,0.08)",
        customdata=tr[["orders", "customers"]],
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Revenue £%{y:,.0f}<br>Orders %{customdata[0]:,}"
                      "<br>Customers %{customdata[1]:,}<extra></extra>"))
    fig.update_xaxes(hoverformat="%b %Y")
    st.plotly_chart(style(fig, 360, f"{gran} revenue"), width="stretch")
    if end >= pd.Timestamp("2011-12-01").date():
        st.caption("Note: December 2011 is a partial month (data ends 9 Dec 2011).")

    a, b = st.columns(2)
    wd = an.sales_by_weekday(sales)
    wd = wd[wd["orders"] > 0]
    fig = px.bar(wd, x="weekday", y="revenue", custom_data=["orders"])
    fig.update_traces(marker_color=BLUE, marker_cornerradius=4,
                      hovertemplate="<b>%{x}</b><br>Revenue £%{y:,.0f}<br>Orders %{customdata[0]:,}<extra></extra>")
    a.plotly_chart(style(fig, 300, "Revenue by day of week"), width="stretch")
    hr = an.sales_by_hour(sales)
    fig = px.bar(hr, x="hour", y="revenue", custom_data=["orders"])
    fig.update_traces(marker_color=BLUE, marker_cornerradius=4,
                      hovertemplate="<b>%{x}:00</b><br>Revenue £%{y:,.0f}<br>Orders %{customdata[0]:,}<extra></extra>")
    fig.update_xaxes(dtick=2, ticksuffix=":00")
    b.plotly_chart(style(fig, 300, "Revenue by hour of day"), width="stretch")
    st.caption("The shop records almost no Saturday orders - the business is closed on Saturdays.")

# ----------------------------------------------------------------------------- #
# Products
# ----------------------------------------------------------------------------- #
with tab_prod:
    a, b = st.columns([3, 2])
    metric = a.radio("Rank by", ["revenue", "units"], horizontal=True,
                     format_func=str.title, key="rank_by")
    tp = an.top_products(sales, 10, metric).iloc[::-1]
    tp["name"] = tp["description"].str.title().str.slice(0, 34)
    fig = px.bar(tp, x=metric, y="name", orientation="h", custom_data=["StockCode", "units", "revenue"])
    fig.update_traces(marker_color=BLUE, marker_cornerradius=4,
                      hovertemplate="<b>%{y}</b> (%{customdata[0]})<br>Revenue £%{customdata[2]:,.0f}"
                                    "<br>Units %{customdata[1]:,}<extra></extra>")
    a.plotly_chart(style(fig, 400, f"Top 10 products by {metric}"), width="stretch")

    prod_rev = sales.groupby("StockCode", observed=True)["Revenue"].sum()
    prod_rev = prod_rev[prod_rev > 0]
    curve = an.pareto(prod_rev)
    step = max(len(curve) // 400, 1)
    cv = curve.iloc[::step]
    top20 = an.top_share(prod_rev, 0.2)
    fig = go.Figure(go.Scatter(x=cv["rank_share"], y=cv["value_share"], mode="lines",
                               line=dict(color=BLUE, width=2),
                               hovertemplate="Top %{x:.0%} of products → %{y:.0%} of revenue<extra></extra>"))
    fig.add_shape(type="line", x0=0.2, x1=0.2, y0=0, y1=top20, line=dict(color=MUTED, dash="dot", width=1))
    fig.add_annotation(x=0.2, y=top20, text=f"Top 20% → {top20:.0%}", showarrow=False,
                       xanchor="left", yanchor="top", xshift=6, font=dict(color=TEXT))
    fig.update_xaxes(tickformat=".0%"); fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
    b.markdown(" ")
    b.plotly_chart(style(fig, 400, "Pareto: share of revenue by product"), width="stretch")

    st.subheader("Highest return rates", divider="gray")
    min_units = st.slider("Minimum units sold", 50, 2000, 500, 50,
                          help="Ignore low-volume products, where one return swings the rate.")
    rr = an.product_return_rates(sales, returns, min_units).head(15)
    if rr.empty:
        st.info("No product meets the minimum-units threshold for this selection.")
    else:
        st.dataframe(
            rr[["StockCode", "description", "units_sold", "units_returned", "return_rate", "value_returned"]].round({"value_returned": 0}),
            hide_index=True, width="stretch",
            column_config={
                "StockCode": "Code", "description": "Product",
                "units_sold": st.column_config.NumberColumn("Units sold", format="localized"),
                "units_returned": st.column_config.NumberColumn("Units returned", format="localized"),
                "return_rate": st.column_config.ProgressColumn("Return rate", format="percent",
                                                               min_value=0, max_value=1),
                "value_returned": st.column_config.NumberColumn("Value returned (£)", format="localized"),
            })

# ----------------------------------------------------------------------------- #
# Customers
# ----------------------------------------------------------------------------- #
with tab_cust:
    rfm = an.rfm_table(sales)
    if rfm.empty:
        st.info("No identified customers in this selection.")
    else:
        seg = an.rfm_segments(rfm)
        a, b = st.columns([1, 1.3])
        s2 = seg.iloc[::-1]
        fig = go.Figure([
            go.Bar(y=s2["segment"], x=s2["customer_share"], orientation="h", name="Share of customers",
                   marker=dict(color="#9ec5f4", cornerradius=4),
                   customdata=s2[["customers"]],
                   hovertemplate="<b>%{y}</b><br>%{customdata[0]:,} customers (%{x:.1%})<extra></extra>"),
            go.Bar(y=s2["segment"], x=s2["revenue_share"], orientation="h", name="Share of revenue",
                   marker=dict(color=BLUE, cornerradius=4),
                   customdata=s2[["revenue"]],
                   hovertemplate="<b>%{y}</b><br>£%{customdata[0]:,.0f} revenue (%{x:.1%})<extra></extra>"),
        ])
        fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
        fig.update_xaxes(tickformat=".0%")
        style(fig, 430, "RFM segments: customers vs revenue")
        fig.update_layout(showlegend=True, legend=dict(orientation="h", y=-0.12, x=0, title=None))
        a.plotly_chart(fig, width="stretch")

        with b:
            st.markdown("**Segment profile**")
            st.dataframe(
                seg[["segment", "customers", "revenue", "avg_recency", "avg_frequency", "avg_monetary"]].round({"revenue": 0, "avg_monetary": 0}),
                hide_index=True, width="stretch", height=390,
                column_config={
                    "segment": "Segment", "customers": st.column_config.NumberColumn("Customers", format="localized"),
                    "revenue": st.column_config.NumberColumn("Revenue (£)", format="localized"),
                    "avg_recency": st.column_config.NumberColumn("Days idle", format="%.0f", help="Average days since last order"),
                    "avg_frequency": st.column_config.NumberColumn("Orders", format="%.1f"),
                    "avg_monetary": st.column_config.NumberColumn("£ / cust.", format="localized"),
                })
        st.caption("RFM = Recency (days since last order), Frequency (number of orders), Monetary (total spend). "
                   "Each is scored 1–5 by quintile; segments come from the R and F scores. "
                   "Champions: bought recently and often – reward them. At Risk / Can't Lose Them: used to buy "
                   "often but have gone quiet – win-back campaign. Hibernating: low value and inactive.")

        st.subheader("Monthly cohort retention", divider="gray")
        ret = an.cohort_retention(sales, max_months=12)
        if ret.shape[1] > 1:
            z = ret.values * 100
            text = [[f"{v:.0f}%" if pd.notna(v) else "" for v in row] for row in z]
            fig = go.Figure(go.Heatmap(
                z=z, x=[f"M{c}" for c in ret.columns], y=ret.index, text=text, texttemplate="%{text}",
                textfont=dict(size=10), colorscale=[[i / (len(SEQ_BLUES) - 1), c] for i, c in enumerate(SEQ_BLUES)],
                zmin=0, zmax=60, xgap=2, ygap=2, colorbar=dict(title="%", thickness=10),
                hovertemplate="Cohort %{y}, month %{x}: %{z:.1f}% active<extra></extra>"))
            fig.update_yaxes(autorange="reversed", type="category", gridcolor="rgba(0,0,0,0)")
            st.plotly_chart(style(fig, 520), width="stretch")
            st.caption("Each row is the month a customer first bought. M1 = share of that cohort who bought again "
                       "one month later, etc. M0 is always 100% (colour capped at 60% so later months stay "
                       "readable). The Dec-2009 cohort includes customers who had bought before the data starts, "
                       "so it looks unusually loyal. Blank cells lie after the data ends; the last "
                       "value on each row falls in the partial December 2011, so it is understated.")

# ----------------------------------------------------------------------------- #
# Countries
# ----------------------------------------------------------------------------- #
with tab_geo:
    cs = an.country_summary(sales)
    excl_uk = st.toggle("Exclude United Kingdom (to compare international markets)", value=True)
    view = cs[cs["Country"] != "United Kingdom"] if excl_uk else cs
    a, b = st.columns([3, 2])
    top = view.head(15).iloc[::-1]
    fig = px.bar(top, x="revenue", y="Country", orientation="h", custom_data=["orders", "customers", "aov"])
    fig.update_traces(marker_color=BLUE, marker_cornerradius=4,
                      hovertemplate="<b>%{y}</b><br>Revenue £%{x:,.0f}<br>Orders %{customdata[0]:,}"
                                    "<br>Customers %{customdata[1]:,}<br>AOV £%{customdata[2]:,.0f}<extra></extra>")
    a.plotly_chart(style(fig, 470, "Top 15 countries by revenue"), width="stretch")
    with b:
        st.markdown(" ")
        st.dataframe(view.head(15)[["Country", "revenue", "revenue_share", "orders", "aov"]].round({"revenue": 0, "aov": 0}), hide_index=True,
                     width="stretch", height=450,
                     column_config={
                         "revenue": st.column_config.NumberColumn("Revenue (£)", format="localized"),
                         "revenue_share": st.column_config.NumberColumn("Share", format="percent"),
                         "orders": st.column_config.NumberColumn("Orders", format="localized"),
                         "aov": st.column_config.NumberColumn("Avg order (£)", format="localized")})

# ----------------------------------------------------------------------------- #
# Key findings & data quality
# ----------------------------------------------------------------------------- #
with tab_find:
    st.markdown("Computed live on the **full dataset** – they don't change with the filters.")
    for i, txt in enumerate(full_insights(), 1):
        st.markdown(f"{i}. {txt}")

with tab_dq:
    st.markdown("Every cleaning rule, how many rows it removed and why. Source: `src/cleaning.py`.")
    if not clean_log.empty:
        st.dataframe(clean_log.drop(columns="reason").round({"value_removed_gbp": 0}),
                     hide_index=True, width="stretch",
                     column_config={
                         "step": "Step", "rows_before": st.column_config.NumberColumn("Rows before", format="localized"),
                         "rows_removed": st.column_config.NumberColumn("Removed", format="localized"),
                         "rows_after": st.column_config.NumberColumn("Rows after", format="localized"),
                         "pct_removed": st.column_config.NumberColumn("% removed", format="%.2f"),
                         "value_removed_gbp": st.column_config.NumberColumn("Value removed (£)", format="localized")})
        st.markdown("**Why each step**")
        st.markdown("\n".join(f"- **{r.step}** – {r.reason}" for r in clean_log.itertuples()))

st.divider()
if len(sales) <= 150_000:
    st.download_button("Download filtered sales lines (CSV)", to_csv(start, end, tuple(countries), codes),
                       file_name="filtered_sales.csv", mime="text/csv")
else:
    st.caption(f"Narrow the filters to under 150,000 sales lines (currently {len(sales):,}) "
               "to download the raw lines as CSV.")
