#!/usr/bin/env python
# Author: WithdewHua

# 日志设置
LOG_LEVEL = "INFO"

# TMDB API Key
TMDB_API_KEY = "xxxxxxxxxxxxxx"

# 数据存储目录
DATA_DIR = "/opt/PMSAuto/data"

# rclone 相关设置
# 如果重命名失败, 是否需要上传至 GD
# 主要失败原因有:
#   1. 获取 tmdb 信息失败;
#   2. 对于剧集, 季度信息缺失
RCLONE_ALWAYS_UPLOAD = False
# rclone rc address
RC_ADDR = ""


# qBittorrent 设置
QBIT = {
    "host": "127.0.0.1",
    "port": 8080,
    "user": "admin",
    "password": "kkUtDJ%q2nf@he&j5xXCZ!Nd",
}

# TG 通知相关设置
# api key
TG_API_KEY = "xxxx:xxxxxxxxxxxxxxxxxxxx"
# 需要通知的 chat id
TG_CHAT_ID = [
    "234886189",
    # "-1001681825024",
]

# GD 相关设置
REMOVE_EMPTY_FOLDER = False
HANDLE_LOCAL_MEDIA = False

# 分类设置
CATEGORY_SETTINGS_MAPPING = {
    "TVShows": [
        (
            (None, 2024),
            {
                "rclone": "GD-TVShows",
                "local": "TVShows",
                "mount_point": "/Media",
            },
        ),
        (
            (2025, None),
            {
                "rclone": "GD-TVShows2",
                "local": "TVShows",
                "mount_point": "/Media2",
            },
        ),
    ],
    "Anime": [
        (
            (None, 2024),
            {
                "rclone": "GD-TVShows",
                "local": "TVShows",
                "mount_point": "/Media",
            },
        ),
        (
            (2025, None),
            {
                "rclone": "GD-TVShows2",
                "local": "TVShows",
                "mount_point": "/Media2",
            },
        ),
    ],
    "Movies": [
        (
            (None, None),
            {
                "rclone": "GD-Movies",
                "local": "Movies",
                "mount_point": "/Media",
            },
        ),
    ],
    "NC17-Movies": [
        (
            (None, None),
            {
                "rclone": "GD-Movies",
                "local": "NC17-Movies",
                "mount_point": "/Media",
            },
        ),
    ],
    "Concerts": [
        (
            (None, None),
            {
                "rclone": "GD-Movies",
                "local": "Concerts",
                "mount_point": "/Media",
            },
        ),
    ],
    "NSFW": [
        (
            (None, None),
            {
                "rclone": "GD-NSFW",
                "local": "NSFW",
                "mount_point": "/Media",
            },
        ),
    ],
    "Music": [
        (
            (None, None),
            {
                "rclone": "GD-Music",
                "local": "Music",
                "mount_point": "/Media",
            },
        ),
    ],
}

# 媒体处理设置
ORIGIN_NAME = True
# 媒体后缀
MEDIA_SUFFIX = [
    "srt",
    "ass",
    "ssa",
    "sup",
    "mkv",
    "ts",
    "mp4",
    "flv",
    "rmvb",
    "avi",
    "mov",
]

# plex 设置
PLEX_BASE_URL = "https://xxxxxxxxxx"
PLEX_API_TOKEN = "xxxx"
PLEX_AUTO_SCAN = True
# Plex 服务器主机地址（SSH 连接用）
PLEX_SERVER_HOST = "100.66.103.236"
# Plex 数据库路径
PLEX_DB_PATH = "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
# emby 设置
EMBY_BASE_URL = "https://xxxxxxxxxx"
EMBY_API_TOKEN = "xxxx"
EMBY_AUTO_SCAN = True
# 神医插件 mediainfo 持久化
# 当采用 strm 时，该选项不生效，即与 strm 文件同目录
EMBY_STRM_ASSISTANT_MEDIAINFO = "/opt/PMS/emby/config/StrmAssistant/MediaInfo"
# strm 文件设置
CREATE_STRM_FILE = True
STRM_FILE_PATH = "/opt/PMS/emby/config/strm"
STRM_MEDIA_SOURCE = "http://127.0.0.1:10001/stream"
UID = 998
GID = 997
STRM_RSYNC_DEST_SERVER = "100.66.173.121"
