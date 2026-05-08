"""
Normalize raw DataTables records from json-subsid-2024.php.
"""


def parse_subsid_record(rec: dict) -> dict:
    return {
        "publication_date":    rec.get("PUBLICATIONDATE", ""),
        "pu_number":           rec.get("PUNUMBER", ""),
        "title_en":            rec.get("TITLEBI", ""),
        "title_bm":            rec.get("TITLEBM", ""),
        "status":              rec.get("STATUS", ""),
        "related_legislation": rec.get("RELATEDLEGISLATION", ""),
        "pdf_url":             rec.get("URLDOC", ""),
    }


def parse_subsid_records(raw_records: list[dict]) -> list[dict]:
    return [parse_subsid_record(r) for r in raw_records]
