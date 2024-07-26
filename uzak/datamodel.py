import sqlite3
from dataclasses import dataclass, field
from datetime import date


@dataclass(eq=True, frozen=True)
class ArchiveReference:
    """Dataclass representing a reference to an archive (ie, the static details necessary to identify an archive
    on the website, not tied to a specific version).
    """
    project: str
    language: str
    flavor: str


@dataclass
class DownloadDetails:
    """Dataclass containing the details necessary to download the current version of an archive."""
    archive_reference: ArchiveReference
    zim_link: str
    size_bytes: int
    sha256_link: str
    torrent_link: str
    magnet_link: str
    date_created: date
    file_name: str = field(init=False)

    def __post_init__(self):
        # Create a file name for the download that follows the convention set out at
        # https://download.kiwix.org/zim/README.
        r = self.archive_reference
        d = self.date_created
        self.file_name = f"{r.project}_{r.language}_{r.flavor.replace(' ', '_')}_{d.strftime('%Y-%m')}.zim"


@dataclass
class ArchiveDetails:
    """Dataclass containing details of a specific downloaded archive."""
    reference: ArchiveReference
    date_created: date
    file_name: str
    sha256: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ArchiveDetails":
        """Create an instance of this class from an `sqlite3.Row` object obtained from the database."""
        reference = ArchiveReference(
            row["project"],
            row["language"],
            row["flavor"]
        )
        return cls(
            reference=reference,
            date_created=row["date_created"],
            file_name=row["file_name"],
            sha256=row["sha256"]
        )