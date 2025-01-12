import argparse
import datetime
import json
import os
import pickle
import re
import traceback
from pathlib import Path
from time import sleep

from log import logger
from media_handle import add_plexmatch_file, rename_media, send_scan_request
from scheduler import Scheduler
from tmdb import TMDB


def parse():
    parser = argparse.ArgumentParser(description="MV Media handle")
    parser.add_argument("path", help="The path of media to handle")
    parser.add_argument("-t", "--type", default="movies", help="media type")
    parser.add_argument(
        "-i", "--ignore_filter", default=None, help="regex to filter folders"
    )
    return parser.parse_args()


def main(root_folder, media_type="movie", ignore_filter=None):
    is_movie = True if media_type == "movie" else False
    prefix = "Released" if is_movie else "Aired"
    t = TMDB(movie=is_movie)
    scheduler = Scheduler()
    fails = {}
    cache_path = Path("tmdb_info.cache")
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            cache = pickle.load(f)
    else:
        cache = {}
    try:
        for root_path, dirs, files in os.walk(root_folder):
            if ignore_filter and re.search(rf"{ignore_filter}", root_path):
                continue
            scan_folders = []
            for file in files:
                logger.info(f"Processing {root_path} starts")
                # 忽略隐藏文件
                if file.startswith("."):
                    continue
                filepath = Path(root_path, file)
                tmdbid_match = re.search(r"tmdb-(\d+)", str(filepath))
                if not tmdbid_match:
                    continue
                try:
                    tmdbid = tmdbid_match.group(1)
                    if cache.get(tmdbid):
                        details = cache.get(tmdbid)
                    else:
                        details = t.get_info_from_tmdb_by_id(tmdb_id=tmdbid)
                        cache.update({tmdbid: details})
                    tmdb_name = details.get("tmdb_name")
                    year = details.get("year")
                    month = details.get("month")
                    title = details.get("title")
                    season = None

                    new_folder = Path(
                        root_folder, f"{prefix}_{year}", f"M{month}", tmdb_name
                    )
                    if not is_movie:
                        season_match = re.search(
                            r"S(eason)?\s?(\d{1,2})", str(filepath)
                        )
                        if season_match:
                            season = season_match.group(2).zfill(2)
                            new_folder = new_folder / f"Season {season}"
                    scan_folders.append(str(new_folder))
                    new_filepath = new_folder / file
                    if new_filepath != filepath:
                        if new_filepath.exists():
                            logger.info(f"{new_filepath} exists, skipping")
                            continue
                        rename_media(str(filepath), str(new_filepath))
                except Exception as e:
                    logger.error(e)
                    logger.error(traceback.format_exc())
                    fails.update({str(filepath): str(e)})
                    continue
                else:
                    plex_match_file = new_folder / ".plexmatch"
                    if not plex_match_file.exists():
                        add_plexmatch_file(
                            dir=str(new_folder),
                            title=title,
                            year=year,
                            tmdb_id=tmdbid,
                            season=season,
                        )
            if scan_folders:
                run_date = datetime.datetime.now() + datetime.timedelta(minutes=3)
                scheduler.add_job(
                    send_scan_request,
                    args=(scan_folders,),
                    trigger="date",
                    run_date=run_date,
                    misfire_grace_time=60,
                    jobstore="default",
                    replace_existing=True,
                    id=f"scan_task_at_{run_date}",
                )
                logger.debug(f"Added scheduler job: next run at {str(run_date)}")
    except Exception as e:
        logger.error(e)
        logger.error(traceback.format_exc())
    finally:
        with open(cache_path, "wb") as f:
            pickle.dump(cache, f)

        with open("mv_failed.json", "a+") as f:
            json.dump(fails, f)

        while True:
            if not scheduler.scheduler.get_jobs():
                break
            sleep(30)
        sleep(60)


def scan_folder():
    src_path = Path("/Media2/TVShows")
    scheduler = Scheduler()
    for dir in src_path.iterdir():
        if re.search(r"Aired_(19\d{2}|20[01]\d)", dir.name):
            for _dir in dir.absolute().iterdir():
                for __dir in _dir.absolute().iterdir():
                    run_date = datetime.datetime.now() + datetime.timedelta(minutes=3)
                    scheduler.add_job(
                        send_scan_request,
                        args=(str(__dir.absolute()),),
                        trigger="date",
                        run_date=run_date,
                        misfire_grace_time=60,
                        jobstore="default",
                        replace_existing=True,
                        id=f"scan_task_at_{run_date}",
                    )
                    logger.debug(
                        f"Added scheduler job: next run at {str(run_date)}, folder: {str(__dir.absolute())}"
                    )

    while True:
        if not scheduler.scheduler.get_jobs():
            break
        sleep(30)
    sleep(60)


if __name__ == "__main__":
    # args = parse()
    # main(
    #     root_folder=args.path,
    #     media_type=args.type,
    #     ignore_filter=args.ignore_filter,
    # )

    scan_folder()
