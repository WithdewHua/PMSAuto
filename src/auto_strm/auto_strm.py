import argparse
import os
import pickle
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Union
from urllib.parse import unquote

sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.fs_operation import check_and_handle_long_filename
from src.log import logger
from src.mediaserver import send_scan_request
from src.settings import (
    DATA_DIR,
    EMBY_AUTO_SCAN,
    PLEX_AUTO_SCAN,
    PLEX_DB_PATH,
    PLEX_SERVER_HOST,
    STRM_FILE_PATH,
    STRM_MEDIA_SOURCE,
)

# 导入模块化的组件
try:
    # 作为模块导入时使用相对导入
    from .file_collector import collect_files_from_remote_folder
    from .file_processor import process_single_file
    from .plex_scanner import batch_plex_scan_diff_and_update
except ImportError:
    # 作为脚本直接运行时使用绝对导入
    from file_collector import collect_files_from_remote_folder
    from file_processor import process_single_file
    from plex_scanner import batch_plex_scan_diff_and_update


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
        help="扫描远程文件夹的最大线程数",
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
    # 添加 Plex 扫描相关参数
    parser.add_argument(
        "--plex-scan",
        action="store_true",
        help="启用 Plex 差集扫描功能",
    )
    parser.add_argument(
        "--plex-server-host",
        help="Plex 服务器主机地址（SSH 连接用）",
    )
    parser.add_argument(
        "--plex-db-path",
        help="Plex 数据库路径",
    )
    return parser.parse_args()


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
    # Plex 扫描相关参数
    enable_plex_scan: bool = False,
    plex_server_host: str = PLEX_SERVER_HOST,
    plex_db_path: str = PLEX_DB_PATH,
):
    """
    自动为远程文件夹中的媒体文件创建 .strm 文件

    Args:
        remote_folders: 远程文件夹列表
        strm_base_path: .strm 文件存放目录
        replace_prefix: 是否替换路径前缀
        prefix: 替换的前缀字符串
        category_index: 分类索引位置
        max_workers: 文件处理的最大线程数
        read_from_file: 是否从缓存文件读取文件列表
        continue_if_file_not_exist: 缓存文件不存在时是否继续处理
        increment: 是否增量处理，默认 True
        repair: 尝试修复错误，默认 True
        dry_run: 是否为试运行模式
        scan_threads: 扫描远程文件夹的最大线程数
        interactive: 是否交互式运行，默认 False
        enable_plex_scan: 是否启用 Plex 差集扫描功能
        plex_server_host: Plex 服务器主机地址（SSH 连接用）
        plex_db_path: Plex 数据库路径
    """
    from src.settings import SUBTITLE_SUFFIX, VIDEO_SUFFIX

    if isinstance(strm_base_path, str):
        strm_base_path = Path(strm_base_path)

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

    folder_collections = {}  # {remote_folder: (video_files, subtitle_files, last_handled, to_delete_files)}

    if len(remote_folders) == 1:
        logger.info("顺序收集远程文件夹信息")
        for remote_folder in remote_folders:
            (
                remote_folder,
                video_files,
                subtitle_files,
                last_handled,
                to_delete_files,
            ) = collect_files_from_remote_folder(
                remote_folder, read_from_file, continue_if_file_not_exist, increment
            )
            if video_files or subtitle_files or to_delete_files:
                folder_collections[remote_folder] = (
                    video_files,
                    subtitle_files,
                    last_handled,
                    to_delete_files,
                )
    else:
        logger.info(
            f"使用 {scan_threads if scan_threads is not None else min(os.cpu_count(), len(remote_folders))} 个线程并行收集远程文件夹信息"
        )
        with ThreadPoolExecutor(
            max_workers=min(os.cpu_count(), len(remote_folders))
        ) as executor:
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
                    (
                        remote_folder,
                        video_files,
                        subtitle_files,
                        last_handled,
                        to_delete_files,
                    ) = future.result()
                    if video_files or subtitle_files or to_delete_files:
                        folder_collections[remote_folder] = (
                            video_files,
                            subtitle_files,
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

    # 统计总文件数并准备所有需要处理的文件和相关信息
    total_video_files, total_subtitle_files = 0, 0
    total_to_handle = 0
    total_to_delete = 0
    files_to_process = []  # [(file, remote_folder)]
    all_last_handled = {}  # {file_path: (strm_file_path, remote_folder)}
    all_to_delete = {}  # {file_path: (strm_file_path, remote_folder)}

    for remote_folder, (
        video_files,
        subtitle_files,
        last_handled,
        to_delete_files,
    ) in folder_collections.items():
        # 统计文件数
        total_video_files += len(video_files)
        total_subtitle_files += len(subtitle_files)
        to_handle = set(video_files + subtitle_files) - set(last_handled.keys())
        total_to_handle += len(to_handle)
        total_to_delete += len(to_delete_files)

        # 准备需要处理的文件
        for file in to_handle:
            files_to_process.append((file, remote_folder))

        # 准备已处理的文件信息
        for file_path, strm_file_path in last_handled.items():
            all_last_handled[file_path] = (strm_file_path, remote_folder)

        # 准备需要删除的文件信息
        for file_path, strm_file_path in to_delete_files.items():
            all_to_delete[file_path] = (strm_file_path, remote_folder)

    logger.info("=" * 50)
    logger.info(
        f"收集完成！共 {len(folder_collections)} 个文件夹，{total_video_files} 个视频文件，{total_subtitle_files} 个字幕文件"
    )
    logger.info(
        f"需要处理 {total_to_handle} 个文件，删除 {total_to_delete} 个多余的文件"
    )
    logger.info("=" * 50)

    # 第二阶段：统一处理所有文件
    logger.info("第二阶段：处理文件")
    logger.info("=" * 50)

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
                    remote_folder,
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

    # 删除多余的 strm 文件和字幕文件
    deleted_count = 0
    if all_to_delete:
        logger.info(f"开始删除 {len(all_to_delete)} 个多余的文件")
        for file_path, (strm_file_path, remote_folder) in all_to_delete.items():
            if not dry_run:
                rslt = subprocess.run(
                    ["rm", "-f", strm_file_path], capture_output=True, encoding="utf-8"
                )
                if not rslt.returncode:
                    deleted_count += 1
                    logger.info(f"删除文件成功: {strm_file_path}")
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

    # 第三阶段：Plex 差集扫描（可选）
    if enable_plex_scan and plex_server_host and plex_db_path:
        if interactive:
            ans = input("是否进行 Plex 差集扫描？(y/n): ")
            if ans.strip().lower() not in ("y", "yes"):
                logger.info("跳过 Plex 差集扫描")
                return

        logger.info("=" * 50)
        logger.info("第三阶段：Plex 差集扫描")
        logger.info("=" * 50)

        batch_plex_scan_diff_and_update(
            remote_folders=remote_folders,
            plex_server_host=plex_server_host,
            plex_db_path=plex_db_path,
            folder_collections=folder_collections,
            read_from_file=read_from_file,
            continue_if_file_not_exist=continue_if_file_not_exist,
        )
        logger.info("Plex 差集扫描完成")
    elif enable_plex_scan:
        logger.warning("启用了 Plex 扫描但参数不完整，跳过扫描")
        logger.warning("需要提供：--plex-server-host, --plex-db-path")


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
        # 扫库
        if to_repair_long_filename:
            time.sleep(60)  # 等待 rclone 刷新
            send_scan_request(
                scan_folders=to_repair_long_filename,
                plex=PLEX_AUTO_SCAN,
                emby=EMBY_AUTO_SCAN,
            )


if __name__ == "__main__":
    if not Path(DATA_DIR).exists():
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    args = parse()
    folders = args.folder
    if not folders:
        folders = [
            "GD-TVShows2:TVShows:/Media2",
            "GD-TVShows2:VarietyShows:/Media2",
            "GD-TVShows2:Documentary:/Media2",
            "GD-Anime:Anime:/Media",
            "GD-Movies-2:Movies:/Media",
            "GD-Movies-2:NC17-Movies:/Media",
            "GD-Movies-2:Concerts:/Media",
            "GD-NSFW-2:NSFW:/Media",
        ]

    auto_strm(
        remote_folders=folders,
        strm_base_path=args.dest,
        max_workers=args.workers,
        scan_threads=args.scan_threads,
        read_from_file=args.read_from_file,
        continue_if_file_not_exist=args.continue_if_file_not_exist,
        increment=not args.not_increment,
        dry_run=args.dry_run,
        interactive=args.interactive,
        # Plex 扫描相关参数
        enable_plex_scan=args.plex_scan,
        plex_server_host=args.plex_server_host or PLEX_SERVER_HOST,
        plex_db_path=args.plex_db_path or PLEX_DB_PATH,
    )
