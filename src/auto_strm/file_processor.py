"""
文件处理器模块
负责处理单个媒体文件创建 strm 文件
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Union

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
        if category == "NSFW":
            return _process_nsfw_file(
                file, strm_base_path, replace_prefix, prefix, video_suffix
            )
        else:
            return _process_regular_file(
                file, strm_base_path, replace_prefix, prefix, is_movie, subtitle_suffix
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

    target_strm_file = Path(strm_base_path) / (
        str(file).removeprefix(prefix).rsplit(".", 1)[0] + ".strm"
    )

    if not target_strm_file.exists():
        if create_strm_file(Path(file_name), strm_file_path=target_strm_file):
            set_ownership(target_strm_file, UID, GID, start_prefix=str(strm_base_path))
            result_info = str(target_strm_file)

            # 处理图片/nfo 等刮削元数据
            _copy_metadata_files(file, target_strm_file, video_suffix, strm_base_path)

            return True, str(file), result_info, True
        else:
            return False, str(file), "创建 strm 文件失败", False
    else:
        logger.info(f"Strm 文件已存在：{target_strm_file}")
        return True, str(file), f"文件已存在: {target_strm_file}", True


def _process_regular_file(
    file: Path,
    strm_base_path: Path,
    replace_prefix: bool,
    prefix: str,
    is_movie: bool,
    subtitle_suffix: set,
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

    target_strm_file = target_strm_folder / (file.name + ".strm")

    # 考虑神医插件，最大占用 15 字节
    if is_filename_length_gt_255(file.name, extra_len=15):
        logger.warning(f"跳过处理文件 {file}: 文件名过长")
        return False, str(file), "文件名过长", False

    if replace_prefix:
        file_name = re.sub(r"^/.*?/", prefix, str(file))
    else:
        file_name = str(file)

    if not target_strm_file.exists():
        if create_strm_file(Path(file_name), strm_file_path=target_strm_file):
            set_ownership(
                target_strm_file,
                uid=UID,
                gid=GID,
                start_prefix=str(strm_base_path),
            )
            result_info = str(target_strm_file)

            # 处理字幕文件
            _copy_subtitle_files(
                file, target_strm_file, file_name, subtitle_suffix, strm_base_path
            )

            return True, str(file), result_info, True
        else:
            return False, str(file), "创建 strm 文件失败", False
    else:
        logger.info(f"Strm 文件已存在：{target_strm_file}")
        return True, str(file), f"文件已存在: {target_strm_file}", True


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
            logger.error(f"复制文件失败：{_file} -> {target_file}")


def _copy_subtitle_files(
    file: Path,
    target_strm_file: Path,
    file_name: str,
    subtitle_suffix: set,
    strm_base_path: Path,
):
    """复制字幕文件"""
    file_pre = file_name.rsplit(".", 1)[0]
    for subtitle_suffix_item in subtitle_suffix:
        subtitle_file = file.parent / f"{file_pre}.{subtitle_suffix_item}"
        target_file = target_strm_file.parent / f"{subtitle_file.name}"

        if target_file.exists():
            continue

        if subtitle_file.exists():
            rslt = subprocess.run(
                [
                    "rclone",
                    "copyto",
                    str(subtitle_file),
                    str(target_file),
                ],
                encoding="utf-8",
                capture_output=True,
            )
            if not rslt.returncode:
                set_ownership(
                    target_file,
                    uid=UID,
                    gid=GID,
                    start_prefix=str(strm_base_path),
                )
            else:
                logger.info(f"复制文件失败：{subtitle_file} -> {target_file}")
