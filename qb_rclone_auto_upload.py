#!/usr/bin/env python
#
# Author: WithdewHua
#


import argparse
import os
import pickle
import re
import subprocess
import time
import traceback
from copy import deepcopy
from datetime import date

import anitopy
import qbittorrentapi
from autorclone import auto_rclone
from log import logger
from media_handle import handle_local_media, media_handle
from settings import (
    CATEGORY_SETTINGS_MAPPING,
    HANDLE_LOCAL_MEDIA,
    QBIT,
    RCLONE_ALWAYS_UPLOAD,
    REMOVE_EMPTY_FOLDER,
    TG_CHAT_ID,
)
from tmdb import TMDB
from tmdbv3api.exceptions import TMDbException
from utils import (
    dump_json,
    get_file_list,
    load_json,
    remove_empty_folder,
    send_tg_msg,
    sumarize_tags,
)

script_path = os.path.split(os.path.realpath(__file__))[0]


def parse():
    parser = argparse.ArgumentParser(description="qBittorrent Auto Rclone")
    parser.add_argument(
        "-s",
        "--src",
        default="",
        help="qBittorrent download path mapping (for container), {host_path}:{container_path}",
    )

    return parser.parse_args()


def main(src_dir=""):
    # instantiate a Client using the appropriate WebUI configuration
    qbt_client = qbittorrentapi.Client(
        host=QBIT.get("host"),
        port=QBIT.get("port"),
        username=QBIT.get("user"),
        password=QBIT.get("password"),
    )

    # the Client will automatically acquire/maintain a logged-in state
    # in line with any request. therefore, this is not strictly necessary;
    # however, you may want to test the provided login credentials.
    try:
        qbt_client.auth_log_in()
    except qbittorrentapi.LoginFailed as e:
        logger.error(e)

    # display qBittorrent info
    logger.info(f"qBittorrent: {qbt_client.app.version}")
    logger.info(f"qBittorrent Web API: {qbt_client.app.web_api_version}")
    # for k,v in qbt_client.app.build_info.items(): print(f'{k}: {v}')

    # current uuid
    uuid = os.urandom(16).hex()

    # retrieve torrents filtered by tag
    while True:
        try:
            # 上传完的种子但没有处理的种子
            try:
                to_handle = load_json("to_handle_media.json")
            except Exception:
                to_handle = {}

            for torrent in qbt_client.torrents_info(sort="size"):
                if torrent.progress == 1 or torrent.state in ["uploading", "forcedUP"]:
                    # workaround：跳过刚完成少于 1min 的种子,最小限制
                    if time.time() - int(torrent.completion_on) < 60:
                        logger.info(f"{torrent.name} is completed less than 60s")
                        continue

                    # get torrent's tags
                    tags = torrent.tags.split(", ")
                    if "" in tags:
                        tags.remove("")
                    category = torrent.category
                    if re.search(r"NSFW", category):
                        tags.append("no_seed")

                    # process torrents added by MoviePilot
                    if "MOVIEPILOT" in tags:
                        category = os.path.basename(torrent.save_path.rstrip("/"))
                        # set category
                        qbt_client.torrents_set_category(
                            category=category, torrent_hashes=torrent.hash
                        )
                        # delete tag
                        qbt_client.torrents_remove_tags(
                            tags="MOVIEPILOT", torrent_hashes=torrent.hash
                        )

                    # 非媒体库目录
                    if category not in CATEGORY_SETTINGS_MAPPING.keys():
                        if "up_done" in tags and "no_seed" in tags:
                            logger.info(
                                f"{torrent.name} is completed and uploaded, cleaning up..."
                            )
                            qbt_client.torrents_delete(
                                delete_files=True, torrent_hashes=torrent.hash
                            )
                        continue

                    # 跳过需要做种，且标记了忽略的种子
                    if "ignore" in tags:
                        if "no_seed" in tags:
                            qbt_client.torrents_delete(
                                delete_files=True, torrent_hashes=torrent.hash
                            )
                        continue

                    # 如果下载量为 0，说明为辅种，直接 ignore
                    if torrent.downloaded == 0:
                        if "ignore" not in tags:
                            tags.append("ignore")
                            # add ignore tag
                            qbt_client.torrents_add_tags(
                                tags="ignore", torrent_hashes=torrent.hash
                            )
                        continue

                    # init flags
                    is_movie = (
                        True if re.search(r"Movies|Concerts", category) else False
                    )
                    is_nc17 = True if re.search(r"NC17-Movies", category) else False
                    query_flag = (
                        True if not re.search(r"NSFW|Music", category) else False
                    )
                    is_anime = True if re.search(r"Anime", category) else False
                    is_documentary, is_variety = False, False
                    is_nc17 = None
                    if "no_query" in tags:
                        query_flag = False

                    # get media info cache
                    media_info_file_path = os.path.join(script_path, "media_info.cache")
                    if os.path.exists(media_info_file_path):
                        with open(media_info_file_path, "rb") as f:
                            media_info: dict = pickle.load(f)
                    else:
                        media_info = {}

                    # get media info from torrent name
                    if re.search(r"Anime", category):
                        parse_rslt = anitopy.parse(torrent.name)
                        name = parse_rslt.get("anime_title")
                        year = parse_rslt.get("anime_year", date.today().year)
                        season = parse_rslt.get("anime_season")
                        release_group = parse_rslt.get("release_group")
                    else:
                        torrent_name_match = re.search(
                            r"^((.+?)[\s\.](\d{4})[\.\s])(?!\d{4}[\s\.])", torrent.name
                        )
                        # not matched
                        if not torrent_name_match:
                            year = ""
                            # todo: 未匹配到年份时,也进行一次匹配查询
                            try:
                                name = re.search(
                                    r"^(.+?)[\s\.](\d{3,4}[Pp])", torrent.name
                                ).group(1)
                            except Exception:
                                name = torrent.name
                        # matched year in torrent name
                        else:
                            name = " ".join(
                                re.sub(
                                    r"[\.\s][sS]\d{1,2}[\.\s]?$",
                                    " ",
                                    torrent_name_match.group(2),
                                )
                                .strip(".")
                                .split(".")
                            )
                            year = torrent_name_match.group(3)
                        season_match = re.search(
                            r"[\.\s]S(\d{2})[\s\.Ee]", torrent.name
                        )
                        season = season_match.group(1) if season_match else ""
                        release_group = torrent.name.split("-")[-1]
                    # media info cache key
                    media_info_match_key = f"{category}_{name}"
                    if year:
                        media_info_match_key += f"_{year}"
                    if season:
                        media_info_match_key += f"_S{season}"
                    if not is_movie and release_group:
                        media_info_match_key += f"_{release_group}"
                    logger.debug(f"{media_info_match_key=}")

                    # torrent is downloaded, and uploaded to GoogleDrive
                    # clean up torrent
                    logger.debug(f"{torrent.name}'s tag: {tags}")
                    if "up_done" in tags:
                        if "no_seed" in tags:
                            logger.info(
                                f"{torrent.name} is completed and uploaded, cleaning up..."
                            )
                            qbt_client.torrents_delete(
                                delete_files=True, torrent_hashes=torrent.hash
                            )
                        if "end" in tags and media_info_match_key in media_info:
                            media_info.pop(media_info_match_key)
                            with open(media_info_file_path, "wb") as f:
                                pickle.dump(media_info, f)
                            # add ignore tag
                            qbt_client.torrents_add_tags(
                                tags="ignore", torrent_hashes=torrent.hash
                            )
                            logger.info(
                                f"Removing {torrent.name}'s record: {media_info_match_key}"
                            )
                    # torrent is downloaded, and not uploaded to GoogleDrive
                    if "up_done" not in tags:
                        tmdb_name = ""
                        tmdb_id = None
                        tmdb = TMDB(movie=is_movie)

                        # get media info from file
                        local_record = False
                        write_record = True
                        media_info_rslt = media_info.get(media_info_match_key, {})
                        if media_info_rslt:
                            local_record = True
                            write_record = False
                            tmdb_name = media_info_rslt.get("tmdb_name")
                            tmdb_id = media_info_rslt.get("tmdb_id")
                            record_tags = media_info_rslt.get("tags", [])
                            is_anime = media_info_rslt.get("is_anime")
                            is_documentary = media_info_rslt.get("is_documentary")
                            is_variety = media_info_rslt.get("is_variety")
                            is_nc17 = media_info_rslt.get("is_nc17")
                            # 更新 tags
                            if tags:
                                tags = sumarize_tags(record_tags, tags)
                                # 更新记录
                                write_record = True
                                media_info_rslt.update({"tags": tags})
                            else:
                                tags = record_tags
                            logger.debug(
                                f"Got {media_info_match_key}'s info: "
                                f"\ntmdb_name: {tmdb_name}"
                                f"\ntmdb_id: {tmdb_id}"
                                f"\nrecord_tags: {record_tags}"
                                f"\ntags: {tags}"
                                f"\nis_anime: {is_anime}"
                                f"\nis_documentary: {is_documentary}"
                                f"\nis_variety: {is_variety}"
                            )
                        else:
                            media_info_rslt = {
                                "tags": tags,
                                "category": category,
                            }

                        # GoogleDrive's default base save path
                        save_path = "Inbox" + "/" + category
                        # default save name
                        save_name = tmdb_name or torrent.name

                        # get year from tag
                        year_tag = re.search(r"Y(\d{4})", ", ".join(tags))
                        year = int(year_tag.group(1)) if year_tag else year
                        # get episode offset from tag
                        offset_tag = re.search(r"O(-?\d+)", ", ".join(tags))
                        offset = int(offset_tag.group(1)) if offset_tag else 0
                        # get season info from tag
                        season_flag = re.search(r"S(\d{2})", ", ".join(tags))
                        season = season_flag.group(1) if season_flag else season
                        # get tmdb_id from tag
                        tmdb_id_tag = re.search(r"T(\d+)", ", ".join(tags))
                        tmdb_id = tmdb_id_tag.group(1) if tmdb_id_tag else tmdb_id

                        # tmdb 与记录中 tmdb 一致，直接用之前的 tmdb_name
                        if (
                            tmdb_id
                            and local_record
                            and str(tmdb_id) == str(media_info_rslt.get("tmdb_id", ""))
                        ):
                            save_name = tmdb_name
                            # None 代表没有记录，重新获取下
                            if (
                                is_anime is None
                                or is_documentary is None
                                or is_variety is None
                                or (is_nc17 is None and is_movie)
                            ):
                                _tmdb_info = tmdb.get_info_from_tmdb_by_id(tmdb_id)
                                is_anime = _tmdb_info.get("is_anime")
                                is_documentary = _tmdb_info.get("is_documentary")
                                is_variety = _tmdb_info.get("is_variety")
                                is_nc17 = _tmdb_info.get("is_nc17")
                                # 需要更新记录
                                write_record = True
                        # 没有记录，或者 tag 的 tmdb_id 发生变化
                        elif tmdb_id and (
                            not local_record
                            or (
                                local_record
                                and str(tmdb_id) not in ",".join(record_tags)
                            )
                        ):
                            try:
                                tmdb_info = tmdb.get_info_from_tmdb_by_id(tmdb_id)
                                tmdb_name = (
                                    tmdb_info.get("tmdb_name")
                                    if not tmdb_name or write_record
                                    else tmdb_name
                                )
                                # 判断是否为 anime
                                is_anime = tmdb_info.get("is_anime")
                                is_documentary = tmdb_info.get("is_documentary")
                                is_variety = tmdb_info.get("is_variety")
                                is_nc17 = tmdb_info.get("is_nc17")
                                save_name = tmdb_name
                            except Exception as e:
                                logger.error(f"Failed to get tmdb info: {e}")
                                logger.error(traceback.format_exc())
                                continue
                        # 否则通过种子名字进行查询
                        else:
                            tv_year_deviation = 0 if not year_tag else 0
                            movie_year_deviation = 0 if not year_tag else 0

                            # anime 种子名比较特殊,进行特殊处理
                            if "Anime" in category:
                                parse_rslt = anitopy.parse(torrent.name)
                                if not year_tag:
                                    if season and int(season) != 1:
                                        year = int(year) - int(season) + 1
                                if not local_record:
                                    tmdb_info = tmdb.get_info_from_tmdb(
                                        {
                                            "query": name,
                                            "first_air_date_year": int(year),
                                        },
                                        year_deviation=tv_year_deviation,
                                    )
                                    tmdb_name = tmdb_info.get("tmdb_name")
                                    tmdb_id = tmdb_info.get("tmdb_id")
                                save_name = torrent.name if not tmdb_name else tmdb_name
                            # 一般种子
                            else:
                                # 匹配到年份
                                if torrent_name_match:
                                    if (
                                        not year_tag
                                        and season
                                        and int(season) != 1
                                        and not re.search(r"HHWEB", torrent.name)
                                    ):
                                        year = int(year) - int(season) + 1
                                    # rename if there is chinese
                                    cn_match = re.match(
                                        r"\[?([\u4e00-\u9fa5]+.*?[\u4e00-\u9fa5]*?)\]? (?![\u4e00-\u9fa5]+)(.+)$",
                                        name,
                                    )
                                    if cn_match:
                                        if query_flag:
                                            if not local_record:
                                                # query tmdb with chinese or other language
                                                for i in range(2):
                                                    _g = i + 1
                                                    if is_movie:
                                                        tmdb_info = tmdb.get_info_from_tmdb(
                                                            {
                                                                "query": cn_match.group(
                                                                    _g
                                                                ),
                                                                "year": int(year),
                                                            },
                                                            year_deviation=movie_year_deviation,
                                                        )
                                                    else:
                                                        tmdb_info = tmdb.get_info_from_tmdb(
                                                            {
                                                                "query": cn_match.group(
                                                                    _g
                                                                ),
                                                                "first_air_date_year": int(
                                                                    year
                                                                ),
                                                            },
                                                            year_deviation=tv_year_deviation,
                                                        )
                                                    tmdb_name = tmdb_info.get(
                                                        "tmdb_name"
                                                    )
                                                    tmdb_id = tmdb_info.get("tmdb_id")
                                                    is_anime = tmdb_info.get("is_anime")
                                                    is_documentary = tmdb_info.get(
                                                        "is_documentary"
                                                    )
                                                    is_variety = tmdb_info.get(
                                                        "is_variety"
                                                    )
                                                    is_nc17 = tmdb_info.get("is_nc17")
                                                    if tmdb_name:
                                                        break
                                        save_name = (
                                            f"[{cn_match.group(1)}] {cn_match.group(2)} ({year})"
                                            if not tmdb_name
                                            else tmdb_name
                                        )
                                    else:
                                        if query_flag:
                                            if not local_record:
                                                if is_movie:
                                                    tmdb_info = tmdb.get_info_from_tmdb(
                                                        {
                                                            "query": name,
                                                            "year": int(year),
                                                        },
                                                        year_deviation=movie_year_deviation,
                                                    )
                                                else:
                                                    tmdb_info = tmdb.get_info_from_tmdb(
                                                        {
                                                            "query": name,
                                                            "first_air_date_year": int(
                                                                year
                                                            ),
                                                        },
                                                        year_deviation=tv_year_deviation,
                                                    )
                                                tmdb_name = tmdb_info.get("tmdb_name")
                                                tmdb_id = tmdb_info.get("tmdb_id")
                                                is_anime = tmdb_info.get("is_anime")
                                                is_documentary = tmdb_info.get(
                                                    "is_documentary"
                                                )
                                                is_variety = tmdb_info.get("is_variety")
                                                is_nc17 = tmdb_info.get("is_nc17")
                                            save_name = (
                                                name + " " + f"({year})"
                                                if not tmdb_name
                                                else tmdb_name
                                            )

                        # stop if rename fail
                        if (
                            query_flag
                            and (not tmdb_name or (not is_movie and not season))
                            and (not RCLONE_ALWAYS_UPLOAD)
                        ):
                            logger.error(
                                f"Renaming {torrent.name} failed, please adjust manually"
                            )
                            send_tg_msg(
                                chat_id=TG_CHAT_ID,
                                text=f"Renaming `{torrent.name}` failed, please adjust manually",
                            )
                            continue
                        # add season info for tvshows
                        if re.search(r"TVShows|Anime", category) and season:
                            save_name = save_name + "/" + f"Season {season.zfill(2)}"

                        # get certification info for movie
                        if tmdb.is_movie and tmdb_name:
                            # 记录中没有则进行查询
                            if is_nc17 is None:
                                tmdb.tmdb_id = tmdb_id
                                is_nc17 = tmdb.get_movie_certification()
                            if is_nc17:
                                save_path = "Inbox/NC17-Movies"

                        if re.search(r"Music", category):
                            save_name = torrent.name
                            if re.search(r"-HHWEB|LeagueCD", torrent.name):
                                tags.append("format")
                            save_path = "Music"
                            # 对于种子名在 [] 中包含歌手名-专辑名
                            if "format" in tags:
                                singer_album_match = re.search(
                                    r"^\[(.*?)\]", torrent.name
                                )
                                if singer_album_match:
                                    singer_album = singer_album_match.group(1)
                                    singer, album = singer_album.split("-", 1)
                                else:
                                    singer, album = torrent.name.split("-", 1)
                                singer = singer.strip()
                                album = album.strip()
                                save_name = f"{singer}/{album}"

                        # 根据分类/年份来决定 GD/挂载点等
                        configs = {}
                        if is_anime:
                            library = "Anime"
                        # 优先判断是否为综艺
                        elif is_variety:
                            library = "VarietyShows"
                        elif is_documentary:
                            library = "Documentary"
                        else:
                            library = category
                        if query_flag:
                            if tmdb_name:
                                year = re.search(r"\s\((\d{4})\)\s", tmdb_name).group(1)
                            for (
                                start_year,
                                end_year,
                            ), settings in CATEGORY_SETTINGS_MAPPING[library]:
                                if (start_year is None or start_year <= int(year)) and (
                                    end_year is None or int(year) <= end_year
                                ):
                                    configs = settings
                                    break
                        else:
                            configs = CATEGORY_SETTINGS_MAPPING[library][-1][1]
                        if not configs:
                            logger.error(
                                f"Can not find settings for category {category} (library: {library})"
                            )
                            continue
                        logger.debug(f"{configs=}")

                        # full path in GoogleDrive
                        google_drive = configs.get("rclone")
                        if not google_drive:
                            logger.error(
                                f"Can not find drive for category {category} (library: {library})"
                            )
                            continue
                        google_drive_save_path = (
                            f"{google_drive}:/{save_path}/" + save_name
                        )
                        # full path in host
                        if src_dir:
                            host_dir, container_dir = src_dir.split(":")
                            src_path = torrent.content_path.replace(
                                container_dir, host_dir
                            )
                        else:
                            src_path = torrent.content_path

                        src_path = src_path.replace("$", r"\$")

                        # 如果是单文件
                        if os.path.isfile(src_path):
                            files_from_file = None
                        # 如果是文件夹
                        else:
                            # torrent files list
                            torrent_files = [
                                file.get("name")
                                .removeprefix(os.path.basename(src_path))
                                .lstrip("/")
                                for file in torrent.files
                                if file.get("priority") != 0
                            ]
                            logger.debug(torrent.files)
                            logger.debug(torrent_files)
                            if not torrent_files:
                                logger.error(f"Can not find files of {torrent.name}")
                                send_tg_msg(
                                    chat_id=TG_CHAT_ID,
                                    text=f"Can not find files of `{torrent.name}`",
                                )
                                continue
                            # 检查文件夹下的文件列表，确保文件无误才进行传输
                            flag, files = get_file_list(src_path)
                            if not flag:
                                logger.error(f"Checking files list failed: {files}")
                                send_tg_msg(
                                    chat_id=TG_CHAT_ID,
                                    text=f"Checking `{torrent.name}` files list failed, ignore",
                                )
                                continue
                            if not set(torrent_files).issubset(set(files)):
                                logger.error(
                                    f"{torrent.name} files not ready yet, ignore"
                                )
                                send_tg_msg(
                                    chat_id=TG_CHAT_ID,
                                    text=f"`{torrent.name}` files not ready yet, ignore",
                                )
                                continue

                            # rclone file include
                            files_from_file = f"/tmp/files_from_{uuid}.txt"
                            with open(files_from_file, "w") as f:
                                f.write("\n".join(torrent_files))

                        # rclone copy
                        logger.info(f"{torrent.name} is completed, copying")

                        # rslt = subprocess.run(["rclone", "copy", torrent.content_path, f"{google_drive_save_path}"])
                        try:
                            auto_rclone(
                                src_path=src_path,
                                dest_path=google_drive_save_path,
                                files_from=files_from_file,
                            )
                        except Exception as e:
                            logger.error(f"Copying {torrent.name} failed: {e}")
                            send_tg_msg(
                                chat_id=TG_CHAT_ID,
                                text=f"Copying `{torrent.name}` failed",
                            )
                        else:
                            # check the target folder after copying
                            rslt = subprocess.run(
                                ["rclone", "ls", f"{google_drive_save_path}"],
                                encoding="utf-8",
                                capture_output=True,
                            )
                            # 空文件夹或者无文件夹，说明上传失败了，不再处理该种子，等待下轮处理
                            if rslt.returncode or (not rslt.stdout):
                                logger.error(f"Checking {torrent.name} failed")
                                send_tg_msg(
                                    chat_id=TG_CHAT_ID,
                                    text=f"Checking `{torrent.name}` failed",
                                )
                                continue
                            else:
                                # delete sample foler
                                if "Sample" in rslt.stdout:
                                    logger.info(
                                        f"Deleting sample folder in {torrent.name}"
                                    )
                                    rslt = subprocess.run(
                                        [
                                            "rclone",
                                            "purge",
                                            f"{google_drive_save_path}/Sample",
                                        ]
                                    )
                                    if rslt.returncode:
                                        logger.error(
                                            f"Deleting sample folder in {google_drive_save_path} failed"
                                        )
                                        send_tg_msg(
                                            chat_id=TG_CHAT_ID,
                                            text=f"Deleting sample folder in `{google_drive_save_path}` failed",
                                        )
                                    else:
                                        logger.info(
                                            f"Deleting sample folder in {google_drive_save_path} succeed"
                                        )
                                        send_tg_msg(
                                            chat_id=TG_CHAT_ID,
                                            text=f"Deleting sample folder in `{google_drive_save_path}` succeed",
                                        )

                            # upload successfully, update torrent's info
                            if "no_seed" not in tags:
                                logger.info(
                                    f"Copying {torrent.name} to {google_drive_save_path} succeed, tagging it..."
                                )
                                # add tag "up_done"
                                qbt_client.torrents_add_tags(
                                    tags="up_done", torrent_hashes=torrent.hash
                                )
                            else:
                                # delete torrent and data if no need to seed
                                logger.info(
                                    f"Copying {torrent.name} to {google_drive_save_path} succeed, deleting it..."
                                )
                                qbt_client.torrents_delete(
                                    delete_files=True, torrent_hashes=torrent.hash
                                )
                            send_tg_msg(
                                chat_id=TG_CHAT_ID,
                                text=f"`{save_name if save_name else torrent.name}` 已入库",
                            )

                        handle_flag = True
                        dst_base_path = configs.get("local")
                        media_type = "tv"
                        # tvshows handle if get tmdb_name successfully
                        if (
                            re.search(r"TVShows|Anime", category)
                            and tmdb_name
                            and "manual" not in tags
                        ):
                            media_type = "tv" if "TVShows" in category else "anime"
                        # movie handle
                        elif is_movie:
                            media_type = "movie"
                        # nsfw handle
                        elif category == "NSFW":
                            media_type = "av"
                        # music handle
                        elif category == "Music":
                            media_type = "music"  # todo
                            if "format" in tags:
                                dst_base_path += f"/{singer}"
                        else:
                            handle_flag = False

                        if handle_flag:
                            try:
                                logger.info(f"Processing {torrent.name} starts")
                                media_handle(
                                    f"{configs.get('mount_point')}/{save_path}/{save_name}",
                                    media_type=media_type,
                                    dst_path=f"{configs.get('mount_point')}/{dst_base_path}",
                                    offset=offset,
                                    tmdb_id=tmdb_id,
                                    keep_nfo=False,
                                )
                            # tmdb resource deleted
                            except TMDbException as e:
                                logger.error(f"Exception happens: {e}")
                                send_tg_msg(
                                    chat_id=TG_CHAT_ID,
                                    text=f"Failed to get TMDB item for `{torrent.name}`, please check……",
                                )
                                if media_info_match_key in media_info:
                                    media_info.pop(media_info_match_key)
                            except Exception as e:
                                logger.error(f"Exception happens: {e}")
                                send_tg_msg(
                                    chat_id=TG_CHAT_ID,
                                    text=f"Failed to do auto management for `{torrent.name}`, try again later……",
                                )
                                # 可能因为挂载缓存问题，导致无法找到文件夹，先做记录后续再尝试
                                to_handle.update(
                                    {
                                        torrent.name: {
                                            "src": f"{configs.get('mount_point')}/{save_path}/{save_name}",
                                            "media_type": media_type,
                                            "dst": f"{configs.get('mount_point')}/{dst_base_path}",
                                            "offset": offset,
                                            "keep_nfo": False,
                                            "tmdb_id": tmdb_id,
                                        }
                                    }
                                )
                            else:
                                logger.info(f"Processed {torrent.name} successfully")

                        # media_info handle
                        # add
                        if name and tmdb_name and write_record and "end" not in tags:
                            media_info_rslt.update(
                                {
                                    "tmdb_name": tmdb_name,
                                    "tmdb_id": tmdb_id,
                                    "is_anime": is_anime,
                                    "is_documentary": is_documentary,
                                    "is_variety": is_variety,
                                    "is_nc17": is_nc17,
                                }
                            )
                            media_info.update({media_info_match_key: media_info_rslt})
                        # delete
                        if local_record and "end" in tags:
                            media_info.pop(media_info_match_key)
                            qbt_client.torrents_add_tags(
                                tags="ignore", torrent_hashes=torrent.hash
                            )

                        # 持久化
                        with open(media_info_file_path, "wb") as f:
                            pickle.dump(media_info, f)

                else:
                    # torrent is in inappropiate state
                    if torrent.state in ["error", "missingFiles"]:
                        logger.warning(
                            f"{torrent.name} is in {torrent.state} state, need checking"
                        )
                        send_tg_msg(
                            chat_id=TG_CHAT_ID,
                            text=f"`{torrent.name}` is in `{torrent.state}` state, need checking",
                        )
                    else:
                        logger.debug(
                            f"{torrent.name} is in {torrent.state} ({torrent.progress * 100}%), skipping"
                        )
                    continue

            # 处理遗留的
            if to_handle:
                _ = deepcopy(to_handle)
                for t, t_info in _.items():
                    try:
                        logger.info(f"Processing {t} starts")
                        media_handle(
                            t_info.get("src"),
                            media_type=t_info.get("media_type"),
                            dst_path=t_info.get("dst"),
                            offset=t_info.get("offset"),
                            keep_nfo=t_info.get("keep_nfo"),
                            tmdb_id=t_info.get("tmdb_id"),
                        )
                    except Exception as e:
                        logger.error(f"Exception happens: {e}")
                        send_tg_msg(
                            chat_id=TG_CHAT_ID,
                            text=f"Failed to do auto management for `{t}`, try again later……",
                        )
                    else:
                        logger.info(f"Processed {t} successfully")
                        del to_handle[t]

            # 更新
            dump_json(to_handle, "to_handle_media.json")

        except Exception as e:
            logger.exception(e)
            time.sleep(60)
            continue
        # clean empty folder
        if REMOVE_EMPTY_FOLDER:
            remove_empty_folder(folders=list(CATEGORY_SETTINGS_MAPPING.keys()))

        # 处理本地资源，可能是手动加入的或者处理失败的
        if HANDLE_LOCAL_MEDIA:
            handle_local_media()

        # check interval
        time.sleep(60)


if __name__ == "__main__":
    args = parse()
    main(src_dir=args.src)
