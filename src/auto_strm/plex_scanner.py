"""
Plex 扫描模块
负责通过 SSH 从 Plex 服务器获取数据库并进行差集扫描
"""

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Set, Tuple

# 添加项目根目录到 Python 路径
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.auto_strm.file_collector import get_remote_folder_video_files
from src.log import logger
from src.mediaserver import send_scan_request
from src.mediaserver.plex import Plex
from src.ssh_client import SSHClient


class PlexDatabaseManager:
    """Plex 数据库管理器，负责数据库的下载、缓存和查询"""

    def __init__(self):
        self._cached_db_path: Optional[str] = None
        self._cached_server_host: Optional[str] = None
        self._cached_remote_path: Optional[str] = None
        self._cache_timestamp: Optional[float] = None
        self._cache_timeout = 3600  # 缓存1小时后过期

    def _is_cache_valid(self, plex_server_host: str, plex_db_path: str) -> bool:
        """检查缓存是否有效"""
        if not self._cached_db_path or not os.path.exists(self._cached_db_path):
            return False

        if (
            self._cached_server_host != plex_server_host
            or self._cached_remote_path != plex_db_path
        ):
            return False

        if (
            self._cache_timestamp is None
            or time.time() - self._cache_timestamp > self._cache_timeout
        ):
            return False

        return True

    def _cleanup_old_cache(self):
        """清理旧的缓存文件"""
        if self._cached_db_path and os.path.exists(self._cached_db_path):
            try:
                os.unlink(self._cached_db_path)
                logger.debug(f"已清理旧的缓存文件: {self._cached_db_path}")
            except Exception as e:
                logger.warning(f"清理旧缓存文件失败: {e}")

        self._cached_db_path = None
        self._cached_server_host = None
        self._cached_remote_path = None
        self._cache_timestamp = None

    def get_database_path(
        self, plex_server_host: str, plex_db_path: str
    ) -> Optional[str]:
        """获取数据库路径，如果缓存有效则返回缓存，否则重新下载"""

        # 检查缓存是否有效
        if self._is_cache_valid(plex_server_host, plex_db_path):
            logger.info(f"使用缓存的 Plex 数据库: {self._cached_db_path}")
            return self._cached_db_path

        # 清理旧缓存
        self._cleanup_old_cache()

        # 重新下载数据库
        try:
            with SSHClient(hostname=plex_server_host) as ssh:
                logger.info(f"连接到 Plex 服务器: {plex_server_host}")

                # 检查 Plex 数据库文件是否存在
                success, stdout, stderr = ssh.execute_command(
                    f"test -f '{plex_db_path}'"
                )
                if not success:
                    logger.error(f"Plex 数据库文件不存在: {plex_db_path}")
                    return None

                # 下载 Plex 数据库到临时文件
                sftp = ssh.get_sftp()
                if not sftp:
                    logger.error("无法建立 SFTP 连接")
                    return None

                # 创建临时文件，但不立即删除
                temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
                temp_db_path = temp_db.name
                temp_db.close()

                logger.info(f"开始下载 Plex 数据库: {plex_db_path}")
                sftp.get(plex_db_path, temp_db_path)
                logger.info(f"数据库已下载并缓存到: {temp_db_path}")

                # 更新缓存信息
                self._cached_db_path = temp_db_path
                self._cached_server_host = plex_server_host
                self._cached_remote_path = plex_db_path
                self._cache_timestamp = time.time()

                return temp_db_path

        except Exception as e:
            logger.error(f"下载 Plex 数据库失败: {e}")
            return None

    def cleanup(self):
        """清理所有缓存"""
        self._cleanup_old_cache()


# 全局数据库管理器实例
_db_manager = PlexDatabaseManager()


def get_plex_file_list_from_server(
    plex_server_host: str,
    media_folder: str,
    plex_db_path: str = "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db",
) -> Tuple[bool, Set[str]]:
    """
    通过 SSH 从 Plex 服务器获取数据库并本地查询获取指定库的文件路径集合

    Args:
        plex_server_host: Plex 服务器主机地址
        media_folder: 远程文件夹路径，用于获取对应的 section_id
        plex_db_path: Plex 数据库在服务器上的路径

    Returns:
        (success, files) 元组，success 表示是否成功，files 为文件路径集合或错误信息
    """
    # 通过文件夹路径获取 section_id
    plex_client = Plex()
    section = plex_client.get_section_by_location(media_folder)
    if not section:
        logger.error(f"无法找到路径 {media_folder} 对应的 Plex section")
        return False, "无法找到对应的 Plex section"

    section_id = section.key

    # 使用数据库管理器获取数据库路径（可能是缓存的）
    local_db_path = _db_manager.get_database_path(plex_server_host, plex_db_path)
    if not local_db_path:
        return False, "无法获取 Plex 数据库"

    # 连接到本地数据库并查询文件路径
    try:
        conn = sqlite3.connect(local_db_path)
        cursor = conn.cursor()

        # 查询指定 section_id 的所有媒体文件路径
        # 从 media_parts 表获取文件路径，这是 Plex 存储文件路径的主要表
        query = """
        SELECT DISTINCT mp.file
        FROM media_parts mp
        JOIN media_items mi ON mp.media_item_id = mi.id
        JOIN metadata_items md ON mi.metadata_item_id = md.id
        WHERE md.library_section_id = ?
        AND mp.file IS NOT NULL
        AND mp.file != ''
        """

        cursor.execute(query, (section_id,))
        results = cursor.fetchall()

        # 如果上面的查询没有结果，尝试更简单的查询
        if not results:
            # 直接从 media_parts 表查询，不做复杂的 JOIN
            query_simple = """
            SELECT DISTINCT file
            FROM media_parts
            WHERE file IS NOT NULL
            AND file != ''
            AND file LIKE ?
            """
            # 使用媒体文件夹路径作为模糊匹配条件
            cursor.execute(query_simple, (f"{media_folder}%",))
            results = cursor.fetchall()

        # 如果还是没有结果，尝试查询所有文件然后在代码中过滤
        if not results:
            logger.warning("使用复杂查询未找到结果，尝试查询所有媒体文件")
            query_all = """
            SELECT DISTINCT file
            FROM media_parts
            WHERE file IS NOT NULL
            AND file != ''
            """
            cursor.execute(query_all)
            all_results = cursor.fetchall()

            # 在代码中过滤出属于指定媒体文件夹的文件
            results = []
            for row in all_results:
                if row[0] and row[0].startswith(media_folder):
                    results.append(row)

        files = set()
        for row in results:
            if row[0]:  # 确保文件路径不为空
                files.add(row[0])

        conn.close()

        logger.info(
            f"从 Plex 数据库获取到 {len(files)} 个 Plex 文件 (section_id: {section_id})"
        )

        if len(files) == 0:
            logger.warning(f"从数据库中没有找到 section_id {section_id} 的任何文件路径")
            logger.warning("这可能是因为该库为空，或者媒体文件夹路径不匹配")
            return False, "未找到任何文件"

        return True, files

    except sqlite3.Error as e:
        logger.error(f"查询 Plex 数据库失败: {e}")
        return False, f"查询数据库失败: {e}"


def get_plex_missing_files(
    remote_folder: str,
    plex_server_host: str,
    plex_db_path: str,
    remote_files: Set[str] = None,
    read_from_file: bool = False,
    continue_if_file_not_exist: bool = False,
) -> Set[str]:
    """
    获取 Plex 中缺失的文件集合

    Args:
        remote_folder: 远程文件夹路径
        plex_server_host: Plex 服务器主机地址
        plex_db_path: Plex 数据库路径
        remote_files: 已收集的远程文件列表（可选）
        read_from_file: 是否从缓存文件读取（当 remote_files 为 None 时使用）
        continue_if_file_not_exist: 缓存文件不存在时是否继续处理（当 remote_files 为 None 时使用）

    Returns:
        Plex 中缺失的文件路径集合
    """
    # 如果没有提供 remote_files，则重新获取（向后兼容）
    if remote_files is None:
        remote_files = set(
            get_remote_folder_video_files(
                remote_folder, read_from_file, continue_if_file_not_exist
            )
        )
    else:
        remote_files = set(remote_files)

    # 获取 Plex 文件列表
    if ":" in remote_folder:
        remote_folder = remote_folder.split(":")
        media_folder = Path(remote_folder[2]) / remote_folder[1]
    else:
        media_folder = remote_folder

    success, plex_files = get_plex_file_list_from_server(
        plex_server_host, str(media_folder), plex_db_path
    )

    if not success:
        logger.error(plex_files)
        return set()

    # 计算差集
    missing_files = remote_files - plex_files

    logger.info(f"远程文件夹共有 {len(remote_files)} 个文件")
    logger.info(f"Plex 库中已有 {len(plex_files)} 个文件")
    logger.info(f"Plex 缺失 {len(missing_files)} 个文件")

    return missing_files


def plex_scan_diff_and_update(
    remote_folder: str,
    plex_server_host: str,
    plex_db_path: str,
    remote_files: Set[str] = None,
    read_from_file: bool = False,
    continue_if_file_not_exist: bool = False,
):
    """
    获取 remote_folder 文件列表，与 Plex (通过 SSH 从服务器获取数据库) 文件列表做差集，
    向 Plex 发起 send_scan_request 请求

    Args:
        remote_folder: 远程文件夹路径
        plex_server_host: Plex 服务器主机地址
        plex_db_path: Plex 数据库路径
        remote_files: 已收集的远程文件列表（可选）
        read_from_file: 是否从缓存文件读取（当 remote_files 为 None 时使用）
        continue_if_file_not_exist: 缓存文件不存在时是否继续处理（当 remote_files 为 None 时使用）
    """
    logger.info(f"开始对 {remote_folder} 进行 Plex 差集扫描")

    # 获取缺失文件
    missing_files = get_plex_missing_files(
        remote_folder,
        plex_server_host,
        plex_db_path,
        remote_files,
        read_from_file,
        continue_if_file_not_exist,
    )

    if missing_files:
        logger.info(f"发现 {len(missing_files)} 个缺失文件，将触发 Plex 扫描")
        # 从文件路径中提取父目录进行扫描
        scan_folders = {str(Path(file_path).parent) for file_path in missing_files}
        send_scan_request(scan_folders=scan_folders, plex=True, emby=False)
        logger.info(f"已向 Plex 发起扫描请求，扫描 {len(scan_folders)} 个文件夹")
    else:
        logger.info("Plex 无需更新，无缺失文件")


def batch_plex_scan_diff_and_update(
    remote_folders: list[str],
    plex_server_host: str,
    plex_db_path: str,
    folder_collections: dict = None,
    read_from_file: bool = False,
    continue_if_file_not_exist: bool = False,
):
    """
    批量对多个远程文件夹进行 Plex 差集扫描

    Args:
        remote_folders: 远程文件夹路径列表
        plex_server_host: Plex 服务器主机地址
        plex_db_path: Plex 数据库路径
        folder_collections: 已收集的文件夹信息字典（可选）
        read_from_file: 是否从缓存文件读取（当 folder_collections 为 None 时使用）
        continue_if_file_not_exist: 缓存文件不存在时是否继续处理（当 folder_collections 为 None 时使用）
    """
    logger.info(f"开始批量 Plex 差集扫描，共 {len(remote_folders)} 个文件夹")

    all_missing_files = set()

    try:
        for remote_folder in remote_folders:
            try:
                # 如果提供了 folder_collections，使用已收集的文件列表
                remote_files = None
                if folder_collections and remote_folder in folder_collections:
                    video_files, _, _ = folder_collections[remote_folder]
                    remote_files = set(video_files)
                    logger.info(
                        f"使用已收集的文件列表，{remote_folder} 共 {len(video_files)} 个文件"
                    )

                missing_files = get_plex_missing_files(
                    remote_folder,
                    plex_server_host,
                    plex_db_path,
                    remote_files,
                    read_from_file,
                    continue_if_file_not_exist,
                )
                all_missing_files.update(missing_files)
            except Exception as e:
                logger.error(f"处理文件夹 {remote_folder} 时出现异常: {e}")

        if all_missing_files:
            logger.info(
                f"所有文件夹共发现 {len(all_missing_files)} 个缺失文件，将触发 Plex 扫描"
            )
            # 从文件路径中提取父目录进行扫描
            scan_folders = [
                str(Path(file_path).parent) for file_path in all_missing_files
            ]
            send_scan_request(
                scan_folders=scan_folders,
                plex=True,
                emby=False,
                interval=3,
                random_interval=True,
            )
            logger.info(
                f"已向 Plex 发起批量扫描请求，扫描 {len(scan_folders)} 个文件夹"
            )
        else:
            logger.info("所有文件夹均无缺失文件，Plex 无需更新")

    finally:
        # 批量处理完成后清理数据库缓存
        logger.info("批量扫描完成，清理数据库缓存")
        cleanup_database_cache()


def cleanup_database_cache():
    """清理数据库缓存"""
    _db_manager.cleanup()
    logger.debug("Plex 数据库缓存已清理")
