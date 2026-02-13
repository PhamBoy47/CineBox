from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Media:
    file_path: str
    file_name: str
    file_size_mb: float
    duration_seconds: float
    resolution: Optional[str] = None

    title: Optional[str] = None
    category: Optional[str] = None
    release_date: Optional[str] = None
    director: Optional[str] = None
    writers: Optional[str] = None
    producers: Optional[str] = None
    runtime_minutes: Optional[int] = None
    imdb_rating: Optional[float] = None
    poster_path: Optional[str] = None
    last_scanned: Optional[datetime] = None
    file_modified_time: Optional[float] = None
    error_message: Optional[str] = None
    error_location: Optional[str] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    episode_title: Optional[str] = None
    episode_air_date: Optional[str] = None
