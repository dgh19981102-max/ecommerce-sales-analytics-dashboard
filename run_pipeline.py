"""Run the whole pipeline end-to-end: download -> clean -> insights -> Excel reports.

    python run_pipeline.py
Then start the dashboard with:
    streamlit run app/streamlit_app.py
"""
from src import analysis, cleaning, download_data, report_excel


def main() -> None:
    print("== 1/4 Download raw data ==")
    download_data.main()
    print("\n== 2/4 Clean ==")
    cleaning.main()
    print("\n== 3/4 Analyse ==")
    analysis.main()
    print("\n== 4/4 Excel reports ==")
    sales, returns = analysis.load_clean()
    for period in ("month", "week"):
        print("Report written:", report_excel.build_report(sales, returns, period))
    print("\nDone. Start the dashboard with:  streamlit run app/streamlit_app.py")


if __name__ == "__main__":
    main()
