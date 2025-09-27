"""
文件收集模块
负责从远程文件夹收集视频文件信息
"""

import json
import pickle
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# 添加项目根目录到 Python 路径
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.log import logger
from src.settings import DATA_DIR, SUBTITLE_SUFFIX, VIDEO_SUFFIX


def traverse_rclone_remote(
    remote: str,
    path: str = "",
    mount_point: str = "",
    suffix: Optional[list[str]] = None,
) -> list[Path]:
    """
    遍历 rclone remote，返回所有文件的路径列表

    Args:
        remote: rclone remote 名称
        path: 远程路径
        mount_point: 挂载点
        suffix: 文件后缀列表

    Returns:
        文件路径列表
    """
    logger.info(f"开始遍历 rclone remote: {remote}:{path}")
    if suffix is None:
        suffix = []
    cmd = [
        "rclone",
        "lsjson",
        f"{remote}:{path}",
        "--files-only",
        "--no-mimetype",
        "--no-modtime",
        "--recursive",
        "--fast-list",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"遍历 rclone remote 失败: {result.stderr}")
        return []
    files = json.loads(result.stdout)
    file_paths = []
    for file in files:
        file_path = file["Path"]
        if file["IsDir"]:
            continue
        if file_path.rsplit(".", 1)[-1].lower() not in suffix:
            continue
        file_paths.append(Path(mount_point) / path / file_path)
    # 保存到文件中
    with open(
        Path(DATA_DIR) / f"{remote}_{path}.json", mode="w", encoding="utf-8"
    ) as f:
        json.dump([str(p) for p in file_paths], f, ensure_ascii=False, indent=4)
    return file_paths


def get_remote_folder_video_files(
    remote_folder: str,
    read_from_file: bool = False,
    continue_if_file_not_exist: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """
    获取 remote_folder 下所有视频文件路径（字符串列表）

    Args:
        remote_folder: 远程文件夹路径，格式可为 'remote:path:mount_point' 或本地路径
        read_from_file: 是否从缓存文件读取
        continue_if_file_not_exist: 缓存文件不存在时是否继续处理

    Returns:
        视频文件路径字符串列表
    """

    logger.info(f"获取远程文件夹视频文件列表：{remote_folder}")
    media_files = []

    if ":" in remote_folder:
        remote, remote_path, mount_point = remote_folder.split(":", 2)
        if read_from_file:
            json_file = Path(DATA_DIR) / f"{remote}_{remote_path}.json"
            if json_file.exists():
                with open(json_file, mode="r", encoding="utf-8") as f:
                    media_files = [Path(p) for p in json.load(f)]
            elif continue_if_file_not_exist:
                logger.warning(
                    f"未找到缓存文件 {json_file}，将重新遍历 {remote}:{remote_path}"
                )
                media_files = traverse_rclone_remote(
                    remote, remote_path, mount_point, VIDEO_SUFFIX + SUBTITLE_SUFFIX
                )
        else:
            media_files = traverse_rclone_remote(
                remote, remote_path, mount_point, VIDEO_SUFFIX + SUBTITLE_SUFFIX
            )
    else:
        remote_folder_path = Path(remote_folder)
        if not remote_folder_path.exists():
            logger.warning(f"远程文件夹 {remote_folder} 不存在，跳过")
            return []
        logger.info(f"开始遍历文件夹：{remote_folder}")
        for file in remote_folder_path.rglob("*"):
            if file.is_file() and file.suffix.lstrip(".").lower() in (
                VIDEO_SUFFIX + SUBTITLE_SUFFIX
            ):
                media_files.append(file)

    all_files, video_files, subtitle_files = [], [], []
    for file in media_files:
        all_files.append(str(file))
        if file.suffix.lstrip(".").lower() in VIDEO_SUFFIX:
            video_files.append(str(file))
        if file.suffix.lstrip(".").lower() in SUBTITLE_SUFFIX:
            subtitle_files.append(str(file))

    return all_files, video_files, subtitle_files


def collect_files_from_remote_folder(
    remote_folder: str,
    read_from_file: bool,
    continue_if_file_not_exist: bool,
    increment: bool,
) -> tuple[str, list[str], list[str], dict[str, str], dict[str, str]]:
    """
    从单个远程文件夹收集文件信息，包含增量处理逻辑

    Args:
        remote_folder: 远程文件夹路径
        read_from_file: 是否从缓存文件读取
        continue_if_file_not_exist: 缓存文件不存在时是否继续处理
        increment: 是否增量处理

    Returns:
        tuple: (remote_folder, video_files, subtitle_files, last_handled, to_delete_files)
    """

    logger.info(f"开始收集远程文件夹文件：{remote_folder}")
    handled_persisted_file = f"{remote_folder.strip('/').replace('/', '_')}_handled.pkl"
    last_handled = {}
    if increment and Path(DATA_DIR, handled_persisted_file).exists():
        with open(Path(DATA_DIR, handled_persisted_file), "rb") as f:
            _handled = pickle.load(f)
            for file_path, strm_file_path in _handled:
                last_handled[file_path] = strm_file_path

    start_time = time.time()
    media_files, video_files, subtitle_files = get_remote_folder_video_files(
        remote_folder, read_from_file, continue_if_file_not_exist
    )

    # 计算需要删除的多余 strm 文件及字幕文件
    to_delete_files = {}
    for file_path in set(last_handled.keys()) - set(media_files):
        to_delete_files[file_path] = last_handled[file_path]

    logger.info(
        f"{remote_folder} 找到 {len(video_files)} 个视频文件，{len(subtitle_files)} 个字幕文件，"
        f"需要删除 {len(to_delete_files)} 个多余的文件，"
        f"耗时 {round(time.time() - start_time, 2)}s"
    )

    return remote_folder, video_files, subtitle_files, last_handled, to_delete_files
