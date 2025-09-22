import argparse
import json
import os
import pickle
import re
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Union
from urllib.parse import unquote

sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.fs_operation import check_and_handle_long_filename, set_ownership
from src.log import logger
from src.mediaserver import send_scan_request
from src.settings import (
    DATA_DIR,
    EMBY_AUTO_SCAN,
    GID,
    PLEX_AUTO_SCAN,
    STRM_FILE_PATH,
    STRM_MEDIA_SOURCE,
    UID,
)
from src.strm import create_strm_file
from src.tmdb import TMDB, is_filename_length_gt_255


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
        help=f"文件处理的最大线程数，默认为 {os.cpu_count()}",
    )
    parser.add_argument(
        "-t",
        "--scan-threads",
        type=int,
        default=None,
        help="扫描远程文件夹的最大线程数（最大为4），默认为顺序扫描",
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
    parser.add_argument(
        "--not-increment",
        action="store_true",
        default=False,
        help="是否增量处理，默认增量",
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry Run 模式")

    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        default=False,
        help="是否交互式运行，默认不交互。若开启则在关键阶段询问是否继续。",
    )
    return parser.parse_args()


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
            if replace_prefix:
                file_name = re.sub(r"^/.*?/", prefix, str(file))
            else:
                file_name = str(file)
            target_strm_file = Path(strm_base_path) / (
                str(file).removeprefix(prefix).rsplit(".", 1)[0] + ".strm"
            )
            if not target_strm_file.exists():
                if create_strm_file(Path(file_name), strm_file_path=target_strm_file):
                    set_ownership(
                        target_strm_file, UID, GID, start_prefix=str(strm_base_path)
                    )
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
                            set_ownership(
                                target_file, UID, GID, start_prefix=str(strm_base_path)
                            )
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
                year_prefix = "Aired_" if not is_movie else "Released_"
                tmdb_name = (
                    file.parent.parent.name if not is_movie else file.parent.name
                )
                if "tmdb-" not in tmdb_name:
                    logger.warning(f"跳过处理文件 {file}: 无 TMDB 名字")
                    return False, str(file), "无 TMDB 名字", False

                # 旧格式
                target_strm_folder = (
                    strm_base_path / category / f"{year_prefix}{year}" / tmdb_name
                )
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
                        logger.warning(f"跳过处理文件 {file}: 无季度信息")
                        return False, str(file), "无季度信息", False
                    target_strm_folder = target_strm_folder / file.parent.name

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
                    if create_strm_file(
                        Path(file_name), strm_file_path=target_strm_file
                    ):
                        set_ownership(
                            target_strm_file,
                            uid=UID,
                            gid=GID,
                            start_prefix=str(strm_base_path),
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
                                        target_file,
                                        uid=UID,
                                        gid=GID,
                                        start_prefix=str(strm_base_path),
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


def collect_files_from_remote_folder(
    remote_folder: str,
    read_from_file: bool,
    continue_if_file_not_exist: bool,
    increment: bool,
) -> tuple[str, list[str], dict[str, str], dict[str, str]]:
    """
    从单个远程文件夹收集文件信息

    Returns:
        tuple: (remote_folder, video_files, last_handled, to_delete_files)
    """
    from settings import VIDEO_SUFFIX

    logger.info(f"开始收集远程文件夹文件：{remote_folder}")
    handled_persisted_file = f"{remote_folder.strip('/').replace('/', '_')}_handled.pkl"
    last_handled = {}
    if increment and Path(DATA_DIR, handled_persisted_file).exists():
        with open(Path(DATA_DIR, handled_persisted_file), "rb") as f:
            _handled = pickle.load(f)
            for file_path, strm_file_path in _handled:
                last_handled[file_path] = strm_file_path

    start_time = time.time()
    # 收集所有符合条件的文件
    video_files = []
    if ":" in remote_folder:
        remote, remote_path, mount_point = remote_folder.split(":", 2)
        if read_from_file:
            json_file = Path(DATA_DIR) / f"{remote}_{remote_path}.json"
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
            return remote_folder, [], {}, {}

        logger.info(f"开始遍历文件夹：{remote_folder}")

        for file in remote_folder_path.rglob("*"):
            if file.is_file() and file.suffix.lstrip(".").lower() in VIDEO_SUFFIX:
                video_files.append(file)

    video_files = [str(p) for p in video_files]

    # 计算需要删除的多余 strm 文件
    to_delete_files = {}
    for file_path in set(last_handled.keys()) - set(video_files):
        to_delete_files[file_path] = last_handled[file_path]

    logger.info(
        f"{remote_folder} 找到 {len(video_files)} 个视频文件，需要删除 {len(to_delete_files)} 个多余的 strm 文件，耗时 {round(time.time() - start_time, 2)}s"
    )

    return remote_folder, video_files, last_handled, to_delete_files


def auto_strm(
    remote_folders: list[str],
    strm_base_path: Union[str, Path] = Path(STRM_FILE_PATH),
    replace_prefix: bool = True,
    prefix: str = "/Media/",
    category_index: int = 2,
    max_workers: int = 4,
    read_from_file: bool = False,
    continue_if_file_not_exist: bool = False,
    increment=True,
    repair=True,
    dry_run: bool = False,
    scan_threads: int = None,
    interactive: bool = False,
):
    """
    自动为远程文件夹中的媒体文件创建 .strm 文件

    Args:
        remote_folders: 远程文件夹列表
        strm_base_path: .strm 文件存放目录
        max_workers: 文件处理的最大线程数
        scan_threads: 扫描远程文件夹的最大线程数（限制最大为4），如果为 None，则顺序扫描
        increment: 是否增量处理，默认 True
        repair: 尝试修复错误，默认 True
        interactive: 是否交互式运行，默认 False
    """
    from settings import SUBTITLE_SUFFIX, VIDEO_SUFFIX

    if isinstance(strm_base_path, str):
        strm_base_path = Path(strm_base_path)

    # 限制 scan_threads 最大为 4
    if scan_threads is not None and scan_threads > 4:
        logger.warning(f"scan_threads 限制最大为 4，当前设置 {scan_threads} 已调整为 4")
        scan_threads = 4

    all_handled = defaultdict(set)
    all_not_handled = defaultdict(set)

    # 第一阶段开始前交互
    if interactive:
        ans = input("即将开始第一阶段：收集文件信息。是否继续？(y/n): ")
        if ans.strip().lower() not in ("y", "yes"):
            print("用户取消操作。")
            return

    # 第一阶段：收集所有远程文件夹的文件信息
    logger.info("=" * 50)
    logger.info("第一阶段：收集文件信息")
    logger.info("=" * 50)

    folder_collections = {}  # {remote_folder: (video_files, last_handled, to_delete_files)}

    if scan_threads is None or len(remote_folders) == 1:
        logger.info("顺序收集远程文件夹信息")
        for remote_folder in remote_folders:
            remote_folder, video_files, last_handled, to_delete_files = (
                collect_files_from_remote_folder(
                    remote_folder, read_from_file, continue_if_file_not_exist, increment
                )
            )
            if video_files or to_delete_files:
                folder_collections[remote_folder] = (
                    video_files,
                    last_handled,
                    to_delete_files,
                )
    else:
        logger.info(f"使用 {scan_threads} 个线程并行收集远程文件夹信息")
        with ThreadPoolExecutor(max_workers=scan_threads) as executor:
            # 提交所有收集任务
            future_to_folder = {
                executor.submit(
                    collect_files_from_remote_folder,
                    remote_folder,
                    read_from_file,
                    continue_if_file_not_exist,
                    increment,
                ): remote_folder
                for remote_folder in remote_folders
            }

            # 处理结果
            for future in as_completed(future_to_folder):
                original_folder = future_to_folder[future]
                try:
                    remote_folder, video_files, last_handled, to_delete_files = (
                        future.result()
                    )
                    if video_files or to_delete_files:
                        folder_collections[remote_folder] = (
                            video_files,
                            last_handled,
                            to_delete_files,
                        )
                    logger.info(f"文件夹 {remote_folder} 信息收集完成")
                except Exception as exc:
                    logger.error(f"收集文件夹 {original_folder} 信息异常: {exc}")

    # 第一阶段结束后交互
    if interactive:
        ans = input("第一阶段已结束，是否继续进入第二阶段？(y/n): ")
        if ans.strip().lower() not in ("y", "yes"):
            print("用户取消操作。")
            return

    # 统计总文件数
    total_files = 0
    total_to_handle = 0
    total_to_delete = 0

    for remote_folder, (
        video_files,
        last_handled,
        to_delete_files,
    ) in folder_collections.items():
        total_files += len(video_files)
        to_handle = set(video_files) - set(last_handled.keys())
        total_to_handle += len(to_handle)
        total_to_delete += len(to_delete_files)

    logger.info("=" * 50)
    logger.info(
        f"收集完成！共 {len(folder_collections)} 个文件夹，{total_files} 个视频文件"
    )
    logger.info(
        f"需要处理 {total_to_handle} 个文件，删除 {total_to_delete} 个多余的 strm 文件"
    )
    logger.info("=" * 50)

    if total_to_handle == 0 and total_to_delete == 0:
        logger.info("没有文件需要处理，退出")
        return

    # 第二阶段：统一处理所有文件
    logger.info("第二阶段：处理文件")
    logger.info("=" * 50)

    # 准备所有需要处理的文件和相关信息
    files_to_process = []  # [(file, remote_folder)]
    all_last_handled = {}  # {file_path: (strm_file_path, remote_folder)}
    all_to_delete = {}  # {file_path: (strm_file_path, remote_folder)}

    for remote_folder, (
        video_files,
        last_handled,
        to_delete_files,
    ) in folder_collections.items():
        to_handle = set(video_files) - set(last_handled.keys())
        for file in to_handle:
            files_to_process.append((file, remote_folder))

        for file_path, strm_file_path in last_handled.items():
            all_last_handled[file_path] = (strm_file_path, remote_folder)

        for file_path, strm_file_path in to_delete_files.items():
            all_to_delete[file_path] = (strm_file_path, remote_folder)

    # 处理文件
    processed_count = 0

    if not dry_run and files_to_process:
        logger.info(f"开始使用 {max_workers} 个线程处理 {len(files_to_process)} 个文件")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有文件处理任务
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
                ): (file, remote_folder)
                for file, remote_folder in files_to_process
            }

            # 处理结果
            for future in as_completed(future_to_file):
                processed_count += 1
                file, remote_folder = future_to_file[future]
                try:
                    success, file_path, result_info, is_handled = future.result()
                    if is_handled:
                        if success:
                            all_handled[remote_folder].add((file_path, result_info))
                            logger.info(
                                f"[{processed_count}/{len(files_to_process)}] 成功处理: {file_path}"
                            )
                        else:
                            all_not_handled[remote_folder].add((file_path, result_info))
                            logger.warning(
                                f"[{processed_count}/{len(files_to_process)}] 处理失败: {file_path} - {result_info}"
                            )
                    else:
                        all_not_handled[remote_folder].add((file_path, result_info))
                        logger.warning(
                            f"[{processed_count}/{len(files_to_process)}] 跳过处理: {file_path} - {result_info}"
                        )
                except Exception as exc:
                    logger.error(
                        f"[{processed_count}/{len(files_to_process)}] 文件 {file} 处理异常: {exc}"
                    )
                    all_not_handled[remote_folder].add((str(file), f"处理异常: {exc}"))

    # 删除多余的 strm 文件
    deleted_count = 0
    if all_to_delete:
        logger.info(f"开始删除 {len(all_to_delete)} 个多余的 strm 文件")
        for file_path, (strm_file_path, remote_folder) in all_to_delete.items():
            if not dry_run:
                rslt = subprocess.run(["rm", "-f", strm_file_path], capture_output=True)
                if not rslt.returncode:
                    deleted_count += 1
                    logger.info(f"删除多余的 strm 文件: {strm_file_path}")
                else:
                    logger.error(f"删除文件失败: {strm_file_path}")
            else:
                deleted_count += 1

    # 添加已存在的文件到处理结果中
    for file_path, (strm_file_path, remote_folder) in all_last_handled.items():
        # 只有在当前仍存在的文件才添加（排除已删除的）
        if file_path not in all_to_delete:
            all_handled[remote_folder].add((file_path, strm_file_path))

    # 保存处理结果
    if not dry_run:
        for remote_folder in folder_collections.keys():
            handled_persisted_file = (
                f"{remote_folder.strip('/').replace('/', '_')}_handled.pkl"
            )
            with open(Path(DATA_DIR) / handled_persisted_file, "wb") as f:
                pickle.dump(all_handled[remote_folder], f)

            not_handled_persisted_file = (
                f"{remote_folder.strip('/').replace('/', '_')}_not_handled.pkl"
            )
            with open(Path(DATA_DIR) / not_handled_persisted_file, "wb") as f:
                pickle.dump(all_not_handled[remote_folder], f)

    # 统计结果
    total_handled = sum(len(files) for files in all_handled.values())
    total_not_handled = sum(len(files) for files in all_not_handled.values())

    logger.info("=" * 50)
    logger.info("处理完成！")
    logger.info(f"成功处理: {total_handled} 个文件")
    logger.info(f"处理失败: {total_not_handled} 个文件")
    logger.info(f"删除多余: {deleted_count} 个文件")
    logger.info("=" * 50)

    # 按文件夹显示详细统计
    for remote_folder in folder_collections.keys():
        handled_count = len(all_handled[remote_folder])
        not_handled_count = len(all_not_handled[remote_folder])
        logger.info(f"{remote_folder}: 成功 {handled_count}, 失败 {not_handled_count}")

    # 第二阶段结束后交互
    if interactive:
        ans = input("第二阶段已结束，是否继续？(y/n): ")
        if ans.strip().lower() not in ("y", "yes"):
            print("用户取消操作。")
            return

    print_not_handled_summary(repair=repair)


def generate_strm_cache(
    strm_folder: str, remote_folder: str, strm_media_source: str = STRM_MEDIA_SOURCE
):
    """生成已处理的 strm 文件缓存"""
    strm_folder_path = Path(strm_folder)
    if not strm_folder_path.exists() or not strm_folder_path.is_dir():
        logger.error(f"指定的 strm 文件夹 {strm_folder} 不存在或不是目录")
        return

    handled = set()
    for file in strm_folder_path.rglob("*.strm"):
        if file.is_file():
            content = file.read_text(encoding="utf-8")
            content = unquote(content.strip())
            media_path = content.removeprefix(strm_media_source)
            if not media_path.startswith("/"):
                media_path = f"/{media_path}"

            handled.add((media_path, str(file)))

    handled_persisted_file = f"{remote_folder.strip('/').replace('/', '_')}_handled.pkl"
    with open(Path(DATA_DIR) / handled_persisted_file, "wb") as f:
        pickle.dump(handled, f)
    logger.info(
        f"已生成 strm 文件缓存，共 {len(handled)} 个文件，保存到 {handled_persisted_file}"
    )


def print_not_handled_summary(repair=True):
    """打印未处理文件的汇总"""
    not_handled_files = defaultdict(list)
    for pkl_file in Path(DATA_DIR).glob("*_not_handled.pkl"):
        remote_folder = pkl_file.stem.removeprefix("").removesuffix("_not_handled")
        with open(pkl_file, "rb") as f:
            not_handled = pickle.load(f)
            not_handled_files[remote_folder].extend(not_handled)

    to_repair_long_filename = set()
    for remote_folder, files in not_handled_files.items():
        if len(files) == 0:
            continue
        logger.info(
            f"远程文件夹 {remote_folder} 未处理文件汇总，共 {len(files)} 个文件："
        )
        for file_path, reason in files:
            logger.info(f"- {file_path}: {reason}")
            if "文件名过长" in reason:
                to_repair_long_filename.add(str(Path(file_path).parent))

    if repair:
        for folder in to_repair_long_filename:
            # 考虑神医插件，最大占用 15 字节
            check_and_handle_long_filename(folder, offset=15)
        time.sleep(60)  # 等待 rclone 刷新
        # 扫库
        if to_repair_long_filename:
            send_scan_request(
                scan_folders=to_repair_long_filename,
                plex=PLEX_AUTO_SCAN,
                emby=EMBY_AUTO_SCAN,
            )


if __name__ == "__main__":
    if not Path(DATA_DIR).exists():
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    args = parse()
    auto_strm(
        remote_folders=args.folder,
        strm_base_path=args.dest,
        max_workers=args.workers,
        scan_threads=args.scan_threads,
        read_from_file=args.read_from_file,
        continue_if_file_not_exist=args.continue_if_file_not_exist,
        increment=not args.not_increment,
        dry_run=args.dry_run,
        interactive=args.interactive,
    )
