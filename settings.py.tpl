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
    "password": 'kkUtDJ%q2nf@he&j5xXCZ!Nd'
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

# 重命名设置
ORIGIN_NAME = True

# plex 设置
PLEX_BASE_URL = "https://xxx.xx"
PLEX_API_TOKEN = "xxxxxxxxxx"
AUTO_SCAN = True
