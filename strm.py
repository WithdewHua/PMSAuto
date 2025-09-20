import argparse
import json
import os
import pickle
import re
import shutil
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=os.cpu_count(),
        help=f"最大线程数，默认为 {os.cpu_count()}",
    )
    parser.add_argument(
        "--read-from-file",
        action="store_true",
        help="是否从缓存文件读取文件列表，默认 False",
    )
    parser.add_argument(
        "--continue-if-file-not-exist",
        action="store_true",
        help="如果缓存文件不存在，是否继续处理，默认 False",
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry Run 模式")

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


def process_single_file(
    file: Path,
    strm_base_path: Path,
    replace_prefix: bool,
    prefix: str,
    category_index: int,
    video_suffix: set,
    subtitle_suffix: set,
):
    """
    处理单个媒体文件创建 strm

    Returns:
        tuple: (success, file_path, result_info, is_handled)
    """
    try:
        category = file.parts[category_index]
        is_movie = True if category in ["Movies", "Concerts", "NC17-Movies"] else False

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
                if create_strm_file(Path(file_name), strm_file_path=target_strm_file):
                    set_ownership(target_strm_file, start_prefix=str(strm_base_path))
                    result_info = str(target_strm_file)

                    # 处理图片/nfo 等刮削元数据
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
                            set_ownership(target_file, start_prefix=str(strm_base_path))
                        else:
                            logger.error(f"复制文件失败：{_file} -> {target_file}")

                    return True, str(file), result_info, True
                else:
                    return False, str(file), "创建 strm 文件失败", False
            else:
                logger.info(f"Strm 文件已存在：{target_strm_file}")
                return True, str(file), f"文件已存在: {target_strm_file}", True

        else:
            year = re.search(
                r"(Aired|Released)_(?P<year>\d{4})|\s\((?P<year2>\d{4})\)\s",
                file.as_posix(),
            )
            if year:
                year = year.group("year") or year.group("year2")
                year_prefix = "Aired_" if is_movie else "Released_"
                tmdb_name = (
                    file.parent.parent.name if not is_movie else file.parent.name
                )
                if "tmdb-" not in tmdb_name:
                    logger.warning(f"跳过处理文件 {file}: 无 TMDB 名字")
                    return False, str(file), "无 TMDB 名字", False

                target_strm_folder = (
                    strm_base_path / category / f"{year_prefix}{year}" / tmdb_name
                )
                if not is_movie:
                    # 季度信息
                    season = file.parent.name
                    if "Season" not in season:
                        logger.warning(f"跳过处理文件 {file}: 无季度信息")
                        return False, str(file), "无季度信息", False
                    target_strm_folder = target_strm_folder / file.parent.name

                target_strm_file = target_strm_folder / (file.name + ".strm")
                if is_filename_length_gt_255(target_strm_file.name):
                    logger.warning(f"跳过处理文件 {file}: 文件名过长")
                    return False, str(file), "文件名过长", False

                if replace_prefix:
                    file_name = re.sub(r"^/.*?/", prefix, str(file))
                else:
                    file_name = str(file)

                if not target_strm_file.exists():
                    if create_strm_file(
                        Path(file_name), strm_file_path=target_strm_file
                    ):
                        set_ownership(
                            target_strm_file, start_prefix=str(strm_base_path)
                        )
                        result_info = str(target_strm_file)

                        # 检查是否存在字幕
                        file_pre = file_name.rsplit(".", 1)[0]
                        for subtitle_suffix_item in subtitle_suffix:
                            subtitle_file = (
                                file.parent / f"{file_pre}.{subtitle_suffix_item}"
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

                        return True, str(file), result_info, True
                    else:
                        return False, str(file), "创建 strm 文件失败", False
                else:
                    logger.info(f"Strm 文件已存在：{target_strm_file}")
                    return True, str(file), f"文件已存在: {target_strm_file}", True
            else:
                return False, str(file), "未获取到年份信息", False
    except Exception as e:
        logger.error(f"处理文件 {file} 时发生错误: {e}")
        return False, str(file), f"处理异常: {e}", False


# 遍历 rclone remote
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
        Path(__file__).parent / f"{remote}_{path}.json", mode="w", encoding="utf-8"
    ) as f:
        json.dump([str(p) for p in file_paths], f, ensure_ascii=False, indent=4)
    return file_paths


def auto_strm(
    remote_folders: list[str],
    strm_base_path: Union[str, Path] = Path(STRM_FILE_PATH),
    replace_prefix: bool = True,
    prefix: str = "/Media/",
    category_index: int = 2,
    max_workers: int = 4,
    read_from_file: bool = False,
    continue_if_file_not_exist: bool = False,
    dry_run: bool = False,
):
    """
    自动为远程文件夹中的媒体文件创建 .strm 文件

    Args:
        remote_folders: 远程文件夹列表
        strm_base_path: .strm 文件存放目录
        max_workers: 最大线程数
    """
    from settings import SUBTITLE_SUFFIX, VIDEO_SUFFIX

    if isinstance(strm_base_path, str):
        strm_base_path = Path(strm_base_path)

    not_handled = defaultdict(set)
    handled = defaultdict(set)

    for remote_folder in remote_folders:
        logger.info(f"开始处理远程文件夹：{remote_folder}")
        handled_persisted_file = (
            f"{remote_folder.strip('/').replace('/', '_')}_handled.pkl"
        )
        last_handled = {}
        if Path(handled_persisted_file).exists():
            with open(handled_persisted_file, "rb") as f:
                _handled = pickle.load(f)
                for file_path, strm_file_path in _handled:
                    last_handled[file_path] = strm_file_path

        start_time = time.time()
        # 收集所有符合条件的文件
        video_files = []
        if ":" in remote_folder:
            remote, remote_path, mount_point = remote_folder.split(":", 2)
            if read_from_file:
                json_file = Path(__file__).parent / f"{remote}_{remote_path}.json"
                if json_file.exists():
                    with open(json_file, mode="r", encoding="utf-8") as f:
                        video_files = [Path(p) for p in json.load(f)]
                elif continue_if_file_not_exist:
                    logger.warning(
                        f"未找到缓存文件 {json_file}，将重新遍历 {remote}:{remote_path}"
                    )
                    video_files = traverse_rclone_remote(
                        remote, remote_path, mount_point, VIDEO_SUFFIX
                    )
            else:
                video_files = traverse_rclone_remote(
                    remote, remote_path, mount_point, VIDEO_SUFFIX
                )
        else:
            remote_folder_path = Path(remote_folder)
            if not remote_folder_path.exists():
                logger.warning(f"远程文件夹 {remote_folder} 不存在，跳过")
                continue

            logger.info(f"开始遍历文件夹：{remote_folder}")

            for file in remote_folder_path.rglob("*"):
                if file.is_file() and file.suffix.lstrip(".").lower() in VIDEO_SUFFIX:
                    video_files.append(file)
                else:
                    logger.info(f"跳过 {file}")
        if not video_files:
            logger.info(
                f"{remote_folder} 找到 {len(video_files)} 个视频文件，退出处理..."
            )
            continue
        logger.info(
            f"{remote_folder} 找到 {len(video_files)} 个视频文件，耗时 {round(time.time() - start_time, 2)}s, 开始多线程处理..."
        )

        # 使用多线程处理文件
        to_handle_files = set(video_files) - set(last_handled.keys())
        to_delete_strm_files = set(last_handled.keys()) - set(video_files)
        deleted_strm_files = 0
        if not dry_run:
            processed_count = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_file = {
                    executor.submit(
                        process_single_file,
                        file,
                        strm_base_path,
                        replace_prefix,
                        prefix,
                        category_index,
                        VIDEO_SUFFIX,
                        SUBTITLE_SUFFIX,
                    ): file
                    for file in to_handle_files
                }

                # 处理结果
                for future in as_completed(future_to_file):
                    processed_count += 1
                    file = future_to_file[future]
                    try:
                        success, file_path, result_info, is_handled = future.result()
                        if is_handled:
                            if success:
                                handled[remote_folder].add((file_path, result_info))
                                logger.info(
                                    f"[{processed_count}/{len(to_handle_files)}] 成功处理: {file_path}"
                                )
                            else:
                                not_handled[remote_folder].add((file_path, result_info))
                                logger.warning(
                                    f"[{processed_count}/{len(to_handle_files)}] 处理失败: {file_path} - {result_info}"
                                )
                        else:
                            not_handled[remote_folder].add((file_path, result_info))
                            logger.warning(
                                f"[{processed_count}/{len(to_handle_files)}] 跳过处理: {file_path} - {result_info}"
                            )
                    except Exception as exc:
                        logger.error(
                            f"[{processed_count}/{len(to_handle_files)}] 文件 {file} 处理异常: {exc}"
                        )
                        not_handled[remote_folder].add((str(file), f"处理异常: {exc}"))

        # 删除多余的 strm 文件
        for file in to_delete_strm_files:
            if not dry_run:
                rslt = subprocess.run(["rm", "-f", file], capture_output=True)
                if not rslt.returncode:
                    last_handled.pop(file)
                    deleted_strm_files += 1
            else:
                deleted_strm_files += 1
        for file, strm_file in last_handled.items():
            handled[remote_folder].add((file, strm_file))

        if not dry_run:
            # 保存处理结果
            with open(
                Path(__file__).parent / handled_persisted_file,
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
            f"{remote_folder} 处理完成，共处理 {len(handled[remote_folder])} 个文件（增量处理 {len(handled[remote_folder]) - len(last_handled.keys())}），未处理 {len(not_handled[remote_folder])} 个文件，删除 {deleted_strm_files} 个文件，共计耗时 {round(time.time() - start_time)}s"
        )


if __name__ == "__main__":
    args = parse()
    auto_strm(
        remote_folders=args.folder,
        strm_base_path=args.dest,
        max_workers=args.workers,
        read_from_file=args.read_from_file,
        continue_if_file_not_exist=args.continue_if_file_not_exist,
        dry_run=args.dry_run,
    )
