import os
import re
import argparse
import shutil
import datetime

from time import sleep
from copy import deepcopy

import anitopy

from tmdb import TMDB
from log import logger
from plex import Plex
from emby import Emby
from settings import ORIGIN_NAME, PLEX_AUTO_SCAN, EMBY_AUTO_SCAN, MEDIA_SUFFIX
from utils import remove_empty_folder, is_filename_length_gt_255
from scheduler import scheduler


def parse():
    parser = argparse.ArgumentParser(description="Media handle")
    parser.add_argument("path", help="The path of the video")
    parser.add_argument(
        "-d", "--dst_path", default="", help="Move the handled video to this path"
    )
    parser.add_argument("-D", "--dryrun", action="store_true", help="Dryrun")
    parser.add_argument("--nogroup", action="store_true", help="No group info")
    parser.add_argument("-g", "--group", default="", help="Define group")
    parser.add_argument(
        "-E",
        "--regex",
        default="",
        help="Regex expression for getting episode (episode number in group(1))",
    )
    parser.add_argument("-N", "--episode_bit", default=2, help="Episodes' bit")
    parser.add_argument("--offset", default=0, help="Offset of episode number")
    parser.add_argument(
        "-T", "--media_type", choices=["movie", "tv", "anime"], help="Set video type"
    )
    parser.add_argument("--tmdb_id", default="", help="TMDB ID")
    parser.add_argument("--keep_nfo", action="store_true", help="Keep NFO files")

    return parser.parse_args()


def media_filename_pre_handle(parent_dir_path, filename):
    # absolute path to file
    filepath = os.path.join(parent_dir_path, filename)

    # split file name into parts
    file_parts = filename.split(".")
    filename_pre, filename_suffix = ".".join(file_parts[0:-1]), file_parts[-1]

    # deal with subtitles
    if filename_suffix.lower() in ["srt", "ass", "ssa", "sup"]:
        lang_match = re.search(r"[-\.](ch[st]|[st]c)", filename_pre, re.IGNORECASE)
        filename_suffix = "zh." + filename_suffix
        if lang_match:
            filename_suffix = lang_match.group(1) + "." + filename_suffix

    return (filepath, filename_pre, filename_suffix)


def get_media_info_from_filename(
    filename_pre, media_type, regex=None, nogroup=False, group=None
):
    if media_type == "anime":
        parse_rslt = anitopy.parse(filename_pre)
        episode = parse_rslt.get("episode_number")
        resolution = parse_rslt.get("video_resolution", "")
        medium = parse_rslt.get("source", [])
        if isinstance(medium, str):
            medium = medium.split()
        frame = ""
        codec = parse_rslt.get("video_term", [])
        if isinstance(codec, str):
            codec = codec.split()
        audio = parse_rslt.get("audio_term", [])
        if isinstance(audio, str):
            audio = audio.split()
        version = parse_rslt.get("release_version", "")
        if nogroup:
            _group = ""
        else:
            _group = group if group else parse_rslt.get("release_group", "")

        return (episode, "", resolution, medium, frame, codec, audio, version, _group)

    if media_type != "movie":
        # get episode of series
        _regex = r"[ep](\d{2,4})(?!\d)"
        if regex:
            _regex = regex
        try:
            episode = re.search(_regex, filename_pre, re.IGNORECASE).group(1)
        except Exception as e:
            logger.error("No episode number found in file: " + filename_pre)
            return False

    # get resolution of video
    try:
        resolution = re.search(
            r"(\d{3,4}[pi])(?!\d)", filename_pre, re.IGNORECASE
        ).group(1)
    except Exception:
        resolution = ""
    # get medium of video
    medium = set(
        re.findall(
            r"UHD|remux|(?:blu-?ray)|web-?dl|dvdrip|web-?rip|[HI]MAX",
            filename_pre,
            re.IGNORECASE,
        )
    )
    # get frame rate of video
    try:
        frame = re.search(r"\d{2,3}fps", filename_pre, re.IGNORECASE).group(0)
    except Exception:
        frame = ""
    # get web-dl source
    try:
        web_source = re.search(
            r"[\.\s](Disney\+|DSNP|NF|Fri(day)?|AMZN|MyTVS(uper)?|TVB|Bili(bili)?|Baha|GagaOOLala|Hami|Netflix|Viu|Viki|TVING|KKTV|G-Global|HBO|Hulu|Paramount+|iTunes|CatchPlay|IQ)[\.\s]",
            filename_pre,
            re.I,
        ).group(1)
    except Exception:
        web_source = ""
    # get codec of video
    codec = set(
        re.findall(
            r"x264|x265|HEVC|h\.?265|h\.?264|10bit|[HS]DR|HQ|HBR|DV|DoVi(?=[\s\.])",
            filename_pre,
            re.IGNORECASE,
        )
    )
    # get audio of video
    audio = set(
        re.findall(
            r"AAC|AC3|DTS(?:-HD)?|FLAC|MA(?:\.[57]\.1)?|2[Aa]udio|TrueHD|Atmos|DDP",
            filename_pre,
        )
    )
    # get version
    try:
        version = re.search(
            r"[\.\s\[](v\d|Remastered|REPACK|PROPER|Extended( Edition)?(?!(.*Cut))|CC|DC|CEE|Criterion Collection|BFI|Directors\.Cut|Fan Cut|Uncut)[\.\s\]]",
            filename_pre,
            re.IGNORECASE,
        ).group(1)
    except Exception:
        version = ""
    else:
        version = get_plex_edition_from_version(version)
    # get group of video
    if nogroup:
        _group = ""
    else:
        if group:
            _group = group
        else:
            _group_split = re.split(
                r"[-@]",
                re.sub(
                    r"(web-dl|dts-hd|blu-ray|-10bit|dts-x)",
                    " ",
                    filename_pre,
                    flags=re.IGNORECASE,
                ),
            )
            if len(_group_split) == 2:
                _group = _group_split[-1]
            elif len(_group_split) == 3:
                _group = _group_split[-2] + "@" + _group_split[-1]
            else:
                _group = ""

    if media_type != "movie":
        return (
            episode,
            web_source,
            resolution,
            medium,
            frame,
            codec,
            audio,
            version,
            _group,
        )
    else:
        return (web_source, resolution, medium, frame, codec, audio, version, _group)


def get_plex_edition_from_version(version: str) -> str:
    _edition_dict = {
        "extended": "{edition-Extended Edition}",
        "extended edition": "{edition-Extended Edition}",
        "cc": "{edition-Criterion Collection}",
        "criterion collection": "{edition-Criterion Collection}",
        "dc": "{edition-Director's Cut}",
        "Directors.Cut": "{edition-Director's Cut}",
        "cee": "{edition-Central and Eastern Europe}",
        "bfi": "{edition-British Film Institute}",
        "fan cut": "{edition-Fan Cut}",
        "uncut": "{edition-Uncut}",
    }
    return _edition_dict.get(version.lower(), version)


def rename_media(old_path, new_path, dryrun=False):
    if os.path.exists(new_path):
        logger.warning(f"{os.path.basename(new_path)} exists in {new_path}")
        return True
    if not dryrun:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        os.rename(old_path, new_path)
    logger.info(old_path + " --> " + new_path)

    return True


def remove_hidden_files(root_dir_path, dryrun=False):
    removed_files = []
    for file in os.listdir(root_dir_path):
        if file.startswith("."):
            removed_files.append((file, 1 if os.path.isdir(file) else 0))
            if not dryrun:
                os.remove(os.path.join(root_dir_path, file))
            logger.info("Removed hidden file: " + os.path.join(root_dir_path, file))
    return removed_files


def remove_small_files(root_dir_path, threshold=128 * 1024 * 1024, dryrun=False):
    for file in os.listdir(root_dir_path):
        filepath = os.path.join(root_dir_path, file)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            if size < threshold:
                if not dryrun:
                    os.remove(filepath)
                logger.info("Removed file: " + filepath + f", size {size}")


def query_tmdb_id(name, media_type):
    is_movie = True if media_type == "movie" else False
    # init TMDB
    tmdb = TMDB(movie=is_movie)
    if media_type != "anima":
        match = re.search(r"^((.+?)[\s\.](\d{4})[\.\s])(?!\d{4}[\s\.])", name)
        if not match:
            logger.error("Failed to get correct formatted name")
            raise
        name = " ".join(match.group(2).strip(".").split("."))
        year = int(match.group(3))
    else:
        name = anitopy.parse(name).get("anime_title")
        year = anitopy.parse(name).get("anime_title")
    
    cn_match = re.match(
        r"\[?([\u4e00-\u9fa5]+.*?[\u4e00-\u9fa5]*?)\]? (?![\u4e00-\u9fa5]+)(.+)$",
        name,
    )

    if cn_match:
        # 分别用中文和英文进行查询
        for i in range(2):
            name = cn_match.group(i + 1)
            tmdb_name, tmdb_id = tmdb.get_name_from_tmdb(
                query_dict={"query": name, "year": year}
            )
            if tmdb_id:
                break
    else:
        tmdb_name, tmdb_id = tmdb.get_name_from_tmdb(
            query_dict={"query": name, "year": year}
        )

    return tmdb_id


def handle_tvshow(
    media_path,
    tmdb_id,
    media_type,
    dst_path=None,
    regex="",
    group="",
    episode_bit=2,
    nogroup=False,
    dryrun=False,
    offset=0,
    keep_nfo=False,
    scan_folders=None,
):
    if not os.path.isdir(media_path):
        logger.error("Please specify a folder")
        return False
    if dst_path is None:
        dst_path = media_path
    if scan_folders is None:
        scan_folders = []
    # get tmdb id if not specified
    tmdb_id = tmdb_id or query_tmdb_id(media_path)
    if not tmdb_id:
        raise Exception(f"Failed to get info. for {media_path} from TMDB")
    # get details from tmdb
    tmdb = TMDB(movie=False)
    details = tmdb.get_info_from_tmdb_by_id(tmdb_id=tmdb_id)
    tmdb_name = details.get("tmdb_name")
    country = details.get("country")
    year = details.get("year")
    month = details.get("month")

    for dir, subdir, files in os.walk(media_path):
        removed_files = remove_hidden_files(dir, dryrun=dryrun)
        for file in removed_files:
            if file[1] == 0:
                files.remove(file[0])
        for file in files:
            (filepath, filename_pre, filename_suffix) = media_filename_pre_handle(
                dir, file
            )
            # remove unuseful files
            keep_file_suffix = deepcopy(MEDIA_SUFFIX)
            if keep_nfo:
                keep_file_suffix.append("nfo")
            if not re.search(r"|".join(keep_file_suffix), filename_suffix, re.IGNORECASE):
                if not dryrun:
                    os.remove(filepath)
                logger.info("Removed file: " + filepath)
                continue

            season_match = re.search(r"S(eason)?\s?(\d{1,2})", dir + file)
            if not season_match:
                raise Exception(f"Not found season number: {dir + file}")
            season = season_match.group(2).zfill(2)

            # special seaon
            if "Specials" in filepath:
                season = "00"

            # 原文件中已经包含 tmdb id
            if re.search(r"tmdb-\d+", file):
                new_filename = re.sub(r".*{tmdb-\d+}", tmdb_name, file)
                if new_filename == file:
                    logger.warning(f"{file}'s name does not change, skipping...")
                    continue
            else:
                (
                    episode,
                    web_source,
                    resolution,
                    medium,
                    frame,
                    codec,
                    audio,
                    version,
                    _group,
                ) = get_media_info_from_filename(
                    filename_pre,
                    media_type=media_type,
                    regex=regex,
                    nogroup=nogroup,
                    group=group,
                )
                # new file name with file extension
                new_filename = (
                    tmdb_name
                    + " - "
                    + f"S{season}E{str(int(episode) - int(offset)).zfill(int(len(episode))).zfill(int(episode_bit))}"
                )

                if version:
                    new_filename += (
                        f" - [{version}]" if "edition-" not in version else f" - {version}"
                    )
                if not ORIGIN_NAME:
                    if web_source:
                        new_filename += f" [{web_source}]"
                    if resolution:
                        new_filename += f" [{resolution}]"
                    if medium:
                        new_filename += f" [{' '.join(medium)}]"
                    if frame:
                        new_filename += f" [{frame}]"
                    if codec:
                        new_filename += f" [{' '.join(codec)}]"
                    if audio:
                        new_filename += f" [{' '.join(audio)}]"
                    if _group:
                        new_filename += f" [{_group}]"
                else:
                    new_filename += f" - {filename_pre}"

                new_filename += f".{filename_suffix}"
                if is_filename_length_gt_255(new_filename):
                    new_filename = (
                        f"S{season}E{str(int(episode) - int(offset)).zfill(int(len(episode))).zfill(int(episode_bit))}"
                        + " - "
                        + file
                    )
            new_dir = os.path.join(dst_path, country, year, month, tmdb_name, f"Season {season}")
            new_file_path = os.path.join(new_dir, new_filename)
            if dst_path != media_path:
                scan_folders.append(new_dir)
                logger.debug(f"Added scan folder: {new_dir}")

            rename_media(os.path.join(dir, file), new_file_path, dryrun=dryrun)

    return scan_folders


def handle_movie(
    media_path,
    tmdb_id,
    dst_path=None,
    nogroup=False,
    group="",
    keep_nfo=False,
    dryrun=False,
    scan_folders=None
):
    if os.path.isfile(media_path):
        media_name = os.path.basename(media_path)
        media_path = os.path.dirname(media_path)
        isfile = True
    if dst_path is None:
        dst_path = media_path
    if scan_folders is None:
        scan_folders = []
    # 初始化 tmdb
    tmdb_name = ""
    tmdb = TMDB(movie=True)

    for dir, subdir, files in os.walk(media_path):
        removed_files = remove_hidden_files(dir, dryrun=dryrun)
        for file in removed_files:
            if file[1] == 1:
                subdir.remove(file[0])
        for _dir in subdir:
            if re.search("Sample", _dir):
                if not dryrun:
                    shutil.rmtree(os.path.join(dir, _dir))
                logger.info(f"Removed sample folder: {os.path.join(media_path, _dir)}")
        for filename in files:
            if isfile and filename != os.path.basename(media_name):
                logger.info(f"No need to handle {filename}, skip...")
                continue
            # for collections, query for each file
            tmdb_id = tmdb_id or query_tmdb_id(filename)
            if not tmdb_id:
                raise Exception(f"Failed to get info. for {media_path} from TMDB")
            (filepath, filename_pre, filename_suffix) = media_filename_pre_handle(
                dir, filename
            )

            keep_file_suffix = deepcopy(MEDIA_SUFFIX)
            if keep_nfo:
                keep_file_suffix.append("nfo")
            # remove unuseful files
            if filename_suffix.lower() not in keep_file_suffix:
                if not dryrun:
                    os.remove(filepath)
                logger.info("Removed file: " + filepath)
                continue

            details = tmdb.get_info_from_tmdb_by_id(tmdb_id=tmdb_id)
            tmdb_name = details.get("tmdb_name")
            country = details.get("country")
            year = details.get("year")
            month = details.get("month")

            if re.search(r"tmdb-\d+", filename):
                new_filename = re.sub(r".*{tmdb-\d+}", tmdb_name, filename)
                if new_filename == filename:
                    logger.warning(f"{filename}'s name does not change, skipping...")
                    continue

            (
                web_source,
                resolution,
                medium,
                frame,
                codec,
                audio,
                version,
                _group,
            ) = get_media_info_from_filename(
                filename_pre, media_type="movie", nogroup=nogroup, group=group
            )
            # new file name with file extension
            new_filename = tmdb_name

            if version:
                new_filename += (
                    f" - [{version}]" if "edition-" not in version else f" - {version}"
                )
            if not ORIGIN_NAME:
                if web_source:
                    new_filename += f" [{web_source}]"
                if resolution:
                    new_filename += f" [{resolution}]"
                if medium:
                    new_filename += f" [{' '.join(medium)}]"
                if frame:
                    new_filename += f" [{frame}]"
                if codec:
                    new_filename += f" [{' '.join(codec)}]"
                if audio:
                    new_filename += f" [{' '.join(audio)}]"
                if _group:
                    new_filename += f" [{_group}]"
            else:
                new_filename += f" - {filename_pre}"

            new_filename += f".{filename_suffix}"

            if is_filename_length_gt_255(new_filename):
                new_filename = filename
            new_dir = os.path.join(dst_path, country, year, month, tmdb_name)
            new_file_path = os.path.join(new_dir, new_filename)
            if dst_path != media_path:
                scan_folders.append(new_dir)
                logger.debug(f"Added scan folder: {new_dir}")
            rename_media(filename, new_file_path, dryrun=dryrun)

    return scan_folders


def handle_local_media(
    root="/Media/Inbox",
    dst_root="/Media",
    folders=["TVShows", "Movies", "Anime", "NSFW", "NC17-Movies", "Concerts"],
    query=False,
    dryrun=False,
):
    """处理本地已有资源

    Args:
        root (str): 处理的根目录
        folders (list): 需要处理的目录（分类）
        query (bool): 是否需要查询 TMDB
        dryrun (bool):

    Returns:
    """

    for folder in folders:
        dst_base_path = folder
        media_type = "movie"
        if re.search(r"tv", folder, flags=re.I):
            media_type = "tv"
        if re.search(r"(anime)", folder, flags=re.I):
            dst_base_path = "TVShows"
            media_type = "anime"
        if re.search(r"(movie|concert)", folder, flags=re.I):
            dst_base_path = "Movies"
        if re.search(r"nsfw", folder, flags=re.I):
            dst_base_path = "Inbox/NSFW"
            media_type = "av"

        path = os.path.join(root, folder)
        media_folders = [
            os.path.join(path, p)
            for p in os.listdir(path)
            if os.path.isdir(os.path.join(path, p))
        ]
        for media_folder in media_folders:
            tmdb_name = re.search(r"tmdb-\d+", media_folder)
            try:
                if tmdb_name:
                    ret = media_handle(
                        path=media_folder,
                        media_type=media_type,
                        dst_path=os.path.join(dst_root, dst_base_path),
                        dryrun=dryrun,
                    )
                else:
                    # 若不进行 TMDB 查询
                    if not query:
                        logger.info(f"Skipping {media_folder}")
                        continue
                    else:
                        ret = media_handle(
                            path=media_folder,
                            media_type=media_type,
                            dst_path=os.path.join(dst_root, dst_base_path),
                            dryrun=dryrun,
                        )
            except Exception as e:
                logger.error(e)
                continue
            else:
                if ret:
                    logger.info(f"Processed {media_folder}")
                else:
                    logger.error(f"Failed to process {media_folder}")


def media_handle(
    path,
    media_type,
    dst_path=None,
    regex="",
    group="",
    nogroup=False,
    episode_bit=2,
    tmdb_id=None,
    dryrun=False,
    offset=0,
    keep_nfo=False,
):
    """Media handler

    Args:
        path (str): path to media to be handled
        dst_path (str, optional): move to the dest path after handling. Defaults to "", which means no move.
        media_type (str, optional): set media type.
        regex (str, optional): regex to match the tvshow's episode number. Defaults to "".
        group (str, optional): group to be used for the new file name. Defaults to "".
        nogroup (bool, optional): whether to set the group or not. Defaults to False.
        episode_bit (int, optional): number of bits to use for the episode number. Defaults to 2.
        tmdb_id (str | None | int, optional): tmdb id of media, if set, rename folder using tmdb name.
        dryrun (bool, optional): whether to do a dryrun or not. Defaults to False.
        offset (int, optional): offset for the episode number. Defaults to 0, which means no offset.
        keep_nfo (bool, optional): keep nfo or not.

    Returns:
        bool: True if the media was handled, False otherwise

    """
    root = os.path.expanduser(path.rstrip("/"))
    tmdb_id = str(tmdb_id) if tmdb_id is not None else ""
        
    # folder to send scan request
    scan_folders = []

    if media_type == "movie":
        try:
            scan_folders = handle_movie(
                media_path=root,
                tmdb_id=tmdb_id,
                nogroup=nogroup,
                group=group,
                keep_nfo=keep_nfo,
                dryrun=dryrun,
            )
        except Exception as e:
            logger.error(f"Process {root} failed dut to {e}" )
            raise e
    elif media_type in ["tv", "anime"]:
        # handle media folder
        try:
            scan_folders = handle_tvshow(
                media_path=root,
                tmdb_id=tmdb_id,
                media_type=media_type,
                dst_path=dst_path,
                regex=regex,
                group=group,
                nogroup=nogroup,
                episode_bit=episode_bit,
                dryrun=dryrun,
                offset=offset,
                keep_nfo=keep_nfo,
                scan_folders=scan_folders
            )
        except Exception as e:
            logger.error(f"Process {root} failed dut to {e}")
            raise e
    elif media_type == "av":
        for dir, subdir, files in os.walk(root):
            remove_small_files(dir, dryrun=dryrun)
    elif media_type == "music":
        if dst_path and not dryrun:
            scan_folders.append(os.path.join(dst_path, media_name))
            logger.debug(f"Added scan folder: {os.path.join(dst_path, media_name)}")
    else:
        pass
        logger.warning("Unkown media type, skip……")

    def __send_scan_request():
        # handle scan request
        media_servers = []
        if PLEX_AUTO_SCAN:
            _plex = Plex()
            media_servers.append(_plex)
        if EMBY_AUTO_SCAN:
            _emby = Emby()
            media_servers.append(_emby)
        for server in media_servers:
            server.scan(path=set(scan_folders))

    if (PLEX_AUTO_SCAN or EMBY_AUTO_SCAN) and scan_folders:
        # 120s 后执行, 尽量避免 rclone 未更新导致路径找不到
        run_date = datetime.datetime.now() + datetime.timedelta(minutes=3)
        scheduler.add_job(
            __send_scan_request,
            trigger="date",
            run_date=run_date,
            misfire_grace_time=60,
        )
        logger.debug(f"Added scheduler job: next run at {str(run_date)}")


if __name__ == "__main__":
    args = parse()
    media_handle(
        args.path,
        media_type=args.media_type,
        dst_path=args.dst_path,
        regex=args.regex,
        group=args.group,
        nogroup=args.nogroup,
        episode_bit=args.episode_bit,
        tmdb_id=args.tmdb_id,
        dryrun=args.dryrun,
        offset=args.offset,
        keep_nfo=args.keep_nfo,
    )

    while True:
        if not scheduler.get_jobs():
            break
        sleep(30)
