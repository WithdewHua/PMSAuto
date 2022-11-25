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


# qBittorrent 设置
# host
QBIT_HOST = "127.0.0.1"
QBIT_PORT = 8080
QBIT_USER = "admin"
QBIT_PASSWD = 'xxxxxxxxxxxxxxx'


# TG 通知相关设置
# api key
TG_API_KEY = "xxxx:xxxxxxxxxxxxxxxxxxxx"
# 需要通知的 chat id
TG_CHAT_ID = [
    "234886189",
    # "-1001681825024",
]

# GD 相关设置
# 多个机器操作同一个 GD 时，可能发生冲突，一台机器设置 True 即可
REMOVE_EMPTY_FOLDER = False

