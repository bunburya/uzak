# `uzak`

`uzak` (**U**pdate **Z**im **A**rchives from **K**iwix) is an unofficial Python script to manage and update
[ZIM archives](https://wiki.openzim.org/wiki/OpenZIM) from the
[Kiwix library](https://wiki.kiwix.org/wiki/Content_in_all_languages). It is not affiliated with the Kiwix project or
organisation.

Kiwix makes available a large number of ZIM files representing snapshots of popular websites, in different languages. These
files can be downloaded and viewed through software developed by Kiwix, including
[`kiwix-serve`](https://wiki.kiwix.org/wiki/Kiwix-serve), which serves the files over HTTP.

The snapshots provided by Kiwix are updated from time to time (some more frequently than others). With `uzak`, you can
create a configuration file specifying all the archives you want to download. `uzak` will download them and add them
to a library file which can be served by `kiwix-serve`. Subsequent runs of `uzak` will check the Kiwix website for
updated versions of those archives and, if found, download them, add them to the archives and optionally delete the old
versions.

## Installation

Clone this repository and install using `pip`.

```shell
git clone git@github.com:bunburya/uzak.git
pip install uzak
```

You may need to (and in any event, probably should) do this from within a
[virtual environment](https://docs.python.org/3/tutorial/venv.html). 

## Configuration

Configuration is primarily through a [TOML](https://toml.io/en/) file. You can specify a particular config file to use
with the `--config` command line option. Otherwise, `uzak` will look for a config file in the usual place depending on
your operating system (for example, on most Linux systems, it will look for `$HOME/.config/uzak/config.toml`).

A sample `config.toml`, with comments, is included in this repo, which should be fairly self-explanatory. Basically, you
have a few "top level" configuration options which specify the behaviour of `uzak` (where to store the files, etc),
followed by one or more `[[archive]]` sections which specify the archives to download.

Each `[[archive]]` section should specify three things:

- `project`, which should correspond to the text in the "Project" column of the website (excluding the description of
    the language in parentheses),
- `language`, which should correspond to the text in the "Language" column, and
- `flavor` (note the US spelling), which should correspond to the text in the "Number of articles / Flavour" column.
    Note that this should appear exactly as it does on the website (meaning the words should be in the same order) 
    "all nopic" and "nopic all" ill not match.

You can include as many `[[archive]]` sections as you like.

**NOTE:** Many archives seem to have incorrectly listed metadata. To give just one example, there is an archive where
the project is listed simply as "the", the language is listed as "infosphere" and the flavour is listed as "en all 
maxi". I suspect this is because the metadata is parsed from the underlying files, which are not always named according
to [the convention](https://download.kiwix.org/zim/README) specified by Kiwix. Again, you should specify the `project`,
`language` and `flavor` attributes of your target archives exactly as they appear in the relevant columns on the Kiwix
website.

## Usage

The main subcommand is `update`, which will check the website for the latest version of each relevant archive, download
each new archive, check its integrity using the sha256 hash provided by Kiwix, and finally add it to the library file.
If the `--prompt` argument is passed, then before downloading anything it will display the number of new archives to be
downloaded and the total download size and ask for confirmation before proceeding. If `delete_old` is set to `true` in 
the config file, then any old versions of the archive that were previously downloaded will be deleted.

Once downloaded, the ZIM files themselves will be stored in the `archives` subdirectory of the directory you specified
in the config file (`base_dir`). A Kiwix library file, `library.xml`, will be stored directly within `base_dir`. If you
run `kiwix-serve` with the `--library` argument and specify that library file, it will serve all of your downloaded
archives over HTTP (see the documentation for `kiwix-serve` for more information). Also within `base_dir` you will find
`archives.db`, an sqlite3 database file used to keep track of what archives have been downloaded. **NOTE**: You should
not edit any of the files within `base_dir` yourself as this may prevent `uzak` from keeping track of them.

Example:
```shell
uzak -c my_config.toml update --prompt
```

There is another subcommand, `find-archives`, which will output an `[[archive]]` section (see "Configuration" above) for
each archive listed on the website. This can be used to browse the available archives from your terminal and the output
can be appended to a config file to fetch all of those archives. **NOTE**, however, that there are a lot of archives,
and some of them are quite big, so it is not advised to blindly append the output of `find-archives` to your config file
unless you know what you are doing. A check in July 2024 revealed that the Kiwix web page listed 3,273 archives,
totalling approximately 4.14 TB. Providing the optional `--lang` argument will only output archives that are listed as
being in the relevant language (but note the comment in the previous section about metadata, including language, not
always being correct).

Example:
```shell
uzak find-archives --lang en
```

The `add` subcommand allows you to add an archive from a location on disk. In addition to providing the path to the
existing file, you must specify the project, language and flavour as arguments, and optionally the date the archive was
created in YYYY-MM format. If the date is omitted, then `uzak` will attempt to figure it out by looking for a date in
the YYYY-MM format at the end of the given file path, just before the `.zim` extension. Calling `add` will move the file
into the archives directory, add the archive to the database and also (if not present already) append an `[[archive]]`
section to the config file. Passing the `--copy` comment will copy the file into the archives directory rather than
moving it so that the original file is preserved. This is necessary if the source file is not on the same device as the
archives directory.

Example:

```shell
# Move file, specify date
uzak add /path/to/wiktionary_en_simple_all_maxi_2024-06.zim wiktionary en "simple all maxi" 2024-06
# Copy file, parse date
uzak add /path/to/wiktionary_en_simple_all_maxi_2024-06.zim wiktionary en "simple all maxi" --copy
```

Call `uzak -h` to find more information about available options.

## Dependencies

`uzak` is a Python script, targeting Python 3.11 or above. Python dependencies are listed in the Pipfile. You also need
to have `kiwix-manage` installed, as it invokes this tool to update your Kiwix library file.

More broadly, of course, it depends on the Kiwix web page linked above remaining available, and in substantially the
same format. Any changes to that page may break `uzak` unexpectedly. Please file an issue with as much information as
possible if you encounter any issues.