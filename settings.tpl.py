#!/usr/bin/env python
# Author: WithdewHua

# 日志设置
LOG_LEVEL = "INFO"

# TMDB API Key
TMDB_API_KEY = "xxxxxxxxxxxxxx"

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
CATEGORY_GDDRIVE_MAPPING = {
    "TVShows": "GD-TVShows",
    "Anime": "GD-TVShows",
    "Movies": "GD-Movies",
    "NC17-Movies": "GD-Movies",
    "Concerts": "GD-Movies",
    "NSFW": "GD-NSFW",
    "Music": "GD-Music",
}

# 分类与本地文件夹映射
CATEGORY_LOCAL_FOLDER_MAPPING = {
    "TVShows": "TVShows",
    "Anime": "TVShows",
    "Movies": "Movies",
    "NC17-Movies": "NC17-Movies",
    "Concerts": "Concerts",
    "NSFW": "NSFW",
    "Music": "Music",
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
# emby 设置
EMBY_BASE_URL = "https://xxxxxxxxxx"
EMBY_API_TOKEN = "xxxx"
EMBY_AUTO_SCAN = True
