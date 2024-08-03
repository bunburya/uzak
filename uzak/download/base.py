from abc import ABC, abstractmethod
from logging import Logger

from uzak import Config
from uzak.datamodel import DownloadDetails, ArchiveDetails


class DownloadError(Exception):
    pass


class BaseDownloader(ABC):

    @abstractmethod
    def __init__(self, config: Config, logger: Logger):
        raise NotImplementedError

    @abstractmethod
    def download_all(self, downloads: list[DownloadDetails], check_length: bool, quiet: bool) -> list[ArchiveDetails]:
        raise NotImplementedError
