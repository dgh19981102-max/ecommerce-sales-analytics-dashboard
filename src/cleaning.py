"""Step 1 - clean the raw transactions and write an audit log of every step.

Usage:
    python -m src.cleaning

Input : data/raw/online_retail_II.parquet   (1,067,371 raw invoice lines)
Output: data/processed/sales_clean.parquet  (cleaned sales lines)
        data/processed/returns_clean.parquet (cleaned return / cancellation lines)
        reports/cleaning_log.csv + reports/cleaning_log.md

Every rule is a small pure function (DataFrame in -> DataFrame out) so it can be
unit-tested on its own (see tests/test_cleaning.py). The `CleaningLog` records how
many rows (and how much money) each rule removed and *why*.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.config import (BULK_QTY_THRESHOLD, CLEANING_LOG_CSV, CLEANING_LOG_MD,
                        COUNTRY_RENAMES, NON_PRODUCT_CODES, NON_PRODUCT_PREFIXES,
                        PROCESSED_DIR, RAW_PARQUET, RETURNS_PARQUET, SALES_PARQUET)


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
@dataclass
class CleaningLog:
    rows: list[dict] = field(default_factory=list)

    def record(self, step: str, before: pd.DataFrame, after: pd.DataFrame, reason: str) -> None:
        removed = before.loc[before.index.difference(after.index)]
        self.rows.append({
            "step": step,
            "rows_before": len(before),
            "rows_removed": len(removed),
            "rows_after": len(after),
            "pct_removed": round(100 * len(removed) / max(len(before), 1), 2),
            "value_removed_gbp": round(float((removed["Quantity"] * removed["Price"]).sum()), 2),
            "reason": reason,
        })

    def note(self, step: str, rows: int, reason: str) -> None:
        """A step that changes/flags rows without deleting them."""
        self.rows.append({"step": step, "rows_before": rows, "rows_removed": 0,
                          "rows_after": rows, "pct_removed": 0.0,
                          "value_removed_gbp": 0.0, "reason": reason})

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


# --------------------------------------------------------------------------- #
# Individual rules (pure functions)
# --------------------------------------------------------------------------- #
def is_cancellation(df: pd.DataFrame) -> pd.Series:
    """Invoices starting with 'C' are cancellations / returns."""
    return df["Invoice"].str.upper().str.startswith("C")


def is_non_product(df: pd.DataFrame) -> pd.Series:
    code = df["StockCode"]
    return code.isin(NON_PRODUCT_CODES) | code.str.startswith(NON_PRODUCT_PREFIXES)


def drop_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Rows identical in every column are double-recorded lines (same invoice, item, minute, qty, price)."""
    return df[~df.duplicated(keep="first")]


def drop_non_products(df: pd.DataFrame) -> pd.DataFrame:
    """Postage, fees, manual adjustments, bad-debt write-offs, tests and vouchers are not product sales."""
    return df[~is_non_product(df)]


def drop_non_positive_price(df: pd.DataFrame) -> pd.DataFrame:
    """Price <= 0 lines are free samples, damages, 'lost', 'given away' and other stock movements."""
    return df[df["Price"] > 0]


def drop_stock_adjustments(df: pd.DataFrame) -> pd.DataFrame:
    """A normal invoice (not 'C') must have a positive quantity; otherwise it is an inventory correction."""
    return df[is_cancellation(df) | (df["Quantity"] > 0)]


def drop_reversed_bulk_orders(df: pd.DataFrame, threshold: int = BULK_QTY_THRESHOLD) -> pd.DataFrame:
    """Remove huge orders that were cancelled in full (e.g. 80,995 paper crafts bought and cancelled
    12 minutes later). They never turned into real sales and would distort revenue AND return rates.

    A sale line is 'reversed' if a cancellation line exists with the same customer, same stock code
    and exactly the negative quantity. Both the sale and the cancellation are removed.
    """
    keys = ["Customer ID", "StockCode", "AbsQty"]
    tmp = df.assign(AbsQty=df["Quantity"].abs())
    big = tmp[(tmp["AbsQty"] >= threshold) & tmp["Customer ID"].notna()]
    sales = big[~is_cancellation(big)]
    cancels = big[is_cancellation(big)]
    pairs = sales.reset_index().merge(cancels.reset_index(), on=keys, suffixes=("_s", "_c"))
    to_drop = set(pairs["index_s"]) | set(pairs["index_c"])
    return df.drop(index=list(to_drop))


def standardise_text(df: pd.DataFrame) -> pd.DataFrame:
    """One product name per StockCode (the most frequent spelling) and readable country names."""
    df = df.copy()
    desc = df["Description"].astype("string").str.strip().str.upper()
    canonical = (desc.groupby(df["StockCode"]).agg(lambda s: s.mode().iat[0] if s.notna().any() else pd.NA))
    df["Description"] = df["StockCode"].map(canonical).fillna("UNKNOWN ITEM").astype(str)
    df["Country"] = df["Country"].replace(COUNTRY_RENAMES)
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derived columns used by the analysis and the dashboard."""
    df = df.copy()
    df["Revenue"] = (df["Quantity"] * df["Price"]).round(2)
    df["InvoiceDay"] = df["InvoiceDate"].dt.normalize()
    df["InvoiceMonth"] = df["InvoiceDate"].dt.to_period("M").dt.to_timestamp()
    df["IsGuest"] = df["Customer ID"].isna()
    return df


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run all rules in order. Returns (sales, returns, log_df)."""
    log = CleaningLog()
    df = raw.copy()
    log.note("0. Raw data loaded", len(df), "Both Excel sheets (Dec-2009 to Dec-2011) combined.")

    # Text first: lines that differ only in spelling ("BUNTING , SPOTTY" vs "SPOTTY BUNTING") are duplicates too.
    df = standardise_text(df)
    log.note("1. Standardise product names & countries", len(df),
             "One name per StockCode (most frequent spelling); EIRE -> Ireland, RSA -> South Africa, etc. "
             "Done first so that duplicates differing only in spelling are caught in step 2.")

    steps = [
        ("2. Remove exact duplicate rows", drop_duplicates,
         "Same invoice, product, time, quantity and price recorded twice - would double-count revenue."),
        ("3. Remove non-product lines", drop_non_products,
         "Postage, Amazon fees, bank charges, manual adjustments, bad-debt write-offs, test items and "
         "gift vouchers are not merchandise sales."),
        ("4. Remove zero / negative prices", drop_non_positive_price,
         "Price <= 0 lines are damaged / lost / given-away stock movements, not customer purchases."),
        ("5. Remove stock adjustments", drop_stock_adjustments,
         "Safety net: a normal invoice (not 'C') with quantity <= 0 is an inventory correction. "
         "In this dataset step 4 already catches all of them, so 0 rows is expected."),
        ("6. Remove reversed bulk orders", drop_reversed_bulk_orders,
         f"Orders of >= {BULK_QTY_THRESHOLD:,} units cancelled in full by the same customer "
         "(data-entry mistakes such as 80,995 x paper craft)."),
    ]
    for name, func, reason in steps:
        before = df
        df = func(df)
        log.record(name, before, df, reason)

    df = add_features(df)
    cancel = is_cancellation(df)
    sales = df[~cancel].reset_index(drop=True)
    returns = df[cancel].reset_index(drop=True)
    log.note("7. Split sales vs returns", len(df),
             f"{len(sales):,} sales lines and {len(returns):,} return lines ('C' invoices). "
             "Returns are kept separately for return-rate analysis.")
    guests = int(sales["IsGuest"].sum())
    log.note("8. Flag missing Customer ID (kept)", len(sales),
             f"{guests:,} sales lines ({guests / len(sales):.1%}) have no Customer ID. Kept for revenue "
             "and product analysis, excluded only from customer analysis (RFM, cohorts).")
    return sales, returns, log.to_frame()


def write_log_markdown(log_df: pd.DataFrame, path=CLEANING_LOG_MD) -> None:
    lines = ["# Data cleaning log", "",
             "| Step | Rows before | Removed | % | Value removed (GBP) | Rows after | Why |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for r in log_df.itertuples():
        lines.append(f"| {r.step} | {r.rows_before:,} | {r.rows_removed:,} | {r.pct_removed} | "
                     f"{r.value_removed_gbp:,.0f} | {r.rows_after:,} | {r.reason} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    raw = pd.read_parquet(RAW_PARQUET)
    sales, returns, log_df = clean(raw)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    CLEANING_LOG_CSV.parent.mkdir(parents=True, exist_ok=True)

    # Compact storage so the app loads fast and the repo stays small.
    keep = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price",
            "Customer ID", "Country", "Revenue"]
    for frame, path in [(sales, SALES_PARQUET), (returns, RETURNS_PARQUET)]:
        out = frame[keep].copy()
        for col in ["Invoice", "StockCode", "Description", "Country"]:
            out[col] = out[col].astype("category")
        out["Price"] = out["Price"].astype("float32")
        out["Quantity"] = out["Quantity"].astype("int32")
        out.to_parquet(path, index=False, compression="zstd")

    log_df.to_csv(CLEANING_LOG_CSV, index=False)
    write_log_markdown(log_df)
    print(log_df[["step", "rows_before", "rows_removed", "rows_after", "value_removed_gbp"]].to_string(index=False))
    print(f"\nSaved {SALES_PARQUET} ({len(sales):,} rows) and {RETURNS_PARQUET} ({len(returns):,} rows)")


if __name__ == "__main__":
    main()
