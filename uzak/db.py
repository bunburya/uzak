import sqlite3
from datetime import date, datetime

from uzak.datamodel import ArchiveReference, ArchiveDetails

sqlite3.register_adapter(date, lambda d: d.strftime("%Y-%m-%d"))
sqlite3.register_converter("DATE", lambda b: datetime.strptime(b.decode(), "%Y-%m-%d").date())


class DbManager:
    """Class for managing the sqlite3 database. Designed to be used as a context manager."""

    CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS archives (
            project TEXT NOT NULL,
            language TEXT NOT NULL,
            flavor TEXT,
            date_created DATE NOT NULL,
            file_name TEXT NOT NULL,
            sha256 TEXT NOT NULL
        )
    """

    SELECT_ARCHIVES = """
        SELECT * FROM archives
        WHERE
            project = ?
            AND language = ?
            AND flavor = ?
        ORDER BY date_created DESC
    """

    INSERT_ARCHIVE = """
        INSERT INTO archives
        VALUES (?, ?, ?, ?, ?, ?)
    """

    SELECT_OLDER = """
        SELECT * FROM archives
        WHERE
            project = ?
            AND language = ?
            AND flavor = ?
            AND date_created < ?
    """

    DELETE_ARCHIVE = """
        DELETE FROM archives
        WHERE
            project = ?
            AND language = ?
            AND flavor = ?
            AND date_created = ?
    """

    ARCHIVE_EXISTS = """
        SELECT EXISTS(
            SELECT 1 FROM archives
                WHERE
                    project = ?
                    AND language = ?
                    AND flavor = ?
                    AND date_created = ?
        )
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.row_factory = sqlite3.Row
        self.create_table()

    def create_table(self):
        with self.conn:
            self.conn.execute(self.CREATE_TABLE)

    def find_archives(self, ref: ArchiveReference) -> list[ArchiveDetails]:
        with self.conn:
            result = self.conn.execute(self.SELECT_ARCHIVES, (ref.project, ref.language, ref.flavor))
        return [ArchiveDetails.from_row(r) for r in result]

    def archive_exists(self, ref: ArchiveReference, date_created: date) -> bool:
        with self.conn:
            return bool(self.conn.execute(self.ARCHIVE_EXISTS, (
                ref.project,
                ref.language,
                ref.flavor,
                date_created
            )).fetchone()[0])

    def get_older(self, ref: ArchiveReference, older_than: date) -> list[ArchiveDetails]:
        with self.conn:
            return [ArchiveDetails.from_row(r) for r in self.conn.execute(self.SELECT_OLDER, (
                ref.project,
                ref.language,
                ref.flavor,
                older_than
            ))]

    def delete_archive(self, archive: ArchiveDetails):
        with self.conn:
            self.conn.execute(self.DELETE_ARCHIVE, (
                archive.reference.project,
                archive.reference.language,
                archive.reference.flavor,
                archive.date_created
            ))

    def insert_archive(self, archive: ArchiveDetails):
        with self.conn:
            self.conn.execute(self.INSERT_ARCHIVE, (
                archive.reference.project,
                archive.reference.language,
                archive.reference.flavor,
                archive.date_created.strftime("%Y-%m-%d"),
                archive.file_name,
                archive.sha256
            ))
