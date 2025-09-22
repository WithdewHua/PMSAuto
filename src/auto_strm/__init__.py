"""
Auto STRM 自动化处理模块

包含以下子模块：
- file_collector: 文件收集功能
- file_processor: 文件处理功能
- plex_scanner: Plex 扫描功能
- auto_strm: 主控制模块
"""

from .auto_strm import auto_strm, generate_strm_cache, print_not_handled_summary
from .file_collector import (
    collect_files_from_remote_folder,
    get_remote_folder_video_files,
)
from .file_processor import process_single_file
from .plex_scanner import (
    batch_plex_scan_diff_and_update,
    get_plex_file_list_from_server,
    plex_scan_diff_and_update,
)

__all__ = [
    # 主要功能
    "auto_strm",
    "generate_strm_cache",
    "print_not_handled_summary",
    # 文件收集
    "get_remote_folder_video_files",
    "collect_files_from_remote_folder",
    # 文件处理
    "process_single_file",
    # Plex 扫描
    "get_plex_file_list_from_server",
    "plex_scan_diff_and_update",
    "batch_plex_scan_diff_and_update",
]
