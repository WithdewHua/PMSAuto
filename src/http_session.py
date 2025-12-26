#!/usr/local/bin/env python
"""
全局 HTTP Session 连接池管理器

提供统一的 requests.Session 管理，供 TMDB、Emby 等组件共享使用
避免创建多个连接池，减少资源消耗和连接泄漏
"""

import atexit

import requests
from src.log import logger


class GlobalHTTPSessionManager:
    """全局 HTTP Session 连接池管理器（单例模式）"""

    _instance = None
    _session = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_session(self, timeout: int = 10) -> requests.Session:
        """
        获取或创建全局共享的 HTTP Session

        Args:
            timeout: 默认超时时间（秒）

        Returns:
            requests.Session: 配置好的 Session 对象
        """
        if self._session is None:
            logger.info("初始化全局 HTTP Session 连接池")
            self._session = requests.Session()

            # 配置 HTTP 适配器 - 优化连接池参数
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=20,  # 连接池大小
                pool_maxsize=40,  # 每个主机的最大连接数
                max_retries=3,  # 重试次数
                pool_block=False,  # 非阻塞模式
            )

            # 为 HTTP 和 HTTPS 挂载适配器
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

            # 设置默认超时
            self._session.timeout = timeout

            # 设置默认请求头
            self._session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )

            # 注册程序退出时的清理函数
            atexit.register(self.cleanup)

            logger.info(
                f"全局 HTTP Session 已创建 "
                f"[pool_connections=20, pool_maxsize=40, timeout={timeout}s]"
            )

        return self._session

    def cleanup(self):
        """清理全局 Session 资源"""
        if self._session is not None:
            logger.info("清理全局 HTTP Session 连接池")
            try:
                # 关闭所有适配器
                for adapter in self._session.adapters.values():
                    try:
                        adapter.close()
                    except Exception as e:
                        logger.debug(f"关闭适配器时出错: {e}")

                # 关闭 Session
                self._session.close()
                logger.info("全局 HTTP Session 已关闭")
            except Exception as e:
                logger.exception(f"清理 HTTP Session 时出错: {e}")
            finally:
                self._session = None

    def reset_session(self):
        """重置 Session（用于特殊情况，如连接异常需要重建）"""
        logger.warning("重置全局 HTTP Session")
        self.cleanup()
        return self.get_session()


# 创建全局单例实例
_global_session_manager = GlobalHTTPSessionManager()


def get_http_session(timeout: int = 10) -> requests.Session:
    """
    获取全局共享的 HTTP Session

    这是推荐的使用方式，所有需要发送 HTTP 请求的模块都应该使用这个函数

    Args:
        timeout: 请求超时时间（秒），默认 10 秒

    Returns:
        requests.Session: 配置好的全局 Session 对象

    Example:
        >>> session = get_http_session()
        >>> response = session.get('https://api.example.com/data')
    """
    return _global_session_manager.get_session(timeout)


def reset_http_session():
    """
    重置全局 HTTP Session

    在遇到连接异常或需要清理连接时调用
    """
    return _global_session_manager.reset_session()
