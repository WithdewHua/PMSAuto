import json
import os
import re
import subprocess
from time import sleep

from src.auto_strm.auto_strm import auto_strm
from src.log import logger
from src.media_handle import rename_media, send_scan_request
from src.mediaserver import Plex

src_path = "/Media/Inbox/MDC-NG"
src_remote_path = "GD-NSFW-2:Inbox/MDC-NG"
dst_path = "/Media/NSFW"

scan_folders = []

release_cre = re.compile(r"<(release|premiered)>([\d-]+)</(release|premiered)>")
skip_src_dirs = {"failed", "佚名", "#未知女优", "未知演员"}


def get_nfo_files():
    """Return source NFOs discovered directly from the rclone remote."""
    result = subprocess.run(
        [
            "rclone",
            "lsjson",
            src_remote_path,
            "--files-only",
            "--no-mimetype",
            "--no-modtime",
            "--recursive",
            "--fast-list",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"获取 NFO 文件列表失败: {result.stderr.strip()}")
        return []

    try:
        files = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.error(f"解析 rclone 文件列表失败: {exc}")
        return []

    nfo_files = {}
    for file in files:
        path = file["Path"].split("/")
        if len(path) != 3:
            continue
        src_dir, number, nfo_name = path
        if src_dir in skip_src_dirs:
            continue
        if nfo_name not in {f"{number}.nfo", f"{number}-C.nfo"}:
            continue

        # Keep the original preference for the -C NFO when both files exist.
        key = (src_dir, number)
        if nfo_name.endswith("-C.nfo") or key not in nfo_files:
            nfo_files[key] = nfo_name
    return sorted(
        (src_dir, number, nfo_name) for (src_dir, number), nfo_name in nfo_files.items()
    )


nfo_files = get_nfo_files()
# actors/number
for index, (src_dir, number, nfo_name) in enumerate(nfo_files, start=1):
    logger.info(f"当前进度: {index}/{len(nfo_files)} 正在处理: {src_dir}/{number}")
    nfo = os.path.join(src_path, src_dir, number, nfo_name)
    try:
        with open(nfo, "r") as f:
            date_match = release_cre.search(f.read())
    except FileNotFoundError:
        logger.warning(f"{number}'s NFO not found, skip...")
        continue
    if not date_match:
        logger.warning(f"Failed to match {number}'s release data, skip...")
        continue
    year, month, _ = date_match.group(2).split("-")

    dst_dir = os.path.join(dst_path, f"Released_{year}", f"M{month}", number)
    if os.path.exists(dst_dir):
        logger.warning(f"Folder already exists: {dst_dir}")
        continue
    rename_media(os.path.join(src_path, src_dir, number), dst_dir)
    scan_folders.append(dst_dir)

# remove empty folder
# remove_empty_folder(root=src_path, folders=None)

plex_scan = True
emby_scan = False
emby_auto_strm = True
if plex_scan:
    _plex = Plex()
if plex_scan or emby_scan:
    logger.info("开始提交扫库请求...")
    num = 0
    for scan_folder in set(scan_folders):
        send_scan_request(scan_folder, plex=plex_scan, emby=emby_scan)
        num += 1
        logger.info(f"已提交扫库请求: {num}/{len(set(scan_folders))}")
        if num % 10 == 0:
            # refresh metadata
            if plex_scan:
                sleep(120)
                _plex.refresh_recently_added("/Media/NSFW", max=50)
    if plex_scan:
        sleep(max(120, num * 6))
        _plex.refresh_recently_added("/Media/NSFW", max=num)

if emby_auto_strm:
    logger.info("开始生成 auto strm 文件...")
    auto_strm(remote_folders=["GD-NSFW-2:NSFW:/Media"])
