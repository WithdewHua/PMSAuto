import argparse
import os
import pickle
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Optional, Union
from urllib.parse import quote

from log import logger
from settings import GID, STRM_FILE_PATH, STRM_MEDIA_SOURCE, UID
from utils import is_filename_length_gt_255


def parse():
    parser = argparse.ArgumentParser(description="AutoStrm")
    parser.add_argument("-f", "--folder", nargs="+", help="指定要处理的远程文件夹")
    parser.add_argument(
        "-d", "--dest", default=STRM_FILE_PATH, help="存放 strm 文件的文件夹"
    )

    return parser.parse_args()


def set_ownership(
    path: Path,
    uid: Union[str, int] = UID,
    gid: Union[str, int] = GID,
    recursive=True,
    start_prefix=None,
):
    if recursive:
        current_path = ""
        file_parts = str(path).strip("/").split("/")
        for part in file_parts:
            if not part:
                continue
            current_path = f"{current_path}/{part}" if current_path else f"/{part}"
            if start_prefix and start_prefix not in current_path:
                continue
            os.chown(current_path, uid=uid, gid=gid)
            logger.info(f"修改文件(夹)权限：{current_path} ({uid}:{gid})")
    else:
        os.chown(Path, uid, gid)
        logger.info(f"修改文件(夹)权限：{current_path} ({uid}:{gid})")


def create_strm_file(
    file_path: Path,
    strm_path: Path = Path(STRM_FILE_PATH),
    strm_file_path: Optional[Path] = None,
    media_source: str = STRM_MEDIA_SOURCE,
):
    """
    创建 .strm 文件

    Args:
        file_path: 媒体文件的完整路径
        strm_path: .strm 文件存放目录
        strm_file_path: 指定 .strm 文件的完整路径（包含文件名），优先级高于 strm_path
        media_source: 媒体源 URL 前缀
    """
    try:
        # 优先使用 strm_file_path 参数
        if strm_file_path:
            strm_path = strm_file_path.parent
        # 确保 strm 目录存在
        strm_path.mkdir(parents=True, exist_ok=True)

        # 构造 .strm 文件的内容
        strm_content = f"{media_source.rstrip('/')}/{quote(str(file_path).lstrip('/'))}"

        # 构造 .strm 文件的完整路径
        strm_file_name = file_path.name + ".strm"
        strm_file_full_path = (
            (strm_path / strm_file_name) if not strm_file_path else strm_file_path
        )

        # 写入 .strm 文件
        strm_file_full_path.write_text(strm_content, encoding="utf-8")

        # 设置权限
        for item in strm_path.rglob("*"):
            shutil.chown(str(item), user=UID, group=GID)
        shutil.chown(str(strm_path), user=UID, group=GID)

        logger.info(f"为 {file_path} 创建 strm 文件成功: {strm_file_full_path}")
        return True
    except Exception as e:
        logger.error(f"为 {file_path} 创建 strm 文件失败: {e}")
        return False


def auto_strm(
    remote_folders: list[str],
    strm_base_path: Union[str, Path] = Path(STRM_FILE_PATH),
    replace_prefix: bool = True,
    prefix: str = "/Media/",
    category_index: int = 2,
):
    """
    自动为远程文件夹中的媒体文件创建 .strm 文件

    Args:
        remote_folders: 远程文件夹列表
        strm_base_path: .strm 文件存放目录
    """
    from settings import SUBTITLE_SUFFIX, VIDEO_SUFFIX

    if isinstance(strm_base_path, str):
        strm_base_path = Path(strm_base_path)

    not_handled = defaultdict(set)
    handled = defaultdict(set)
    for remote_folder in remote_folders:
        logger.info(f"开始处理远程文件夹：{remote_folder}")
        remote_folder_path = Path(remote_folder)
        if not remote_folder_path.exists():
            logger.warning(f"远程文件夹 {remote_folder} 不存在，跳过")
            continue
        for file in remote_folder_path.rglob("*"):
            if file.is_file() and file.suffix.lstrip(".").lower() in VIDEO_SUFFIX:
                logger.info(f"开始处理文件 {file}")
                category = file.parts[category_index]
                is_movie = (
                    True if category in ["Movies", "Concerts", "NC17-Movies"] else False
                )
                # 对于 nsfw，直接同路径映射
                if category == "NSFW":
                    if replace_prefix:
                        file_name = re.sub(r"^/.*?/", prefix, str(file))
                    else:
                        file_name = str(file)
                    target_strm_file = Path(strm_base_path) / (
                        str(file).removeprefix(prefix).rsplit(".", 1)[0] + ".strm"
                    )
                    if not target_strm_file.exists():
                        if create_strm_file(
                            Path(file_name), strm_file_path=target_strm_file
                        ):
                            set_ownership(
                                target_strm_file, start_prefix=str(strm_base_path)
                            )
                            handled[remote_folder].add((str(file), target_strm_file))
                        else:
                            handled[remote_folder].add(
                                (str(file), "创建 strm 文件失败")
                            )
                    else:
                        logger.info(f"Strm 文件已存在：{target_strm_file}")
                    # 处理图片/nfo 等刮削元数据
                    for _file in file.parent.iterdir():
                        if _file.name == file.name:
                            continue
                        if _file.name.rsplit(".", 1)[-1] in VIDEO_SUFFIX:
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
                            set_ownership(target_file, start_prefix=str(strm_base_path))
                        else:
                            logger.error(f"复制文件失败：{_file} -> {target_file}")

                else:
                    year = re.search(
                        r"(Aired|Released)_(?P<year>\d{4})|\s\((?P<year2>\d{4})\)\s",
                        file.as_posix(),
                    )
                    if year:
                        year = year.group("year") or year.group("year2")
                        year_prefix = "Aired_" if is_movie else "Released_"
                        tmdb_name = (
                            file.parent.parent.name
                            if not is_movie
                            else file.parent.name
                        )
                        if "tmdb-" not in tmdb_name:
                            logger.warning(f"跳过处理文件 {file}: 无 TMDB 名字")
                            not_handled[remote_folder].add((str(file), "无 TMDB 名字"))
                            continue
                        target_strm_folder = (
                            strm_base_path
                            / category
                            / f"{year_prefix}{year}"
                            / tmdb_name
                        )
                        if not is_movie:
                            # 季度信息
                            season = file.parent.name
                            if "Season" not in season:
                                logger.warning(f"跳过处理文件 {file}: 无季度信息")
                                not_handled[remote_folder].add(
                                    (str(file), "无季度信息")
                                )
                                continue
                            target_strm_folder = target_strm_folder / file.parent.name
                        target_strm_file = target_strm_folder / (file.name + ".strm")
                        if is_filename_length_gt_255(target_strm_file.name):
                            logger.warning(f"跳过处理文件 {file}: 文件名过长")
                            not_handled[remote_folder].add((str(file), "文件名过长"))
                            continue

                        if replace_prefix:
                            file_name = re.sub(r"^/.*?/", prefix, str(file))
                        else:
                            file_name = str(file)
                        if not target_strm_file.exists():
                            if create_strm_file(
                                Path(file_name), strm_file_path=target_strm_file
                            ):
                                handled[remote_folder].add(
                                    (str(file), target_strm_file)
                                )
                                set_ownership(
                                    target_strm_file, start_prefix=str(strm_base_path)
                                )
                            else:
                                not_handled[remote_folder].add(
                                    (str(file), "创建 strm 文件失败")
                                )
                        else:
                            logger.info(f"Strm 文件已存在：{target_strm_file}")
                        # 检查是否存在字幕
                        file_pre = file_name.rsplit(".", 1)[0]
                        for subtitle_suffix in SUBTITLE_SUFFIX:
                            subtitle_file = (
                                file.parent / f"{file_pre}.{subtitle_suffix}"
                            )
                            target_file = (
                                target_strm_file.parent / f"{subtitle_file.name}"
                            )
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
                                        target_file, start_prefix=str(strm_base_path)
                                    )
                                else:
                                    logger.info(
                                        f"复制文件失败：{subtitle_file} -> {target_file}"
                                    )
                    else:
                        not_handled[remote_folder].add((str(file), "未获取到年份信息"))
            else:
                logger.info(f"{file} 无需处理，跳过")
                continue
        with open(
            Path(__file__).parent
            / f"{remote_folder.strip('/').replace('/', '_')}_handled.pkl",
            "wb",
        ) as f:
            pickle.dump(handled[remote_folder], f)
        with open(
            Path(__file__).parent
            / f"{remote_folder.strip('/').replace('/', '_')}_not_handled.pkl",
            "wb",
        ) as f:
            pickle.dump(not_handled[remote_folder], f)
        logger.info(
            f"处理完成，已处理 {len(handled[remote_folder])} 个文件，未处理 {len(not_handled[remote_folder])} 个文件"
        )


if __name__ == "__main__":
    args = parse()
    auto_strm(
        remote_folders=args.folder,
        strm_base_path=args.dest,
    )
