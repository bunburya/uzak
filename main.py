import hashlib
import logging
import os.path
import sqlite3
import subprocess
import tomllib
from argparse import ArgumentParser
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Collection

import bs4
import platformdirs
import psutil
import requests
from tqdm import tqdm

# Register sqlite3 converters and adapters
sqlite3.register_adapter(date, lambda d: d.strftime("%Y-%m-%d"))
sqlite3.register_converter("DATE", lambda b: datetime.strptime(b.decode(), "%Y-%m-%d").date())

logger = logging.getLogger(__name__)
logger.propagate = False
# Logger to handle "normal" output, ie, information provided to the user in the usual way.
normal_output = logging.StreamHandler()
normal_output.setFormatter(logging.Formatter("%(message)s"))
normal_output.setLevel(logging.INFO)
normal_output.filter = lambda r: r.levelno < logging.WARN

# Logger to handle "bad" output (warnings or errors), which also communicates the log level.
bad_output = logging.StreamHandler()
bad_output.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
bad_output.setLevel(logging.WARN)

logger.addHandler(normal_output)
logger.addHandler(bad_output)

logging.basicConfig(level=logging.INFO)


class DownloadError(Exception):
    pass


class ParserError(Exception):
    pass


def parse_date(s: str) -> date:
    """Convert a date in the format "YYYY-MM" to a `date` object (using 1 for the `day` value)."""
    y, m = s.split("-")
    return date(
        year=int(y),
        month=int(m),
        day=1
    )


@dataclass(eq=True, frozen=True)
class ArchiveReference:
    """Dataclass representing a reference to an archive (ie, the static details necessary to identify an archive
    on the website, not tied to a specific version).
    """
    project: str
    language: str
    flavor: str


@dataclass
class Config:
    content_url: str
    base_dir: str
    delete_old: bool
    kiwix_manage_exec: str
    archives: list[ArchiveReference]
    archive_dir: str = field(init=False)
    library_path: str = field(init=False)
    db_path: str = field(init=False)

    def __post_init__(self):
        self.archive_dir = os.path.join(self.base_dir, "archives")
        self.library_path = os.path.join(self.base_dir, "library.xml")
        self.db_path = os.path.join(self.base_dir, "archives.db")

    @classmethod
    def from_toml_file(cls, toml_file: str) -> "Config":
        with open(toml_file, "rb") as f:
            c = tomllib.load(f)
        return Config(
            content_url=c["content_url"],
            base_dir=c["base_dir"],
            delete_old=c["delete_old"],
            kiwix_manage_exec=c["kiwix_manage_exec"],
            archives=[ArchiveReference(a["project"], a["language"], a["flavor"]) for a in c["archive"]]
        )


@dataclass
class DownloadDetails:
    """Dataclass containing the details necessary to download the current version of an archive."""
    archive_reference: ArchiveReference
    zim_link: str
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


class Parser:
    """Class for parsing the Kiwix website."""

    def __init__(self, url: str, archive_refs: Collection[ArchiveReference]):
        self.url = url
        self.archive_refs = set(archive_refs)

    def parse_archive_row(self, tr: bs4.element.Tag, dbm: DbManager) -> Optional[DownloadDetails]:
        """Parse a single table row (`<tr>`) containing information about a ZIM archive, and return download details."""
        proj_td, lang_td, size_td, date_td, flav_td, links_td = tr.find_all("td")
        reference = ArchiveReference(
            proj_td.text.strip().split()[0],
            lang_td.text.strip(),
            flav_td.text.strip()
        )
        zim_link, sha_link, bt_link, mag_link = (a.attrs["href"] for a in links_td.find_all("a"))
        date_created = parse_date(date_td.text.strip())

        if (reference in self.archive_refs) and (not dbm.archive_exists(reference, date_created)):
            return DownloadDetails(
                archive_reference=reference,
                zim_link=zim_link,
                sha256_link=sha_link,
                torrent_link=bt_link,
                magnet_link=mag_link,
                date_created=date_created
            )
        else:
            return None

    def parse_page(self, dbm: DbManager) -> list[DownloadDetails]:
        """Parse the table containing ZIM archive details and return a list of download details for new, relevant
        archives.

        :param dbm: :class:`DbManager` object, used to query whether a given archive has already been downloaded.
        """
        r = requests.get(self.url)
        r.raise_for_status()
        page = bs4.BeautifulSoup(r.content.decode(), "html.parser")
        table = page.find("table", id="zimtable")
        if table is None:
            raise ParserError("Could not find table with id `zimtable`.")
        details = []
        for tr in table.find_all("tr")[1:]:
            if (d := self.parse_archive_row(tr, dbm)) is not None:
                details.append(d)
        return details


class DownloadManager:

    def __init__(self, archive_dir: str, library_file: str):
        self.archive_dir = archive_dir

    def download(
            self,
            download: DownloadDetails,
            check_length: bool = True,
            verify: bool = True
    ) -> ArchiveDetails:

        logger.info(f"Downloading ZIM file from {download.zim_link}.")

        if check_length:
            head_response = requests.head(download.zim_link, allow_redirects=True)
            head_response.raise_for_status()
            if not ("Content-Length" in head_response.headers):
                raise DownloadError("Could not get content length. Aborting download.")
            size = int(head_response.headers["Content-Length"])
            if psutil.disk_usage(self.archive_dir).free < size:
                raise DownloadError("File would not fit on disk. Aborting download.")
        else:
            size = None

        if verify:
            sha_response = requests.get(download.sha256_link)
            if not sha_response.ok:
                raise DownloadError("Could not download sha256 hash. Aborting download.")
            sha = sha_response.content.decode("utf-8").split(" ")[0]
        else:
            sha = None

        dest_path = os.path.join(self.archive_dir, download.file_name)
        part_path = dest_path + ".part"

        content_response = requests.get(download.zim_link, stream=True)
        if not content_response.ok:
            raise DownloadError("Could not download content. Aborting.")

        with tqdm(total=size, unit='B', unit_scale=True) as progress_bar:
            with open(part_path, 'wb') as f:
                for chunk in content_response.iter_content(chunk_size=1024 * 1024):
                    progress_bar.update(len(chunk))
                    f.write(chunk)

        if sha is not None:
            file_hash = hashlib.sha256()
            with open(part_path, "rb") as f:
                while data := f.read(1024 * 1024 * 10):
                    file_hash.update(data)
            if not file_hash.hexdigest() == sha:
                os.remove(part_path)
                raise DownloadError(f"sha256 hash of downloaded content not equal to hash downloaded from server. "
                                    "Aborting.")

        os.rename(part_path, dest_path)

        return ArchiveDetails(
            reference=download.archive_reference,
            date_created=download.date_created,
            file_name=download.file_name,
            sha256=sha
        )


class ArchiveManager:

    def __init__(self, config: Config):
        self.config = config
        self.db_manager = DbManager(config.db_path)
        self.parser = Parser(config.content_url, config.archives)
        self.dl_manager = DownloadManager(config.archive_dir, config.library_path)
        if os.path.isfile(config.base_dir):
            raise FileExistsError(f"Already a non-directory file at {config.base_dir}.")
        if os.path.isfile(config.archive_dir):
            raise FileExistsError(f"Already a non-directory file at {config.archive_dir}.")
        if not os.path.exists(config.archive_dir):
            os.makedirs(config.archive_dir)

    def add_to_library(self, archive: ArchiveDetails):
        archive_path = os.path.join(self.config.archive_dir, archive.file_name)
        subprocess.run([self.config.kiwix_manage_exec, self.config.library_path, "add", archive_path])

    def get_zim_id(self, archive: ArchiveDetails) -> Optional[str]:
        output = subprocess.run(
            [self.config.kiwix_manage_exec, self.config.library_path, "show"],
            capture_output=True
        ).stdout.decode()
        relevant_path = os.path.join(self.config.archive_dir, archive.file_name)
        lines = output.splitlines()
        latest_id: Optional[str] = None
        for line in lines:
            line = line.strip()
            if line.startswith("id:"):
                latest_id = line.split()[1]
            elif line.startswith("path:"):
                if line.split()[1] == relevant_path:
                    return latest_id
        return None

    def remove_from_library(self, archive: ArchiveDetails):
        zim_id = self.get_zim_id(archive)
        if zim_id is not None:
            subprocess.run([self.config.kiwix_manage_exec, self.config.library_path, "remove", zim_id])

    def update(self):
        for to_dl in self.parser.parse_page(self.db_manager):
            new = self.dl_manager.download(to_dl)
            self.db_manager.insert_archive(new)
            self.add_to_library(new)
            if self.config.delete_old:
                for old in self.db_manager.get_older(new.reference, new.date_created):
                    old_path = os.path.join(self.config.archive_dir, old.file_name)
                    logger.info(f"Deleting file at {old_path}.")
                    os.remove(old_path)
                    self.db_manager.delete_archive(old)
                    self.remove_from_library(old)


def main():
    arg_parser = ArgumentParser(description="Fetch new ZIM archives from download.kiwix.org.")
    arg_parser.add_argument("-c", "--config", metavar="PATH", help="Path to config file to use.")
    arg_parser.add_argument("-d", "--debug", action="store_true", help="Debug mode (verbose logging).")

    args = arg_parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    default_conf_file = os.path.join(platformdirs.user_config_dir(appname="kiwix-updater"), "config.toml")
    conf_file = args.config or default_conf_file
    if not os.path.isfile(conf_file):
        raise FileNotFoundError(f"Could not find configuration file at {conf_file}")
    config = Config.from_toml_file(conf_file)
    manager = ArchiveManager(config)
    manager.update()
    manager.db_manager.conn.close()


if __name__ == "__main__":
    main()
