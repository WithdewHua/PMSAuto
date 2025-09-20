import traceback
from pathlib import Path
from urllib.parse import quote

import paramiko
from log import logger
from settings import GID, STRM_FILE_PATH, STRM_MEDIA_SOURCE, STRM_RSYNC_DEST_SERVER, UID


class SSHClient:
    """SSH 客户端，基于 paramiko 实现的远程服务器操作"""

    def __init__(self, hostname: str, username: str = "root", port: int = 22):
        self.hostname = hostname
        self.username = username
        self.port = port
        self.client = None
        self.sftp = None

    def connect(self) -> bool:
        """建立 SSH 连接"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # 尝试使用 SSH 密钥认证
            self.client.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                timeout=10,
                look_for_keys=True,
                allow_agent=True,
            )

            logger.debug(f"SSH 连接成功: {self.username}@{self.hostname}:{self.port}")
            return True

        except Exception as e:
            logger.error(f"SSH 连接失败: {e}")
            self.close()
            return False

    def close(self):
        """关闭 SSH 连接"""
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.client:
            self.client.close()
            self.client = None

    def __enter__(self):
        """上下文管理器入口"""
        if self.connect():
            return self
        else:
            raise ConnectionError(f"无法连接到 {self.hostname}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.close()

    def execute_command(self, command: str) -> tuple[bool, str, str]:
        """
        在远程服务器上执行命令

        Args:
            command: 要执行的命令

        Returns:
            tuple: (success, stdout, stderr)
        """
        if not self.client:
            logger.error("SSH 连接未建立")
            return False, "", "SSH 连接未建立"

        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=30)

            # 读取输出
            stdout_data = stdout.read().decode("utf-8")
            stderr_data = stderr.read().decode("utf-8")
            exit_status = stdout.channel.recv_exit_status()

            success = exit_status == 0
            if not success:
                logger.debug(
                    f"命令执行失败: {command}, 退出码: {exit_status}, 错误: {stderr_data}"
                )

            return success, stdout_data, stderr_data

        except Exception as e:
            logger.error(f"执行命令失败: {command}, 错误: {e}")
            return False, "", str(e)

    def get_sftp(self):
        """获取 SFTP 客户端"""
        if not self.sftp and self.client:
            try:
                self.sftp = self.client.open_sftp()
            except Exception as e:
                logger.error(f"创建 SFTP 连接失败: {e}")
                return None
        return self.sftp

    def create_directory(self, directory: str, set_permissions: bool = True) -> bool:
        """
        在远程服务器上创建目录

        Args:
            directory: 要创建的目录路径
            set_permissions: 是否设置目录权限

        Returns:
            bool: 创建是否成功
        """
        sftp = self.get_sftp()
        if not sftp:
            return False

        try:
            # 检查目录是否已存在
            try:
                sftp.stat(directory)
                logger.debug(f"远程目录已存在: {directory}")
                return True
            except FileNotFoundError:
                pass

            # 递归创建目录
            path_parts = directory.strip("/").split("/")
            current_path = ""
            created_dirs = []  # 记录新创建的目录，用于设置权限

            for part in path_parts:
                if not part:  # 跳过空字符串
                    continue

                current_path = f"{current_path}/{part}" if current_path else f"/{part}"

                try:
                    sftp.stat(current_path)
                except FileNotFoundError:
                    sftp.mkdir(current_path)
                    created_dirs.append(current_path)
                    logger.debug(f"创建远程目录: {current_path}")

            # 设置新创建目录的权限
            if set_permissions and created_dirs:
                for dir_path in created_dirs:
                    if not self.set_ownership(dir_path, UID, GID):
                        logger.warning(f"设置目录权限失败: {dir_path}")

            logger.debug(f"远程目录创建成功: {directory}")
            return True

        except Exception as e:
            logger.error(f"远程目录创建失败: {directory}, 错误: {e}")
            return False

    def write_file(self, file_path: str, content: str) -> bool:
        """
        在远程服务器上写入文件

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            bool: 写入是否成功
        """
        sftp = self.get_sftp()
        if not sftp:
            return False

        try:
            # 确保父目录存在
            parent_dir = str(Path(file_path).parent)
            if not self.create_directory(parent_dir):
                return False

            # 写入文件
            with sftp.open(file_path, "w") as remote_file:
                remote_file.write(content)

            # 设置文件权限
            self.set_ownership(file_path, UID, GID)

            logger.debug(f"远程文件写入成功: {file_path}")
            return True

        except Exception as e:
            logger.error(
                f"远程文件写入失败: {file_path}, 写入内容：{content}, 错误: {e}"
            )
            logger.exception(traceback.format_exc())
            return False

    def set_ownership(self, path: str, user: str, group: str) -> bool:
        """
        在远程服务器上设置文件/目录的所有者

        Args:
            path: 文件或目录路径
            user: 用户
            group: 组

        Returns:
            bool: 设置是否成功
        """
        command = f'chown -R {user}:{group} "{path}"'
        success, stdout, stderr = self.execute_command(command)

        if success:
            logger.debug(f"远程文件权限设置成功: {path}")
        else:
            logger.error(f"远程文件权限设置失败: {path}, 错误: {stderr}")

        return success

    def remote_path_exists(self, path: str) -> bool:
        """
        检查远程服务器上的文件或目录是否存在

        Args:
            path: 要检查的文件或目录路径

        Returns:
            bool: 文件或目录是否存在
        """
        if not self.client:
            logger.error("SSH 连接未建立")
            return False

        try:
            # 使用 test 命令检查路径是否存在
            success, stdout, stderr = self.execute_command(f'test -e "{path}"')

            if success:
                logger.debug(f"远程路径存在: {path}")
            else:
                logger.debug(f"远程路径不存在: {path}")

            return success

        except Exception as e:
            logger.error(f"检查远程路径失败: {path}, 错误: {e}")
            return False

    def move_remote_file(
        self, source_path: str, destination_path: str, create_dest_dir: bool = True
    ) -> bool:
        """
        在远程服务器上移动文件或目录到另一个位置

        Args:
            source_path: 源文件或目录路径
            destination_path: 目标文件或目录路径
            create_dest_dir: 是否自动创建目标目录

        Returns:
            bool: 移动是否成功
        """
        try:
            # 检查源文件是否存在
            success, stdout, stderr = self.execute_command(f'test -e "{source_path}"')
            if not success:
                logger.error(f"源文件/目录不存在: {source_path}")
                return False

            # 如果需要创建目标目录
            if create_dest_dir:
                dest_dir = str(Path(destination_path).parent)
                if not self.create_directory(dest_dir, set_permissions=True):
                    logger.error(f"无法创建目标目录: {dest_dir}")
                    return False

            # 执行移动命令
            command = f'mv "{source_path}" "{destination_path}"'
            success, stdout, stderr = self.execute_command(command)

            if success:
                logger.info(f"远程文件移动成功: {source_path} -> {destination_path}")

                # 设置目标文件/目录的权限
                if not self.set_ownership(destination_path, UID, GID):
                    logger.warning(f"移动成功但设置权限失败: {destination_path}")

                return True
            else:
                logger.error(
                    f"远程文件移动失败: {source_path} -> {destination_path}, 错误: {stderr}"
                )
                return False

        except Exception as e:
            logger.error(
                f"远程文件移动异常: {source_path} -> {destination_path}, 错误: {e}"
            )
            return False


class RemoteStrmManager:
    """远程 STRM 文件管理器，基于 paramiko 实现"""

    def __init__(
        self, hostname: str, username: str = "root", base_path: str = STRM_FILE_PATH
    ):
        self.hostname = hostname
        self.username = username
        self.base_path = base_path

    def create_strm_file(
        self,
        media_file_path: Path,
        strm_dst_file_path: Path,
        media_source: str = STRM_MEDIA_SOURCE,
    ) -> bool:
        """
        在远程服务器上创建 STRM 文件

        Args:
            media_file_path: 媒体文件路径
            strm_dst_file_path: STRM 文件的目标路径
            media_source: 媒体源 URL 前缀

        Returns:
            bool: 创建是否成功
        """
        try:
            with SSHClient(self.hostname, self.username) as ssh_client:
                # 构造 STRM 文件内容
                strm_content = f"{media_source.rstrip('/')}/{quote(str(media_file_path).lstrip('/'))}"

                # 写入 STRM 文件（会自动创建目录并设置权限）
                remote_file_path = str(strm_dst_file_path)
                if not ssh_client.write_file(remote_file_path, strm_content):
                    return False

                # 设置 STRM 文件的权限
                if not ssh_client.set_ownership(remote_file_path, UID, GID):
                    logger.warning(
                        f"设置文件权限失败，但 STRM 文件创建成功: {remote_file_path}"
                    )

                logger.info(f"远程 STRM 文件创建成功: {remote_file_path}")
                return True

        except Exception as e:
            logger.error(f"创建远程 STRM 文件失败: {e}")
            return False

    def delete_strm_file(self, strm_file_path: Path) -> bool:
        """
        删除远程服务器上的 STRM 文件

        Args:
            strm_file_path: 要删除的 STRM 文件路径

        Returns:
            bool: 删除是否成功
        """
        try:
            with SSHClient(self.hostname, self.username) as ssh_client:
                remote_file_path = str(strm_file_path)

                # 检查文件是否存在
                success, stdout, stderr = ssh_client.execute_command(
                    f'test -f "{remote_file_path}"'
                )
                if not success:
                    logger.info(f"远程 STRM 文件不存在: {remote_file_path}")
                    return True  # 文件不存在也算删除成功

                # 删除文件
                success, stdout, stderr = ssh_client.execute_command(
                    f'rm -f "{remote_file_path}"'
                )
                if not success:
                    logger.error(
                        f"删除远程 STRM 文件失败: {remote_file_path}, 错误: {stderr}"
                    )
                    return False

                logger.info(f"远程 STRM 文件删除成功: {remote_file_path}")
                return True

        except Exception as e:
            logger.error(f"删除远程 STRM 文件失败: {e}")
            return False

    def delete_strm_directory(
        self, strm_dir_path: Path, remove_empty_parents: bool = True
    ) -> bool:
        """
        删除远程服务器上的 STRM 目录

        Args:
            strm_dir_path: 要删除的 STRM 目录路径
            remove_empty_parents: 是否删除空的父目录

        Returns:
            bool: 删除是否成功
        """
        try:
            with SSHClient(self.hostname, self.username) as ssh_client:
                remote_dir_path = str(strm_dir_path)

                # 检查目录是否存在
                success, stdout, stderr = ssh_client.execute_command(
                    f'test -d "{remote_dir_path}"'
                )
                if not success:
                    logger.info(f"远程 STRM 目录不存在: {remote_dir_path}")
                    return True  # 目录不存在也算删除成功

                # 删除目录及其内容
                success, stdout, stderr = ssh_client.execute_command(
                    f'rm -rf "{remote_dir_path}"'
                )
                if not success:
                    logger.error(
                        f"删除远程 STRM 目录失败: {remote_dir_path}, 错误: {stderr}"
                    )
                    return False

                logger.info(f"远程 STRM 目录删除成功: {remote_dir_path}")

                # 如果需要，删除空的父目录
                if remove_empty_parents:
                    self._remove_empty_parent_directories(
                        ssh_client, strm_dir_path.parent
                    )

                return True

        except Exception as e:
            logger.error(f"删除远程 STRM 目录失败: {e}")
            return False

    def _remove_empty_parent_directories(
        self, ssh_client: SSHClient, parent_path: Path
    ) -> None:
        """
        递归删除空的父目录

        Args:
            ssh_client: SSH 客户端实例
            parent_path: 父目录路径
        """
        try:
            parent_str = str(parent_path)

            # 不要删除基础路径
            if (
                parent_str == self.base_path
                or parent_str == "/"
                or parent_path == parent_path.parent
            ):
                return

            # 检查目录是否为空
            success, stdout, stderr = ssh_client.execute_command(
                f'find "{parent_str}" -mindepth 1 -maxdepth 1 | head -1'
            )

            # 如果没有输出，说明目录为空
            if success and not stdout.strip():
                success, stdout, stderr = ssh_client.execute_command(
                    f'rmdir "{parent_str}"'
                )
                if success:
                    logger.debug(f"删除空目录: {parent_str}")
                    # 递归检查上级目录
                    self._remove_empty_parent_directories(
                        ssh_client, parent_path.parent
                    )
                else:
                    logger.debug(f"无法删除目录 {parent_str}: {stderr}")

        except Exception as e:
            logger.debug(f"删除空父目录时出错: {e}")


def create_remote_strm_file(
    media_file_path: Path,
    strm_dst_file_path: Path,
    hostname: str = STRM_RSYNC_DEST_SERVER,
    username: str = "root",
) -> bool:
    """
    便捷函数：在远程服务器上创建 STRM 文件

    Args:
        media_file_path: 媒体文件路径
        strm_dst_file_path: STRM 文件的目标路径
        hostname: 远程服务器主机名
        username: SSH 用户名

    Returns:
        bool: 创建是否成功
    """
    strm_manager = RemoteStrmManager(hostname, username)
    return strm_manager.create_strm_file(media_file_path, strm_dst_file_path)


def delete_remote_strm_file(
    strm_file_path: Path,
    hostname: str = STRM_RSYNC_DEST_SERVER,
    username: str = "root",
) -> bool:
    """
    便捷函数：删除远程服务器上的 STRM 文件

    Args:
        strm_file_path: 要删除的 STRM 文件路径
        hostname: 远程服务器主机名
        username: SSH 用户名

    Returns:
        bool: 删除是否成功
    """
    strm_manager = RemoteStrmManager(hostname, username)
    return strm_manager.delete_strm_file(strm_file_path)


def delete_remote_strm_directory(
    strm_dir_path: Path,
    hostname: str = STRM_RSYNC_DEST_SERVER,
    username: str = "root",
    remove_empty_parents: bool = True,
) -> bool:
    """
    便捷函数：删除远程服务器上的 STRM 目录

    Args:
        strm_dir_path: 要删除的 STRM 目录路径
        hostname: 远程服务器主机名
        username: SSH 用户名
        remove_empty_parents: 是否删除空的父目录

    Returns:
        bool: 删除是否成功
    """
    strm_manager = RemoteStrmManager(hostname, username)
    return strm_manager.delete_strm_directory(strm_dir_path, remove_empty_parents)


def copy_file_to_remote(
    local_file_path: Path,
    remote_file_path: Path,
    hostname: str = STRM_RSYNC_DEST_SERVER,
    username: str = "root",
) -> bool:
    """
    将本地文件复制到远程服务器

    Args:
        local_file_path: 本地文件路径
        remote_file_path: 远程文件路径
        hostname: 远程服务器主机名
        username: SSH 用户名

    Returns:
        bool: 复制是否成功
    """
    try:
        with SSHClient(hostname, username) as ssh_client:
            sftp = ssh_client.get_sftp()
            if not sftp:
                logger.error("无法创建 SFTP 连接")
                return False

            # 确保远程目录存在
            remote_dir = str(Path(remote_file_path).parent)
            if not ssh_client.create_directory(remote_dir):
                logger.error(f"无法创建远程目录: {remote_dir}")
                return False

            # 复制文件
            local_file_str = str(local_file_path)
            remote_file_str = str(remote_file_path)

            logger.debug(f"开始复制文件: {local_file_str} -> {remote_file_str}")
            sftp.put(local_file_str, remote_file_str)

            # 设置文件权限
            if not ssh_client.set_ownership(remote_file_str, UID, GID):
                logger.warning(f"设置文件权限失败，但文件复制成功: {remote_file_str}")

            logger.info(f"文件复制成功: {remote_file_str}")
            return True

    except Exception as e:
        logger.error(
            f"文件复制失败: {local_file_path} -> {remote_file_path}, 错误: {e}"
        )
        return False


def check_remote_path_exists(
    path: str,
    hostname: str = STRM_RSYNC_DEST_SERVER,
    username: str = "root",
) -> bool:
    """
    便捷函数：检查远程服务器上的文件或目录是否存在

    Args:
        path: 要检查的文件或目录路径
        hostname: 远程服务器主机名
        username: SSH 用户名

    Returns:
        bool: 文件或目录是否存在
    """
    try:
        with SSHClient(hostname, username) as ssh_client:
            return ssh_client.remote_path_exists(path)
    except Exception as e:
        logger.error(f"检查远程路径失败: {path}, 错误: {e}")
        return False


def move_remote_file(
    source_path: str,
    destination_path: str,
    hostname: str = STRM_RSYNC_DEST_SERVER,
    username: str = "root",
    create_dest_dir: bool = True,
) -> bool:
    """
    便捷函数：在远程服务器上移动文件或目录到另一个位置

    Args:
        source_path: 源文件或目录路径
        destination_path: 目标文件或目录路径
        hostname: 远程服务器主机名
        username: SSH 用户名
        create_dest_dir: 是否自动创建目标目录

    Returns:
        bool: 移动是否成功
    """
    try:
        with SSHClient(hostname, username) as ssh_client:
            return ssh_client.move_remote_file(
                source_path, destination_path, create_dest_dir
            )
    except Exception as e:
        logger.error(
            f"远程文件移动失败: {source_path} -> {destination_path}, 错误: {e}"
        )
        return False
