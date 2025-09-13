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
            logger.error(f"远程文件写入失败: {file_path}, 错误: {e}")
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
        command = f"chown -R {user}:{group} '{path}'"
        success, stdout, stderr = self.execute_command(command)

        if success:
            logger.debug(f"远程文件权限设置成功: {path}")
        else:
            logger.error(f"远程文件权限设置失败: {path}, 错误: {stderr}")

        return success


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


if __name__ == "__main__":
    # 测试用例
    test_media_path = Path("/Media/TVShows/Test/Season 01/test.mkv")
    test_strm_path = Path("/opt/PMS/emby/config/strm/Test/Season 01/test.mkv.strm")

    success = create_remote_strm_file(test_media_path, test_strm_path)
    print(f"测试结果: {'成功' if success else '失败'}")
