import os
import re
import shutil
from time import sleep

from log import logger
from media_handle import rename_media, send_scan_request
from plex import Plex
from utils import remove_empty_folder

src_path = "/Media/Inbox/NSFW/Done"
dst_path = "/Media/NSFW"

src_dirs = os.listdir(src_path)
dst_dirs = os.listdir(dst_path)

scan_folders = []

release_cre = re.compile(r"<release>([\d-]+)</release>")
# actors/number
for src_dir in src_dirs:
    if src_dir in ["failed", "佚名"]:
        continue
    numbers = os.listdir(os.path.join(src_path, src_dir))
    for number in numbers:
        c_nfo = os.path.join(src_path, src_dir, number, f"{number}-C.nfo")
        no_c_nfo = os.path.join(src_path, src_dir, number, f"{number}.nfo")
        if os.path.exists(c_nfo):
            nfo = c_nfo
        elif os.path.exists(no_c_nfo):
            nfo = no_c_nfo
        else:
            nfo = None
        if nfo is None:
            logger.warning(f"{number}'s NFO not found, skip...")
            continue
        with open(nfo, "r") as f:
            date_match = release_cre.search(f.read())
        if not date_match:
            logger.warning(f"Failed to match {number}'s release data, skip...")
            continue
        year, month, _ = date_match.group(1).split("-")

        dst_dir = os.path.join(dst_path, f"Released_{year}", f"M{month}", number)
        if os.path.exists(dst_dir):
            logger.warning(f"Folder already exists: {dst_dir}")
            continue
        rename_media(os.path.join(src_path, src_dir, number), dst_dir)
        scan_folders.append(dst_dir)

# remove empty folder
# remove_empty_folder(root=src_path, folders=None)

_plex = Plex()
for scan_folder in set(scan_folders):
    send_scan_request(scan_folder, plex=True, emby=False)
    sleep(30)
    # refresh metadata
    _plex.refresh_recently_added("/Media/NSFW", max=5)
