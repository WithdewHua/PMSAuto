import os
import datetime
import shutil

from time import sleep

from log import logger
from media_handle import rename_media, send_scan_request
from scheduler import scheduler


src_path = "/Media/Inbox/NSFW/Done"
dst_path = "/Media/NSFW"

src_dirs = os.listdir(src_path)
dst_dirs = os.listdir(dst_path)

scan_folders = []

# number/actors/number
for src_dir in src_dirs:
    series_num = src_dir.split("-")[0].upper()
    actors = os.listdir(os.path.join(src_path, src_dir))[0]
    if actors in ["failed", "佚名"]:
        continue
    dst_dir = os.path.join(dst_path, series_num, actors, src_dir)
    if os.path.exists(dst_dir):
        logger.warning(f"Folder already exists: {dst_dir}")
        continue
    rename_media(os.path.join(src_path, src_dir, actors, src_dir), dst_dir)
    shutil.rmtree(os.path.join(src_path, src_dir))
    logger.info(f"Removed folder: {os.path.join(src_path, src_dir)}")
    scan_folders.append(dst_dir)

for scan_folder in set(scan_folders):
    run_date = datetime.datetime.now() + datetime.timedelta(minutes=3)
    scheduler.add_job(
        send_scan_request,
        args=(scan_folder,),
        trigger="date",
        run_date=run_date,
        misfire_grace_time=60,
        jobstore="default",
        id=f"scan_task_at_{run_date}",
    )
    logger.debug(f"Added scheduler job: next run at {str(run_date)}")
    sleep(30)

while True:
    if not scheduler.get_jobs():
        break
    sleep(30)

