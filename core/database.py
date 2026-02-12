from __future__ import annotations

import sqlite3
from datetime import datetime
from sqlite3 import Connection, Cursor
from typing import Optional

from models.media_model import Media


class DatabaseError(Exception):
    """Raised when a database operation fails."""


class DatabaseManager:
    def __init__(self, db_path: str = "media.db") -> None:
        self._db_path = db_path
        self._connection = self._create_connection()
        self._create_media_table()

    def _create_connection(self) -> Connection:
        try:
            connection = sqlite3.connect(self._db_path)
            connection.row_factory = sqlite3.Row
            return connection
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to connect to database: {exc}") from exc

    def _create_media_table(self) -> None:
        query = """
        CREATE TABLE IF NOT EXISTS media (
            file_path TEXT PRIMARY KEY,
            file_name TEXT NOT NULL,
            file_size_mb REAL NOT NULL,
            duration_seconds REAL NOT NULL,
            resolution TEXT,
            title TEXT,
            category TEXT,
            release_date TEXT,
            director TEXT,
            writers TEXT,
            producers TEXT,
            runtime_minutes INTEGER,
            imdb_rating REAL,
            poster_path TEXT,
            last_scanned TEXT
        );
        """
        self._execute(query)

    def _execute(self, query: str, params: tuple = ()) -> Cursor:
        try:
            cursor = self._connection.cursor()
            cursor.execute(query, params)
            self._connection.commit()
            return cursor
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database query failed: {exc}") from exc

    @staticmethod
    def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    @staticmethod
    def _deserialize_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _row_to_media(row: sqlite3.Row) -> Media:
        return Media(
            file_path=row["file_path"],
            file_name=row["file_name"],
            file_size_mb=row["file_size_mb"],
            duration_seconds=row["duration_seconds"],
            resolution=row["resolution"],
            title=row["title"],
            category=row["category"],
            release_date=row["release_date"],
            director=row["director"],
            writers=row["writers"],
            producers=row["producers"],
            runtime_minutes=row["runtime_minutes"],
            imdb_rating=row["imdb_rating"],
            poster_path=row["poster_path"],
            last_scanned=DatabaseManager._deserialize_datetime(row["last_scanned"]),
        )

    def insert_media(self, media: Media) -> None:
        query = """
        INSERT INTO media (
            file_path,
            file_name,
            file_size_mb,
            duration_seconds,
            resolution,
            title,
            category,
            release_date,
            director,
            writers,
            producers,
            runtime_minutes,
            imdb_rating,
            poster_path,
            last_scanned
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            media.file_path,
            media.file_name,
            media.file_size_mb,
            media.duration_seconds,
            media.resolution,
            media.title,
            media.category,
            media.release_date,
            media.director,
            media.writers,
            media.producers,
            media.runtime_minutes,
            media.imdb_rating,
            media.poster_path,
            self._serialize_datetime(media.last_scanned),
        )
        self._execute(query, params)

    def update_media(self, media: Media) -> None:
        query = """
        UPDATE media
        SET
            file_name = ?,
            file_size_mb = ?,
            duration_seconds = ?,
            resolution = ?,
            title = ?,
            category = ?,
            release_date = ?,
            director = ?,
            writers = ?,
            producers = ?,
            runtime_minutes = ?,
            imdb_rating = ?,
            poster_path = ?,
            last_scanned = ?
        WHERE file_path = ?;
        """
        params = (
            media.file_name,
            media.file_size_mb,
            media.duration_seconds,
            media.resolution,
            media.title,
            media.category,
            media.release_date,
            media.director,
            media.writers,
            media.producers,
            media.runtime_minutes,
            media.imdb_rating,
            media.poster_path,
            self._serialize_datetime(media.last_scanned),
            media.file_path,
        )
        self._execute(query, params)

    def get_media_by_category(self, category: str) -> list[Media]:
        query = "SELECT * FROM media WHERE category = ?;"
        cursor = self._execute(query, (category,))
        rows = cursor.fetchall()
        return [self._row_to_media(row) for row in rows]

    def get_media_by_path(self, file_path: str) -> Optional[Media]:
        query = "SELECT * FROM media WHERE file_path = ?;"
        cursor = self._execute(query, (file_path,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_media(row)

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to close database connection: {exc}") from exc
