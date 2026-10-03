"""Project-wide paths and constants. Everything else imports from here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = ROOT / "reports"

RAW_PARQUET = RAW_DIR / "online_retail_II.parquet"
SALES_PARQUET = PROCESSED_DIR / "sales_clean.parquet"      # one row per cleaned sales line
RETURNS_PARQUET = PROCESSED_DIR / "returns_clean.parquet"  # one row per cleaned return (cancellation) line
CLEANING_LOG_CSV = REPORTS_DIR / "cleaning_log.csv"
CLEANING_LOG_MD = REPORTS_DIR / "cleaning_log.md"
INSIGHTS_MD = REPORTS_DIR / "insights.md"

# Official source (UCI Machine Learning Repository, CC BY 4.0).
UCI_ZIP_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
# Fallback mirror: the same 1,067,371 rows packaged in the CRAN package `onlineretail2`.
MIRROR_RDA_URL = "https://raw.githubusercontent.com/allanvc/onlineretail2/master/data/onlineretail2.rda"

# Stock codes that are NOT physical products: postage, fees, manual adjustments, tests, vouchers.
# Found by listing every StockCode that does not start with 5 digits and reading its Description
# (see notebooks/01_data_cleaning.ipynb). "DCGS..." codes are real items from the Dotcom gift shop,
# so they are kept.
NON_PRODUCT_CODES = {
    "POST", "DOT", "C2", "C3",             # postage / carriage
    "M", "m",                              # manual price corrections
    "D",                                   # discount lines
    "S",                                   # samples
    "B",                                   # adjust bad debt
    "BANK CHARGES", "AMAZONFEE", "CRUK",   # fees / commissions
    "ADJUST", "ADJUST2",                   # stock adjustments
    "PADS",                                # 0.001 GBP filler item
    "TEST001", "TEST002",                  # test products
    "GIFT", "DCGSSBOY", "DCGSSGIRL", "DCGSLBOY", "DCGSLGIRL",  # vouchers / "update" lines
}
NON_PRODUCT_PREFIXES = ("gift_0001",)      # gift vouchers gift_0001_10 ... gift_0001_90

# Bulk lines (>= this quantity) that were cancelled in full are treated as data-entry mistakes.
BULK_QTY_THRESHOLD = 1000

# Country names normalised to something a client would recognise.
COUNTRY_RENAMES = {
    "EIRE": "Ireland",
    "RSA": "South Africa",
    "USA": "United States",
    "Korea": "South Korea",
}
