import os.path
import time
from logging import Logger
from time import sleep
from typing import Optional

import psutil
import qbittorrentapi as qbt
from qbittorrentapi import TorrentDictionary
from tqdm import tqdm

from uzak import Config
from uzak.datamodel import DownloadDetails, ArchiveDetails
from uzak.download.base import DownloadError, BaseDownloader


class QBitTorrentDownloader(BaseDownloader):

    def __init__(
            self,
            config: Config,
            logger: Logger
    ):
        self.archive_dir = config.archive_dir
        qbt_conf = config.qbt_config
        if qbt_conf is None:
            raise ValueError("No `qbittorrent` section found in config.")
        self.client = qbt.Client(
            host=qbt_conf.host,
            port=qbt_conf.port,
            username=qbt_conf.username,
            password=qbt_conf.password
        )
        self.poll_interval = qbt_conf.poll_interval
        self.logger = logger

    def download(
            self,
            download: DownloadDetails,
            check_length: bool = True,
            start_paused: bool = False
    ) -> tuple[str, int]:
        dest_path = os.path.join(self.archive_dir, download.file_name)
        part_path = dest_path + ".part"
        self.logger.info(f"Downloading to {dest_path}")
        self.client.torrents_add(
            urls=[download.torrent_link],
            tags=["uzak"],
            download_path=part_path,
            save_path=dest_path,
            is_stopped=check_length or start_paused
        )

        # Get the torrent info for the torrent we just added. It doesn't seem to show up straight away so we try a few
        # times until we find it, waiting a second between each try. If it's still not appearing after a few tries,
        # raise an error.
        info = None
        tries = 0
        while info is None:
            for i in self.client.torrents_info(tag="uzak"):
                if i.save_path == dest_path:
                    info = i
                    break
            else:
                tries += 1
                if tries >= 5:
                    raise DownloadError(f"Could not find torrent after adding: {download}.")
                else:
                    time.sleep(1)
        if check_length:
            if info.size > psutil.disk_usage(self.archive_dir).free:
                self.client.torrents_delete(torrent_hashes=[info.hash])
                raise DownloadError("File would not fit on disk. Aborting download.")
            else:
                if not start_paused:
                    self.client.torrents_start(torrent_hashes=info.hash)
        return info.hash, info.size

    def download_all(
            self,
            downloads: list[DownloadDetails],
            check_length: bool = True,
            quiet: bool = False
    ):
        dl_info: dict[str, tuple[DownloadDetails, int]] = {}
        archives: list[ArchiveDetails] = []
        for d in downloads:
            h, s = self.download(d, check_length=False, start_paused=True)
            dl_info[h] = (d, s)
        hashes = dl_info.keys()
        if check_length:
            total_size = sum(dl_info[h][1] for h in hashes)
            if total_size > psutil.disk_usage(self.archive_dir).free:
                self.client.torrents_delete(torrent_hashes=hashes)
                raise DownloadError("All files would not fit on disk. Aborting download.")
            else:
                self.client.torrents_start(torrent_hashes=hashes)
        pbars: dict[str, tqdm] = {}
        for h in dl_info:
            d, s = dl_info[h]
            pbars[h] = tqdm(
                total=s,
                unit='B',
                unit_scale=True,
                desc=d.file_name.removesuffix(".zim"),
                disable=quiet
            )
        while dl_info:
            current_info = self.client.torrents_info(torrent_hashes=hashes)
            for i in current_info:
                if i.hash not in dl_info:
                    continue
                if not quiet:
                    pbars[i.hash].update(i.completed)
                if os.path.isfile(i.save_path) and i.completed >= i.size:
                    dl = dl_info[i.hash][0]
                    archives.append(dl.archive_details)
                    self.client.torrents_delete(torrent_hashes=[i.hash])
                    dl_info.pop(i.hash)
            sleep(self.poll_interval)
        return archives



