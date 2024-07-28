import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(eq=True, frozen=True)
class ArchiveReference:
    """Dataclass representing a reference to an archive (ie, the static details necessary to identify an archive
    on the website, not tied to a specific version).
    """
    project: str
    language: str
    flavor: str

    def to_file_name(self, date_created: Optional[date] = None) -> str:
        flav = self.flavor.replace(" ", "_")
        base = "_".join((self.project, self.language, flav))
        if date_created is not None:
            base += "_" + date_created.strftime("%Y-%m")
        return base + ".zim"

    def to_config(self) -> str:
        lines = [
            "[[archive]]",
            f'project = "{self.project}"',
            f'language = "{self.language}"',
            f'flavor = "{self.flavor}"'
        ]
        return "\n".join(lines)


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
        self.file_name = r.to_file_name(d)


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