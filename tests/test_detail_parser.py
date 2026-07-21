from scraper.parsers.detail_parser import find_latest_reprint


def test_latest_reprint_is_chosen_by_strict_calendar_date_not_label_or_order():
    timeline = [
        {"date": "01/02/2023", "log_type": "REPRINT ONLINE", "pdf_url": "old-online.pdf"},
        {"date": "02/09/2023", "log_type": "REPRINT", "pdf_url": "latest-reprint.pdf"},
        {"date": "01/01/2024", "log_type": "AMENDMENTS", "pdf_url": "amendment.pdf"},
    ]

    assert find_latest_reprint(timeline) == "latest-reprint.pdf"


def test_latest_reprint_rejects_malformed_dates_instead_of_using_scrape_order():
    timeline = [
        {"date": "not-a-date", "log_type": "REPRINT", "pdf_url": "invalid.pdf"},
        {"date": "03/04/2023", "log_type": "REPRINT ONLINE", "pdf_url": "valid.pdf"},
    ]

    assert find_latest_reprint(timeline) == "valid.pdf"
