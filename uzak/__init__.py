import logging
import os.path
import shutil
import subprocess
from argparse import ArgumentParser
from datetime import date
from typing import Optional

import platformdirs

from uzak.config import Config
from uzak.datamodel import ArchiveDetails, ArchiveReference
from uzak.db import DbManager
from uzak.download import DownloadManager, get_file_hash
from uzak.log import get_logger
from uzak.parser import Parser, FileSizeSuffix, parse_date

logger = get_logger(__name__)


def bytes_to_str(b: int) -> str:
    """Convert a number of bytes to a human-readable description like "2.34 GB"."""
    if b < 0:
        raise ValueError(f"Negative value for number of bytes: {b}.")
    for suf in reversed(FileSizeSuffix):
        if b >= suf:
            div = round(b / suf, 2)
            return f"{div} {suf.name}"
    return f"{b} B"


class ArchiveManager:

    def __init__(self, config: Config):
        self.config = config
        # Lazy initiate these as they may not be needed depending on the subcommands run
        self._db_manager: Optional[DbManager] = None
        self._dl_manager: Optional[DownloadManager] = None
        self._parser: Optional[Parser] = None
        if os.path.isfile(config.base_dir):
            raise FileExistsError(f"Already a non-directory file at {config.base_dir}.")
        if os.path.isfile(config.archive_dir):
            raise FileExistsError(f"Already a non-directory file at {config.archive_dir}.")
        if not os.path.exists(config.archive_dir):
            os.makedirs(config.archive_dir)

    @property
    def dl_manager(self) -> DownloadManager:
        if self._dl_manager is None:
            self._dl_manager = DownloadManager(self.config.archive_dir)
        return self._dl_manager

    @property
    def parser(self) -> Parser:
        if self._parser is None:
            self._parser = Parser(self.config.content_url, self.config.archives)
        return self._parser

    @property
    def db_manager(self) -> DbManager:
        if self._db_manager is None:
            self._db_manager = DbManager(self.config.db_path)
        return self._db_manager

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

    def update(self, prompt: bool = False):
        all_new = self.parser.find_updated_archives(self.db_manager)
        if not all_new:
            logger.info("Nothing to download.")
            return
        if prompt:
            n_downloads = len(all_new)
            total_size_bytes = sum(d.size_bytes for d in all_new)
            total_size = bytes_to_str(total_size_bytes)
            proceed = input(f"Will download {n_downloads} archive(s) totalling approx {total_size}. Proceed? [y/N] ")
            if proceed.lower() != "y":
                logger.info("Aborting.")
                return
        for to_dl in all_new:
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

    def get_archive_configs(self, lang: Optional[str] = None) -> str:
        """Scrape details of all archives from the website and return a string with their details in a format that can
        be appended to a config file.

        :param lang: If provided, only archives in this language will be listed.
        """
        sections = [a.to_config() for a in self.parser.find_archive_refs(lang)]
        return "\n\n".join(sections)

    def add_file(
            self,
            filepath: str,
            ref: ArchiveReference,
            date_created: Optional[date] = None,
            copy: bool = True
    ) -> ArchiveDetails:
        if date_created is None:
            # Try parse from filepath
            date_str = filepath.removesuffix(".zim").split("_")[-1]
            date_created = parse_date(date_str)
        if self.db_manager.archive_exists(ref, date_created):
            raise ValueError(f"Archive already exists in database: f{ref}")
        archive_filename = ref.to_file_name(date_created)
        archive_filepath = os.path.join(self.config.archive_dir, archive_filename)
        if os.path.exists(archive_filepath):
            raise FileExistsError(f"File already exists: {archive_filepath}")
        sha = get_file_hash(filepath)
        archive = ArchiveDetails(
            ref,
            date_created,
            archive_filename,
            sha
        )
        if copy:
            shutil.copyfile(filepath, archive_filepath)
        else:
            os.rename(filepath, archive_filepath)
        self.db_manager.insert_archive(archive)
        if ref not in self.config.archives:
            with open(self.config.config_file_path, "a") as f:
                f.write("\n")
                f.write(ref.to_config())
                f.write("\n")
            self.config.archives.append(ref)
        logger.info(f"Added {filepath} to archive as {archive_filename}.")
        return archive


def main():
    arg_parser = ArgumentParser(description="Fetch new ZIM archives from download.kiwix.org.")
    arg_parser.add_argument("-c", "--config", metavar="PATH", help="Path to config file to use.")
    arg_parser.add_argument("-d", "--debug", action="store_true", help="Debug mode (verbose logging).")
    subparsers = arg_parser.add_subparsers(required=True)
    update_parser = subparsers.add_parser("update", help="Update archives.")
    update_parser.add_argument("-p", "--prompt", action="store_true",
                               help="Prompt for confirmation (once) before downloading.")
    update_parser.set_defaults(func=lambda mgr, ns: mgr.update(ns.prompt))
    find_archives_parser = subparsers.add_parser("find-archives",
                                                 help="Get a list of all available archives, in an appropriate format "
                                                      "for inclusion in a config file.")
    find_archives_parser.add_argument("--lang", help="Language to filter by.")
    find_archives_parser.set_defaults(func=lambda mgr, ns: print(mgr.get_archive_configs(ns.lang)))
    add_parser = subparsers.add_parser("add", help="Add a file to the library.")
    add_parser.add_argument("file", help="Path to file to add.")
    add_parser.add_argument("project", help="Project name of archive.")
    add_parser.add_argument("language", help="Language of archive.")
    add_parser.add_argument("flavor", help="Flavour of archive.")
    add_parser.add_argument("date", help="Date archive was created, in YYYY-MM format.", nargs="?")
    add_parser.add_argument("--copy", action="store_true",
                            help="Copy file to archives directory, rather than moving it.")
    add_parser.set_defaults(func=lambda mgr, ns: mgr.add_file(
        ns.file,
        ArchiveReference(ns.project, ns.language, ns.flavor),
        parse_date(ns.date) if ns.date is not None else None,
        ns.copy
    ))

    args = arg_parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    default_conf_file = os.path.join(platformdirs.user_config_dir(appname="uzak"), "config.toml")
    conf_file = args.config or default_conf_file
    if not os.path.isfile(conf_file):
        raise FileNotFoundError(f"Could not find configuration file at {conf_file}")
    config = Config.from_toml_file(conf_file)
    manager = ArchiveManager(config)
    args.func(manager, args)


if __name__ == "__main__":
    main()
