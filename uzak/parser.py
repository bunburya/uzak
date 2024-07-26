from datetime import date
from enum import IntEnum
from typing import Collection, Optional

import bs4
import requests

from uzak.datamodel import ArchiveReference, DownloadDetails
from uzak.db import DbManager


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

class FileSizeSuffix(IntEnum):
    B = 1
    KB = 1024
    MB = 1_048_576
    GB = 1_073_741_824
    TB = 1_099_511_627_776

def str_to_bytes(s: str) -> int:
    """Convert a human-readable description of a file size like "2.34 GB" to bytes."""
    n, suf = s.split()
    n = float(n)
    mul = int(FileSizeSuffix[suf])
    return int(n * mul)

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
                size_bytes=str_to_bytes(size_td.text.strip()),
                zim_link=zim_link,
                sha256_link=sha_link,
                torrent_link=bt_link,
                magnet_link=mag_link,
                date_created=date_created
            )
        else:
            return None

    def get_archive_rows(self) -> list[bs4.element.Tag]:
        """Parse the web page and return a list of `bs4` objects representing <tr> tags containing the details of the
        archives.
        """
        r = requests.get(self.url)
        r.raise_for_status()
        page = bs4.BeautifulSoup(r.content.decode(), "html.parser")
        table = page.find("table", id="zimtable")
        if table is None:
            raise ParserError("Could not find table with id `zimtable`.")
        return table.find_all("tr")[1:]

    def find_updated_archives(self, dbm: DbManager) -> list[DownloadDetails]:
        """Parse the web page and return a list of download details for new, relevant archives.

        :param dbm: :class:`DbManager` object, used to query whether a given archive has already been downloaded.
        """
        rows = self.get_archive_rows()
        details = []
        for tr in rows:
            if (d := self.parse_archive_row(tr, dbm)) is not None:
                details.append(d)
        return details

    def find_archive_refs(self, lang: Optional[str]) -> list[ArchiveReference]:
        """Parse the web page and return a list of :class:`ArchiveReference` objects representing the available
        archives.

        :param lang: If provided, only archives in the given language are provided.
        """
        refs = []
        for tr in self.get_archive_rows():
            proj_td, lang_td, _, _, flav_td, _ = tr.find_all("td")
            arc_lang = lang_td.text.strip()
            if (lang is None) or (arc_lang == lang):
                refs.append(ArchiveReference(
                    proj_td.text.strip().split()[0],
                    arc_lang,
                    flav_td.text.strip()
                ))
        return refs