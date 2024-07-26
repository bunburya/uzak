import hashlib
import os

import psutil
import requests
from tqdm import tqdm

from uzak.datamodel import DownloadDetails, ArchiveDetails
from uzak.log import get_logger

logger = get_logger(__name__)


class DownloadError(Exception):
    pass


class DownloadManager:

    def __init__(self, archive_dir: str):
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
            logger.info("Verifying file integrity.")
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
