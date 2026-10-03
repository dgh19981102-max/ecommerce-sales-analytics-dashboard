"""Step 0 - download the raw data and store it as one fast-loading parquet file.

Usage:
    python -m src.download_data

Tries the official UCI zip first (contains online_retail_II.xlsx with two sheets,
2009-2010 and 2010-2011). If UCI is unreachable it falls back to a public mirror
of the identical dataset. Either way the result is data/raw/online_retail_II.parquet.
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from src.config import MIRROR_RDA_URL, RAW_DIR, RAW_PARQUET, UCI_ZIP_URL

COLUMNS = ["Invoice", "StockCode", "Description", "Quantity",
           "InvoiceDate", "Price", "Customer ID", "Country"]


def _fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_from_uci() -> pd.DataFrame:
    print(f"Downloading {UCI_ZIP_URL} ...")
    content = _fetch(UCI_ZIP_URL)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xlsx_name = next(n for n in zf.namelist() if n.endswith(".xlsx"))
        xlsx_bytes = zf.read(xlsx_name)
    (RAW_DIR / "online_retail_II.xlsx").write_bytes(xlsx_bytes)
    print("Reading both Excel sheets (this takes 1-3 minutes, only once) ...")
    sheets = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=None,
                           dtype={"Invoice": str, "StockCode": str})
    return pd.concat(sheets.values(), ignore_index=True)


def load_from_mirror() -> pd.DataFrame:
    import pyreadr  # only needed for the fallback

    print(f"Downloading mirror {MIRROR_RDA_URL} ...")
    tmp = RAW_DIR / "onlineretail2.rda"
    tmp.write_bytes(_fetch(MIRROR_RDA_URL))
    df = next(iter(pyreadr.read_r(str(tmp)).values()))
    return df.rename(columns={"CustomerID": "Customer ID"})


def standardise_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df[COLUMNS].copy()
    df["Invoice"] = df["Invoice"].astype(str).str.strip()
    df["StockCode"] = df["StockCode"].astype(str).str.strip()
    df["Description"] = df["Description"].astype("string")
    df["Quantity"] = pd.to_numeric(df["Quantity"]).astype("int64")
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"]).astype("datetime64[ns]")
    df["Price"] = pd.to_numeric(df["Price"]).astype("float64")
    df["Customer ID"] = pd.to_numeric(df["Customer ID"]).astype("Int64")
    df["Country"] = df["Country"].astype(str).str.strip()
    return df


def main() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if RAW_PARQUET.exists():
        print(f"{RAW_PARQUET} already exists - nothing to do.")
        return RAW_PARQUET
    try:
        df = load_from_uci()
    except Exception as exc:  # network blocked, site down, ...
        print(f"UCI download failed ({exc!r}); using mirror instead.", file=sys.stderr)
        df = load_from_mirror()
    df = standardise_types(df)
    df.to_parquet(RAW_PARQUET, index=False)
    print(f"Saved {len(df):,} rows -> {RAW_PARQUET}")
    return RAW_PARQUET


if __name__ == "__main__":
    main()
