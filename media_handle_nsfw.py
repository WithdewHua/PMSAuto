import os
import shutil

from time import sleep

from log import logger
from media_handle import rename_media, send_scan_request


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
    send_scan_request(scan_folder)
    sleep(30)

