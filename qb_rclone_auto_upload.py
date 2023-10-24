#!/usr/bin/env python
#
# Author: WithdewHua
#


import subprocess
import os
import re
import time
import argparse

from copy import deepcopy

import qbittorrentapi
import anitopy

from datetime import date
from autorclone import auto_rclone
from log import logger
from media_handle import media_handle, handle_local_media
from tmdb import TMDB
from utils import load_json, dump_json, send_tg_msg, remove_empty_folder, sumarize_tags
from settings import (
    RCLONE_ALWAYS_UPLOAD,
    QBIT,
    TG_CHAT_ID,
    REMOVE_EMPTY_FOLDER,
    HANDLE_LOCAL_MEDIA,
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

    # retrieve torrents filtered by tag
    while True:
        try:
            for torrent in qbt_client.torrents_info():
                if torrent.progress == 1 or torrent.state in ["uploading", "forcedUP"]:
                    # get torrent's tags
                    tags = torrent.tags.split(", ")
                    if "" in tags:
                        tags.remove("")
                    category = torrent.category
                    if category == "NSFW":
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

                    # handle torrents with specific category
                    if category not in [
                        "Movies",
                        "TVShows",
                        "NSFW",
                        "NC17-Movies",
                        "Concerts",
                        "Anime",
                        "Music",
                    ]:
                        if "no_seed" in tags:
                            logger.info(
                                f"{torrent.name} does not need to seed, cleaning up..."
                            )
                            qbt_client.torrents_delete(
                                delete_files=True, torrent_hashes=torrent.hash
                            )
                            continue
                        else:
                            continue

                    # get media info
                    media_info_file_path = os.path.join(script_path, "media_info.json")
                    if os.path.exists(media_info_file_path):
                        media_info: dict = load_json(media_info_file_path)
                    else:
                        media_info = {}

                    # get media title
                    if category == "Anime":
                        parse_rslt = anitopy.parse(torrent.name)
                        name = parse_rslt.get("anime_title")
                    else:
                        torrent_name_match = re.search(
                            r"^((.+?)[\s\.](\d{4})[\.\s])(?!\d{4}[\s\.])", torrent.name
                        )
                        # not matched
                        if not torrent_name_match:
                            # todo: 未匹配到年份时,也进行一次匹配查询
                            try:
                                name = re.search(
                                    r"^(.+?)[\s\.](\d{3,4}[Pp])", torrent.name
                                ).group(1)
                            except:
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

                    # flag
                    is_movie = (
                        True
                        if category in ["Movies", "NC17-Movies", "Concerts"]
                        else False
                    )
                    is_nc17 = True if category == "NC17-Movies" else False
                    query_flag = True if category not in ["NSFW", "Music"] else False
                    if "no_query" in tags:
                        query_flag = False

                    # torrent is downloaded, and uploaded to GoogleDrive
                    # clean up torrent
                    if "up_done" in tags and "no_seed" in tags:
                        logger.info(
                            f"{torrent.name} is completed and uploaded to GoogleDrive, cleaning up..."
                        )
                        qbt_client.torrents_delete(
                            delete_files=True, torrent_hashes=torrent.hash
                        )
                        if "end" in tags:
                            media_info.pop(name)
                            dump_json(media_info, media_info_file_path)
                            logger.debug(f"Removing {name}'s record...")
                    # torrent is downloaded, and not uploaded to GoogleDrive
                    if "up_done" not in tags:
                        tmdb_name = ""
                        tmdb = TMDB(movie=is_movie)

                        # get media info from file
                        local_record = False
                        write_record = True
                        media_info_rslt = media_info.get(name, {})
                        if media_info_rslt:
                            local_record = True
                            write_record = False
                            tmdb_name = media_info_rslt.get("tmdb_name")
                            record_tags = media_info_rslt.get("tags", [])
                            # 更新 tags
                            if tags:
                                tags = sumarize_tags(record_tags, tags)
                                # 更新记录
                                write_record = True
                                media_info_rslt.update({"tags": tags})
                            else:
                                tags = record_tags
                            logger.debug(
                                f"Got {name}'s info: "
                                f"\ntmdb_name: {tmdb_name}"
                                f"\nrecord_tags: {record_tags}"
                                f"\ntags: {tags if tags else record_tags}"
                            )
                        else:
                            media_info_rslt = {
                                "tags": tags,
                                "category": category,
                            }

                        # GoogleDrive's default base save path
                        save_path = "Inbox" + "/" + category
                        # default save name
                        save_name = torrent.name

                        season = ""
                        # get year from tag
                        year_tag = re.search(r"Y(\d{4})", ", ".join(tags))
                        year = int(year_tag.group(1)) if year_tag else None
                        # get episode offset from tag
                        offset_tag = re.search(r"O(-?\d+)", ", ".join(tags))
                        offset = int(offset_tag.group(1)) if offset_tag else 0
                        # get season info for tvshows
                        if category in ["TVShows", "Anime"]:
                            # get season info from ", ".join(tags)
                            rslt = re.search(r"S(\d{2})", ", ".join(tags))
                            if rslt:
                                season = rslt.group(1)
                            else:
                                # get season info from torrent name
                                season_match = re.search(
                                    r"[\.\s]S(\d{2})[\s\.Ee]", torrent.name
                                )
                                season = season_match.group(1) if season_match else ""
                        # get tmdb_id from tag
                        tmdb_id_tag = re.search(r"T(\d+)", ", ".join(tags))
                        tmdb_id = tmdb_id_tag.group(1) if tmdb_id_tag else None

                        # tags 中的 tmdb id 始终优先，如果存在 tmdb_id, 直接通过 tmdb id 获取名字
                        if tmdb_id:
                            tmdb_name = (
                                tmdb.get_name_from_tmdb_by_id(tmdb_id)
                                if not tmdb_name or write_record
                                else tmdb_name
                            )
                            save_name = tmdb_name
                        # 否则通过种子名字进行查询
                        else:
                            tv_year_deviation = 0 if not year_tag else 0
                            movie_year_deviation = 0 if not year_tag else 0

                            # anime 种子名比较特殊,进行特殊处理
                            if category == "Anime":
                                parse_rslt = anitopy.parse(torrent.name)
                                # name = parse_rslt.get("anime_title")
                                season = (
                                    season
                                    if season
                                    else parse_rslt.get("anime_season", "")
                                )
                                if not year_tag:
                                    year = parse_rslt.get(
                                        "anime_year", date.today().year
                                    )
                                    if season and int(season) != 1:
                                        year = int(year) - int(season) + 1
                                tmdb_name = (
                                    tmdb.get_name_from_tmdb(
                                        {"query": name, "first_air_date_year": year},
                                        year_deviation=tv_year_deviation,
                                    )
                                    if not local_record
                                    else tmdb_name
                                )
                                save_name = torrent.name if not tmdb_name else tmdb_name
                            # 一般种子
                            else:
                                # 匹配到年份
                                if torrent_name_match:
                                    if not year_tag:
                                        year = torrent_name_match.group(3)

                                    # rename if there is chinese
                                    cn_match = re.match(
                                        r"\[?([\u4e00-\u9fa5]+.*?[\u4e00-\u9fa5]*?)\]? (?![\u4e00-\u9fa5]+)(.+)$",
                                        name,
                                    )
                                    if cn_match:
                                        if query_flag:
                                            if local_record:
                                                tmdb_name = tmdb_name
                                            else:
                                                # query tmdb with chinese or other language
                                                for i in range(2):
                                                    _g = i + 1
                                                    if is_movie:
                                                        tmdb_name = tmdb.get_name_from_tmdb(
                                                            {
                                                                "query": cn_match.group(
                                                                    _g
                                                                ),
                                                                "year": int(year),
                                                            },
                                                            year_deviation=movie_year_deviation,
                                                        )
                                                    else:
                                                        if (
                                                            not year_tag
                                                            and season
                                                            and int(season) != 1
                                                        ):
                                                            year = (
                                                                int(year)
                                                                - int(season)
                                                                + 1
                                                            )
                                                        tmdb_name = tmdb.get_name_from_tmdb(
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
                                                    if tmdb_name:
                                                        break
                                        save_name = (
                                            f"[{cn_match.group(1)}] {cn_match.group(2)} ({year})"
                                            if not tmdb_name
                                            else tmdb_name
                                        )
                                    else:
                                        if query_flag:
                                            if is_movie:
                                                tmdb_name = (
                                                    tmdb_name
                                                    if local_record
                                                    else tmdb.get_name_from_tmdb(
                                                        {
                                                            "query": name,
                                                            "year": int(year),
                                                        },
                                                        year_deviation=movie_year_deviation,
                                                    )
                                                )
                                            else:
                                                if (
                                                    not year_tag
                                                    and season
                                                    and int(season) != 1
                                                ):
                                                    year = int(year) - int(season) + 1
                                                tmdb_name = (
                                                    tmdb_name
                                                    if local_record
                                                    else tmdb.get_name_from_tmdb(
                                                        {
                                                            "query": name,
                                                            "first_air_date_year": int(
                                                                year
                                                            ),
                                                        },
                                                        year_deviation=tv_year_deviation,
                                                    )
                                                )
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
                        if category in ["TVShows", "Anime"] and season:
                            save_name = save_name + "/" + f"Season {season.zfill(2)}"

                        # get certification info for movie
                        if tmdb.is_movie and tmdb_name:
                            is_nc17 = tmdb.get_movie_certification()
                            if is_nc17:
                                save_path = "Inbox/NC17-Movies"

                        if category == "Music":
                            save_name = torrent.name
                            save_path = "Music"
                            # 对于种子名在 [] 中包含歌手名-专辑名
                            if "format" in tags:
                                singer_album = re.search(
                                    r"\[(.*?)\]", torrent.name
                                ).group(1)
                                singer, album = singer_album.split("-", 1)
                                save_name = f"{singer}/{album}"

                        # full path in GoogleDrive
                        if category in ["TVShows", "Anime"]:
                            google_drive = "GD-TVShows"
                        elif category in ["Movies", "Concerts", "NC17-Movies"]:
                            google_drive = "GD-Movies"
                        elif category in ["NSFW"]:
                            google_drive = "GD-NSFW"
                        elif category in ["Music"]:
                            google_drive = "GD-Music"
                        else:
                            logger.error(f"Can not find drive for category {category}")
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

                        # rclone copy
                        logger.info(f"{torrent.name} is completed, copying")

                        # rslt = subprocess.run(["rclone", "copy", torrent.content_path, f"{google_drive_save_path}"])
                        try:
                            rslt = auto_rclone(
                                src_path=src_path, dest_path=google_drive_save_path
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
                                # change category to "Seed"
                                qbt_client.torrents_set_category(
                                    category="Seed", torrent_hashes=torrent.hash
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

                        # 处理上传完的种子
                        try:
                            to_handle = load_json("to_handle_media.json")
                        except:
                            to_handle = {}

                        handle_flag = True
                        dst_base_path = category
                        media_type = "tv"
                        # tvshows handle if get tmdb_name successfully
                        if (
                            category in ["TVShows", "Anime"]
                            and tmdb_name
                            and "manual" not in tags
                        ):
                            dst_base_path = "TVShows"
                            media_type = "tv" if category == "TVShows" else "anime"
                        # movie handle
                        elif is_movie:
                            dst_base_path = category if not is_nc17 else "NC17-Movies"
                            media_type = "movie"
                        # nsfw handle
                        elif category == "NSFW":
                            dst_base_path = category
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
                                    f"/Media/{save_path}/{save_name}",
                                    media_type=media_type,
                                    dst_path=f"/Media/{dst_base_path}",
                                    offset=offset,
                                )
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
                                            "src": f"/Media/{save_path}/{save_name}",
                                            "media_type": media_type,
                                            "dst": f"/Media/{dst_base_path}",
                                            "offset": offset,
                                        }
                                    }
                                )
                            else:
                                logger.info(f"Processed {torrent.name} successfully")
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

                        # media_info handle
                        # add
                        if (
                            name
                            and tmdb_name
                            and write_record
                            and "end" not in tags
                            and not is_movie
                        ):
                            media_info_rslt.update({"tmdb_name": tmdb_name})
                            media_info.update({name: media_info_rslt})
                            dump_json(media_info, media_info_file_path)
                        # delete
                        if local_record and "end" in tags:
                            media_info.pop(name)
                            dump_json(media_info, media_info_file_path)

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
        except Exception as e:
            logger.exception(e)
            time.sleep(60)
            continue
        # clean empty folder
        if REMOVE_EMPTY_FOLDER:
            remove_empty_folder(
                folders=[
                    "Anime",
                    "Movies",
                    "TVShows",
                    "NSFW",
                    "NC17-Movies",
                    "Concerts",
                ]
            )

        # 处理本地资源，可能是手动加入的或者处理失败的
        if HANDLE_LOCAL_MEDIA:
            handle_local_media()

        # check interval
        time.sleep(60)


if __name__ == "__main__":
    args = parse()
    main(src_dir=args.src)
