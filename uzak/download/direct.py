import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from logging import Logger
from threading import RLock
from typing import Optional

import psutil
import requests
from tqdm import tqdm

from uzak import Config
from uzak.datamodel import DownloadDetails, ArchiveDetails
from uzak.download.base import DownloadError, BaseDownloader


def get_file_hash(file_path: str) -> str:
    """Calculate the sha256 hash of the specified file."""
    file_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        while data := f.read(1024 * 1024 * 10):
            file_hash.update(data)
    return file_hash.hexdigest()


class DirectDownloader(BaseDownloader):

    def __init__(self, config: Config, logger: Logger):
        self.archive_dir = config.archive_dir
        self.logger = logger

    def download(
            self,
            download: DownloadDetails,
            check_length: bool = True,
            verify: bool = True,
            quiet: bool = False,
            pbar_position: Optional[int] = None
    ) -> ArchiveDetails:

        self.logger.info(f"Downloading ZIM file from {download.zim_link}.")

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

        with tqdm(
                total=size,
                unit='B',
                unit_scale=True,
                desc=download.file_name.removesuffix(".zim"),
                position=pbar_position,
                leave=(pbar_position is None),  # Only leave traces if we're not in multithreaded environment
                disable=quiet
        ) as progress_bar:
            with open(part_path, 'wb') as f:
                for chunk in content_response.iter_content(chunk_size=1024 * 1024):
                    progress_bar.update(len(chunk))
                    f.write(chunk)

        if sha is not None:
            if not get_file_hash(part_path) == sha:
                os.remove(part_path)
                raise DownloadError(f"sha256 hash of downloaded content not equal to hash downloaded from server. "
                                    "Aborting.")

        os.rename(part_path, dest_path)

        return download.archive_details

    def download_all(
            self,
            downloads: list[DownloadDetails],
            check_length: bool = True,
            quiet: bool = False
    ) -> list[ArchiveDetails]:
        if len(downloads) == 1:
            # If there is only one archive to download, do it the old non-multithreaded way, as the output from tqdm
            # isn't great in a multithreaded context
            return [self.download(downloads[0], check_length, True, quiet)]
        tqdm.set_lock(RLock())
        # below is attempt to address https://github.com/tqdm/tqdm/issues/670 but doesn't seem to work...
        posn_range = range(1, len(downloads) + 1)
        with ThreadPoolExecutor(initializer=tqdm.set_lock, initargs=(tqdm.get_lock(),)) as p:
            return list(p.map(
                lambda d, posn: self.download(d, check_length, True, quiet, posn),
                downloads, posn_range
            ))
