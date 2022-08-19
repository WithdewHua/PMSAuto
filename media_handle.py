import os
import re
import argparse
import anitopy

from tmdb import TMDB
from log import logger


def parse():
    parser = argparse.ArgumentParser(description="Media handle")
    parser.add_argument("path", help="The path of the video")
    parser.add_argument("-d", "--dst_path", default="", help="Move the handled video to this path")
    parser.add_argument("-D", "--dryrun", action="store_true", help="Dryrun")
    parser.add_argument("--nogroup", action="store_true", help="No group info")
    parser.add_argument("-g", "--group", default="", help="Define group")
    parser.add_argument("-E", "--regex", default="", help="Regex expression for getting episode (episode number in group(1))")
    parser.add_argument("-N", "--episode_bit", default=2, help="Episodes' bit")
    parser.add_argument("-n", "--name", default="", help="Name of movie or series' folder")
    parser.add_argument("--offset", default=0, help="Offset of episode number")
    parser.add_argument("-T", "--media_type", choices=["movie", "tv", "anime"], help="Set video type")

    return parser.parse_args()

def media_filename_pre_handle(parent_dir_path, filename):
    # absolute path to file
    filepath = os.path.join(parent_dir_path, filename)

    # split file name into parts
    file_parts = filename.split(".")
    filename_pre, filename_suffix = ".".join(file_parts[0:-1]), file_parts[-1]

    # deal with subtitles
    if filename_suffix in ["srt", "ass", "ssa", "sup"]:
        lang_match = re.search(r"[-\.](ch[st]|[st]c)", filename_pre, re.IGNORECASE)
        filename_suffix = "zh." + filename_suffix
        if lang_match:
            filename_suffix = lang_match.group(1) + "." + filename_suffix

    return (filepath, filename_pre, filename_suffix)



def get_media_info_from_filename(filename_pre, media_type, regex=None, nogroup=False, group=None):
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

        return (episode, resolution, medium, frame, codec, audio, version, _group)

    if media_type != "movie":
        # get episode of series
        _regex = r"ep?(\d{2,4})(?!\d)"
        if regex:
            _regex = regex
        try:
            episode = re.search(_regex, filename_pre, re.IGNORECASE).group(1)
        except Exception as e:
            logger.error("No episode number found in file: " + filename_pre)
            return False

    # get resolution of video
    try:
        resolution = re.search(r"(\d{3,4}[pi])(?!\d)", filename_pre, re.IGNORECASE).group(1)
    except Exception:
        resolution = ""
    # get medium of video
    medium = re.findall(r"UHD|remux|(?:blu-?ray)|web-?dl|dvdrip|web-?rip", filename_pre, re.IGNORECASE)
    # get frame rate of video
    try:
        frame = re.search(r"\d{2,3}fps", filename_pre, re.IGNORECASE).group(0)
    except Exception:
        frame = ""
    # get codec of video
    codec = re.findall(r"x264|x265|HEVC|h265|h264", filename_pre, re.IGNORECASE)
    # get audio of video
    audio = re.findall(r"AAC|AC3|DTS(?:-HD)?|FLAC|MA(?:\.[57]\.1)?|2[Aa]udio|TrueHD|Atmos", filename_pre)
    # get version
    try:
        version = re.search(r"[\.\s\[](v2|Remastered|REPACK|PROPER|Extended (Edition)?|CC|DC|CEE|Criterion Collection)[\.\s\]]", filename_pre, re.IGNORECASE).group(1)
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
            _group = re.split(r"[-@]", filename_pre)[-1] if len(re.split(r"[-@]", filename_pre)) > 1 else ""
            # _group = filename_pre.split("-@")[-1] if len(filename_pre.split("-@")) > 1 else ""

    if media_type != "movie":
        return (episode, resolution, medium, frame, codec, audio, version, _group)
    else:
        return (resolution, medium, frame, codec, audio, version, _group)


def get_plex_edition_from_version(version: str) -> str:
    _edition_dict = {
        "extended": "{edition-Extended Edition}",
        "extended edition": "{edition-Extended Edition}",
        "cc": "{edition-Criterion Collection}",
        "criterion collection": "{edition-Criterion Collection}",
        "dc": "{edition-Direct's Cut}",
        "cee": "{edition-Central and Eastern Europe}",
    }
    return _edition_dict.get(version.lower(), version)


def handle_tvshow(media_name, filename, parent_dir_path, media_type, regex="", group="", episode_bit=2, nogroup=False, dryrun=False, offset=0):
    (filepath, filename_pre, filename_suffix) = media_filename_pre_handle(parent_dir_path, filename)

    # get season of series
    if "Specials" in filepath:
        season = "00"
    elif "Season" in filepath:
        season = re.search(r"Season\s(\d{2})", filepath).group(1)
    else:
        raise Exception(f"No season found: {filepath}")

    # remove unuseful files
    if not re.search(r"srt|ass|ssa|sup|mkv|ts|mp4", filename_suffix):
        if not dryrun:
            os.remove(filepath)
        logger.info("Removed file: " + filepath)
        return True

    try:
        (episode, resolution, medium, frame, codec, audio, version, _group) = get_media_info_from_filename(filename_pre, media_type=media_type, regex=regex, nogroup=nogroup, group=group)
    except Exception as e:
        logger.error(e)
        return False
    # new file name with file extension
    new_filename = (
        media_name
        + " - "
        + f"S{season}E{str(int(episode) - int(offset)).zfill(int(len(episode))).zfill(int(episode_bit))}"
    )

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
    if version:
        new_filename += f" [{version}]" if "edition-" not in version else f" {version}"
    new_filename += f".{filename_suffix}"

    rename_media(parent_dir_path, filename, new_filename, dryrun=dryrun)

    return True


def rename_media(parent_dir, old_name, new_name, dryrun=False):
    old_path = os.path.join(parent_dir, old_name)
    new_path = os.path.join(parent_dir, new_name)

    if not dryrun:
        os.rename(old_path, new_path)
    logger.info(old_path + " --> " + new_path)

    return new_path


def remove_hidden_files(root_dir_path, dryrun=False):
    removed_files = []
    for file in os.listdir(root_dir_path):
        if file.startswith("."):
            removed_files.append((file, 1 if os.path.isdir(file) else 0))
            if not dryrun:
                os.remove(os.path.join(root_dir_path, file))
            logger.info("Removed hidden file: " + os.path.join(root_dir_path, file))
    return removed_files


def handle_movie(parent_dir_path, filename, nogroup=False, group="", dryrun=False):
    if re.search(r"tmdb-\d+", os.path.basename(parent_dir_path)):
        tmdb_name = os.path.basename(parent_dir_path)
    else:
        match = re.search(r"^((.+?)[\s\.](\d{4})[\.\s])(?!\d{4}[\s\.])", filename)
        if not match:
            logger.error("Failed to get correct formatted name")
            return False
        name = " ".join(match.group(2).strip(".").split("."))
        year = match.group(3)
        cn_match = re.match(r"\[?([\u4e00-\u9fa5]+.*?[\u4e00-\u9fa5]*?)\]? (?![\u4e00-\u9fa5]+)(.+)$", name)
        if cn_match:
            name = cn_match.group(1)
        tmdb = TMDB(movie=True)
        tmdb_name = tmdb.get_name_from_tmdb(query_dict={"query": name, "year": year})
    if not tmdb_name:
        logger.error(f"Failed to get info. for {filename} from TMDB")
        return False

    (filepath, filename_pre, filename_suffix) = media_filename_pre_handle(parent_dir_path, filename)
    # remove unuseful files
    if filename_suffix not in ["srt", "ass", "ssa", "sup", "mkv", "ts", "mp4"]:
        if not dryrun:
            os.remove(filepath)
        logger.info("Removed file: " + filepath)
        return True

    (resolution, medium, frame, codec, audio, version, _group) = get_media_info_from_filename(filename_pre, media_type="movie", nogroup=nogroup, group=group)
    # new file name with file extension
    new_filename = tmdb_name

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
    if version:
        new_filename += f" [{version}]" if "edition-" not in version else f" {version}"
    new_filename += f".{filename_suffix}"

    parent_dir_name = os.path.basename(parent_dir_path)

    if parent_dir_name == tmdb_name:
        new_dir_path = rename_media(parent_dir_path, filename, new_filename, dryrun=dryrun)
    else:
        os.makedirs(os.path.join(parent_dir_path, tmdb_name), exist_ok=True)
        new_name = f"{tmdb_name}/{new_filename}"
        new_dir_path = rename_media(parent_dir_path, filename, new_name, dryrun=dryrun)

    return new_dir_path




def media_handle(path, media_type, dst_path="", regex="", group="", name="", nogroup=False, episode_bit=2, dryrun=False, offset=0):
    """Media handler

    Args:
        path (str): path to media to be handled
        dst_path (str, optional): move to the dest path after handling. Defaults to "", which means no move.
        media_type (str, optional): set media type.
        regex (str, optional): regex to match the tvshow's episode number. Defaults to "".
        group (str, optional): group to be used for the new file name. Defaults to "".
        name (str, optional): rename the show's root folder. Defaults to "".
        nogroup (bool, optional): whether to set the group or not. Defaults to False.
        episode_bit (int, optional): number of bits to use for the episode number. Defaults to 2.
        dryrun (bool, optional): whether to do a dryrun or not. Defaults to False.
        offset (int, optional): offset for the episode number. Defaults to 0, which means no offset.

    Returns:
        bool: True if the media was handled, False otherwise

    """
    root = os.path.expanduser(path.rstrip('/'))
    # modify season name as Season XX
    if media_type != "movie":
        season_match = re.search(r"S(eason)?\s?(\d{1,2})", os.path.basename(root))
        if season_match and f"Season {season_match.group(2).zfill(2)}" != os.path.basename(root):
            root = rename_media(os.path.dirname(root), os.path.basename(root), f"Season {season_match.group(2).zfill(2)}", dryrun=False)
        for dir in os.listdir(root):
            dir_path = os.path.join(root, dir)
            if os.path.isdir(dir_path):
                season_match = re.search(r"S(eason)?\s?(\d{1,2})", dir)
                if season_match and f"Season {season_match.group(2).zfill(2)}" != dir:
                    rename_media(root, dir, f"Season {season_match.group(2).zfill(2)}", dryrun=False)
    # remove season name from path
    media_path = re.sub(r"\/Season \d+", "", root)
    media_name = os.path.basename(media_path)
    # rename media folder if name is set
    if name:
        _parent_root_dir = os.path.dirname(root)
        root = rename_media(_parent_root_dir, media_name, name, dryrun=dryrun)
        media_name = name

    if media_type == "movie":
        for path, subdir, files in os.walk(root):
            removed_files = remove_hidden_files(path, dryrun=dryrun)
            for file in removed_files:
                if file[1] == 1:
                    subdir.remove(file[0])
            for _dir in subdir:
                if re.search("Sample", _dir):
                    if not dryrun:
                        os.remove(os.path.join(path, _dir))
                    logger.info(f"Removed sample folder: {os.path.join(path, _dir)}")

            for file in files:
                rslt = handle_movie(path, file, nogroup=nogroup, group=group, dryrun=dryrun)
                if rslt == False:
                    logger.error("Process failed: " + os.path.join(path, file))
                    continue
                elif (not isinstance(rslt, bool)) and dst_path:
                    dir_name = os.path.basename(os.path.dirname(rslt))
                    if not dryrun:
                        os.makedirs(os.path.join(dst_path, dir_name), exist_ok=True)
                        if os.path.exists(os.path.join(dst_path, dir_name, os.path.basename(rslt))):
                            logger.warning(f"File {file} exists in {os.path.join(dst_path, dir_name, os.path.basename(rslt))}, skip...")
                        os.rename(rslt, os.path.join(dst_path, dir_name, os.path.basename(rslt)))
                    logger.info(f"Moved {rslt} to {os.path.join(dst_path, dir_name, os.path.basename(rslt))}")
            if not dryrun:
                for path, dirs, files in os.walk(root, topdown=False):
                    if not files and not dirs:
                        os.rmdir(path)
            logger.info(f"Removed {root}") 
    else:
        for path, subdir, files in os.walk(root):
            removed_files = remove_hidden_files(path, dryrun=dryrun)
            for file in removed_files:
                if file[1] == 0:
                    files.remove(file[0])
            # handle each file
            for filename in files:
                rslt = handle_tvshow(media_name, filename, path, media_type=media_type, regex=regex, group=group, nogroup=nogroup, episode_bit=episode_bit, dryrun=dryrun, offset=offset)
                if not rslt:
                    logger.warning(f"Process failed: {filename}")
                    # break
                    continue
        # move to destination path
        if dst_path:
            # move all season folders to destination path
            # todo: move file one by one
            for path, subdir, files in os.walk(root):
                for file in files:
                    file_full_path = os.path.join(path, file)
                    dst_file_full_path = os.path.join(dst_path, media_name, file_full_path.split(media_name, 1)[-1].strip("/"))
                    dst_dir_full_path = os.path.dirname(dst_file_full_path)

                    if not dryrun:
                        if not os.path.exists(dst_dir_full_path):
                            os.makedirs(dst_dir_full_path)
                        if os.path.exists(dst_file_full_path):
                            logger.warning(f"File {file} exists in {dst_dir_full_path}, skip...")
                        else:
                            os.rename(file_full_path, dst_file_full_path)
                    logger.info(f"Moved {file_full_path} to {dst_file_full_path}")
            if not dryrun:
                # remove original media folder
                for path, dirs, files in os.walk(root, topdown=False):
                    if not files and not dirs:
                        os.rmdir(path)
            logger.info(f"Removed {root}")

if __name__ == "__main__":
    args = parse()
    media_handle(args.path, media_type=args.media_type, dst_path=args.dst_path, regex=args.regex, name=args.name, group=args.group, nogroup=args.nogroup, episode_bit=args.episode_bit, dryrun=args.dryrun, offset=args.offset)
