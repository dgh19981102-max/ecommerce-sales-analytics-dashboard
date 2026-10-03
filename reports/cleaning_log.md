# Data cleaning log

| Step | Rows before | Removed | % | Value removed (GBP) | Rows after | Why |
|---|---:|---:|---:|---:|---:|---|
| 0. Raw data loaded | 1,067,371 | 0 | 0.0 | 0 | 1,067,371 | Both Excel sheets (Dec-2009 to Dec-2011) combined. |
| 1. Standardise product names & countries | 1,067,371 | 0 | 0.0 | 0 | 1,067,371 | One name per StockCode (most frequent spelling); EIRE -> Ireland, RSA -> South Africa, etc. Done first so that duplicates differing only in spelling are caught in step 2. |
| 2. Remove exact duplicate rows | 1,067,371 | 34,337 | 3.22 | 432,269 | 1,033,034 | Same invoice, product, time, quantity and price recorded twice - would double-count revenue. |
| 3. Remove non-product lines | 1,033,034 | 5,870 | 0.57 | -71,355 | 1,027,164 | Postage, Amazon fees, bank charges, manual adjustments, bad-debt write-offs, test items and gift vouchers are not merchandise sales. |
| 4. Remove zero / negative prices | 1,027,164 | 5,956 | 0.58 | 0 | 1,021,208 | Price <= 0 lines are damaged / lost / given-away stock movements, not customer purchases. |
| 5. Remove stock adjustments | 1,021,208 | 0 | 0.0 | 0 | 1,021,208 | Safety net: a normal invoice (not 'C') with quantity <= 0 is an inventory correction. In this dataset step 4 already catches all of them, so 0 rows is expected. |
| 6. Remove reversed bulk orders | 1,021,208 | 85 | 0.01 | 33,245 | 1,021,123 | Orders of >= 1,000 units cancelled in full by the same customer (data-entry mistakes such as 80,995 x paper craft). |
| 7. Split sales vs returns | 1,021,123 | 0 | 0.0 | 0 | 1,021,123 | 1,003,248 sales lines and 17,875 return lines ('C' invoices). Returns are kept separately for return-rate analysis. |
| 8. Flag missing Customer ID (kept) | 1,003,248 | 0 | 0.0 | 0 | 1,003,248 | 226,717 sales lines (22.6%) have no Customer ID. Kept for revenue and product analysis, excluded only from customer analysis (RFM, cohorts). |
