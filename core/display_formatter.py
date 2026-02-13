from models.media_model import Media
from typing import Optional


class DisplayFormatter:
    """
    Responsible for generating virtual display titles for Media objects.
    Does NOT modify filesystem.
    """

    @staticmethod
    def _extract_year(date_string: Optional[str]) -> Optional[str]:
        """
        Extract year from YYYY-MM-DD formatted date.
        """
        if not date_string:
            return None
        return date_string.split("-")[0]

    @staticmethod
    def format(media: Media) -> str:
        """
        Generate formatted display title.

        Format B:
        TV  -> Show Name (Year) - S01E01 - Episode Title
        Movie -> Movie Name (Year)
        """

        year = DisplayFormatter._extract_year(media.release_date)

        # TV
        if media.season_number and media.episode_number:
            base_title = media.title or media.file_name

            if year:
                base_title = f"{base_title} ({year})"

            season = f"S{int(media.season_number):02d}"
            episode = f"E{int(media.episode_number):02d}"

            episode_title = media.episode_title or ""

            if episode_title:
                return f"{base_title} - {season}{episode} - {episode_title}"

            return f"{base_title} - {season}{episode}"

        # Movie
        if media.title:
            if year:
                return f"{media.title} ({year})"
            return media.title

        # Fallback
        return media.file_name
