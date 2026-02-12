from core.scanner import MediaScanner
from core.enricher import MediaEnricher
from core.database import DatabaseManager


def main():
    scanner = MediaScanner()
    enricher = MediaEnricher()
    db = DatabaseManager()

    media_files = scanner.scan_folder("D:/Entertainment/TV/Solo Leveling/S02")

    for media in media_files:
        enriched = enricher.enrich(media)

        existing = db.get_media_by_path(enriched.file_path)
        if existing:
            db.update_media(enriched)
            print(f"Updated: {enriched.title}")
        else:
            db.insert_media(enriched)
            print(f"Inserted: {enriched.title}")


if __name__ == "__main__":
    main()
