"""
文件处理器模块
负责处理单个媒体文件创建 strm 文件
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union

# 添加项目根目录到 Python 路径
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.fs_operation import set_ownership
from src.log import logger
from src.settings import GID, UID
from src.strm import create_strm_file
from src.tmdb import TMDB, is_filename_length_gt_255


def process_single_file(
    file: Union[Path, str],
    strm_base_path: Union[str, Path],
    replace_prefix: bool,
    prefix: str,
    category_index: int,
    video_suffix: set,
    subtitle_suffix: set,
    remote_folder: Optional[str] = None,
):
    """
    处理单个媒体文件创建 strm

    Args:
        file: 媒体文件路径
        strm_base_path: strm 文件基础路径
        replace_prefix: 是否替换前缀
        prefix: 替换的前缀
        category_index: 分类索引
        video_suffix: 视频文件后缀集合
        subtitle_suffix: 字幕文件后缀集合
        remote_folder: rclone 远程文件夹 (rclone:folder:mount_point)

    Returns:
        tuple: (success, file_path, result_info, is_handled)
    """
    if isinstance(file, str):
        file = Path(file)
    if isinstance(strm_base_path, str):
        strm_base_path = Path(strm_base_path)

    try:
        category = file.parts[category_index]
        is_movie = True if category in ["Movies", "Concerts", "NC17-Movies"] else False

        # 对于 nsfw，直接同路径映射
        if category in ["NSFW", "Hentai"]:
            return _process_nsfw_file(
                file, strm_base_path, replace_prefix, prefix, video_suffix
            )
        else:
            return _process_regular_file(
                file,
                strm_base_path,
                replace_prefix,
                prefix,
                is_movie,
                subtitle_suffix,
                remote_folder=remote_folder,
            )
    except Exception as e:
        logger.error(f"处理文件 {file} 时发生错误: {e}")
        return False, str(file), f"处理异常: {e}", False


def _process_nsfw_file(
    file: Path,
    strm_base_path: Path,
    replace_prefix: bool,
    prefix: str,
    video_suffix: set,
):
    """处理 NSFW 类型文件"""
    if replace_prefix:
        file_name = re.sub(r"^/.*?/", prefix, str(file))
    else:
        file_name = str(file)
    # 在处理 nsfw 视频文件时，会复制同目录下的图片/nfo 等刮削元数据
    # 所有如果不是视频文件，直接跳过，并认为已处理
    if file.suffix.lstrip(".").lower() not in video_suffix:
        logger.info(f"跳过处理文件 {file}: NSFW 非视频文件")
        return (
            True,
            str(file),
            str(Path(strm_base_path, file_name.removeprefix(prefix))),
            True,
        )

    target_strm_file = Path(strm_base_path) / (
        file_name.removeprefix(prefix).rsplit(".", 1)[0] + ".strm"
    )

    if not target_strm_file.exists():
        if create_strm_file(Path(file_name), strm_file_path=target_strm_file):
            set_ownership(target_strm_file, UID, GID, start_prefix=str(strm_base_path))

            # 处理图片/nfo 等刮削元数据
            _copy_metadata_files(file, target_strm_file, video_suffix, strm_base_path)

            return True, str(file), str(target_strm_file), True
        else:
            return False, str(file), "创建 strm 文件失败", False
    else:
        logger.info(f"Strm 文件已存在：{target_strm_file}")
        return True, str(file), str(target_strm_file), True


def _process_regular_file(
    file: Path,
    strm_base_path: Path,
    replace_prefix: bool,
    prefix: str,
    is_movie: bool,
    subtitle_suffix: set,
    remote_folder: Optional[str] = None,
):
    """处理常规类型文件"""
    year = re.search(
        r"(Aired|Released)_(?P<year>\d{4})|\s\((?P<year2>\d{4})\)\s",
        file.as_posix(),
    )

    if not year:
        return False, str(file), "未获取到年份信息", False

    year = year.group("year") or year.group("year2")
    year_prefix = "Aired_" if not is_movie else "Released_"
    tmdb_name = file.parent.parent.name if not is_movie else file.parent.name

    if "tmdb-" not in tmdb_name:
        logger.warning(f"跳过处理文件 {file}: 无 TMDB 名字")
        return False, str(file), "无 TMDB 名字", False

    # 构建目标文件夹路径
    target_strm_folder = _build_target_folder_path(
        strm_base_path, file, year_prefix, year, tmdb_name, is_movie
    )
    is_subtitle = file.suffix.lstrip(".").lower() in subtitle_suffix
    if not is_subtitle:
        target_strm_file = target_strm_folder / (file.name + ".strm")
    else:
        # 检查是否存在 strm 文件
        file_name = None
        for _file in target_strm_folder.iterdir():
            if not _file.name.endswith(".strm"):
                continue
            # 去掉 .mkv 等后缀，再去掉 .strm
            file_pre = _file.name.rsplit(".", 2)[0]
            if file.name.startswith(file_pre):
                file_name = (
                    f"{_file.name.rsplit('.', 1)[0]}{file.name.removeprefix(file_pre)}"
                )
                break
        if not file_name:
            logger.warning(f"跳过处理文件 {file}: 未找到对应的 strm 文件")
            return False, str(file), "未找到对应的 strm 文件", False
        target_strm_file = target_strm_folder / file_name
    # 考虑神医插件，最大占用 15 字节
    if not is_subtitle and is_filename_length_gt_255(file.name, extra_len=15):
        logger.warning(f"跳过处理文件 {file}: 文件名过长")
        return False, str(file), "文件名过长", False

    if replace_prefix:
        file_name = re.sub(r"^/.*?/", prefix, str(file))
    else:
        file_name = str(file)

    if not target_strm_file.exists():
        if not is_subtitle:
            if create_strm_file(Path(file_name), strm_file_path=target_strm_file):
                set_ownership(
                    target_strm_file,
                    uid=UID,
                    gid=GID,
                    start_prefix=str(strm_base_path),
                )

                return True, str(file), str(target_strm_file), True
            else:
                return False, str(file), "创建 strm 文件失败", False
        else:
            # 直接复制字幕文件
            if copy_file(Path(file), target_strm_file, strm_base_path, remote_folder):
                return True, str(file), str(target_strm_file), True
            else:
                return False, str(file), f"字幕文件复制失败: {target_strm_file}", False

    else:
        logger.info(f"文件已存在：{target_strm_file}")
        return True, str(file), str(target_strm_file), True


def _build_target_folder_path(
    strm_base_path: Path,
    file: Path,
    year_prefix: str,
    year: str,
    tmdb_name: str,
    is_movie: bool,
) -> Path:
    """构建目标文件夹路径"""
    category = file.parts[2]  # 假设 category_index=2

    # 旧格式
    target_strm_folder = strm_base_path / category / f"{year_prefix}{year}" / tmdb_name

    # 没有则采用新格式
    if not target_strm_folder.exists():
        tmdb_id = re.search(r"tmdb-(\d+)", tmdb_name).group(1)
        tmdb = TMDB(movie=is_movie)
        tmdb_info = tmdb.get_info_from_tmdb_by_id(tmdb_id)
        target_strm_folder = (
            strm_base_path
            / category
            / f"{year_prefix}{year}"
            / f"M{tmdb_info.get('month')}"
            / tmdb_name
        )

    if not is_movie:
        # 季度信息
        season = file.parent.name
        if "Season" not in season:
            raise ValueError(f"无季度信息: {season}")
        target_strm_folder = target_strm_folder / file.parent.name

    return target_strm_folder


def _copy_metadata_files(
    file: Path, target_strm_file: Path, video_suffix: set, strm_base_path: Path
):
    """复制元数据文件（用于NSFW）"""
    for _file in file.parent.iterdir():
        if _file.name == file.name:
            continue
        if _file.name.rsplit(".", 1)[-1] in video_suffix:
            continue

        target_file = target_strm_file.parent / _file.name
        if target_file.exists():
            continue

        logger.info(f"复制文件：{_file} -> {target_file}")
        rslt = subprocess.run(
            ["rclone", "copyto", str(_file), str(target_file)],
            encoding="utf-8",
            capture_output=True,
        )
        if not rslt.returncode:
            set_ownership(target_file, UID, GID, start_prefix=str(strm_base_path))
        else:
            logger.error(f"复制文件失败：{_file} -> {target_file}: {rslt.stderr}")


def copy_file(
    src: Path, dest: Path, strm_base_path: Path, remote_folder: Optional[str] = None
):
    """复制文件"""
    if dest.exists():
        logger.info(f"文件已存在，跳过复制：{dest}")
        return

    if remote_folder:
        remote_folder = remote_folder.split(":")
        if len(remote_folder) != 3:
            src = src
        else:
            rclone, _, mount_point = remote_folder[:]
            src = f"{rclone}:{str(src).removeprefix(mount_point)}"

    logger.info(f"复制文件：{src} -> {dest}")
    rslt = subprocess.run(
        ["rclone", "copyto", str(src), str(dest)],
        encoding="utf-8",
        capture_output=True,
    )
    if not rslt.returncode:
        set_ownership(dest, UID, GID, start_prefix=str(strm_base_path))
        return True
    else:
        logger.error(f"复制文件失败：{src} -> {dest}: {rslt.stderr}")
        return False
