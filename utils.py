#!/usr/bin/env python3

import json
import os
import re
from copy import deepcopy

import requests

from settings import TG_API_KEY
from log import logger


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=4, separators=(",", ": "))


# BOT
TG_BOT_MSG = f"https://api.telegram.org/bot{TG_API_KEY}/sendMessage"
# TG_BOT_PIC = f'https://api.telegram.org/bot{API_KEY}/sendPhoto'


def send_tg_msg(chat_id, text, parse_mode="markdownv2"):
    """Send telegram message"""
    if isinstance(chat_id, str):
        payload = dict(chat_id=chat_id, text=text, parse_mode=parse_mode)
        try_send = 1
        while try_send <= 3:
            try:
                requests.post(TG_BOT_MSG, data=payload)
            except Exception as e:
                try_send += 1
                logger.error(f"Send notification failed due to {e}")
                continue
            else:
                break
    elif isinstance(chat_id, list):
        for _chat_id in chat_id:
            payload = dict(chat_id=_chat_id, text=text, parse_mode=parse_mode)
            try_send = 1
            while try_send <= 3:
                try:
                    requests.post(TG_BOT_MSG, data=payload)
                except Exception as e:
                    try_send += 1
                    logger.error(f"Send notification failed due to {e}")
                    continue
                else:
                    break
    else:
        raise AttributeError


def remove_empty_folder(
    root="/Media/Inbox",
    folders=["Anime", "Movies", "TVShows", "NSFW", "NC17-Movies", "Concerts"],
    remove_root_folder=False,
):
    """Remove empty folder"""

    if not folders:
        folders = [root]

    for dir in folders:
        root_folder = dir if dir == root else os.path.join(root, dir)
        logger.debug(f"Checking folder: {root_folder}")
        if not os.path.exists(root_folder):
            continue

        while True:
            redo = False
            for dir, subdir, files in os.walk(root_folder, topdown=False):
                if not files and not subdir:
                    if os.path.basename(dir) == root_folder and not remove_root_folder:
                        continue
                    logger.info(f"Removing empty foler: {dir}")
                    os.rmdir(dir)
                    redo = True
            if not redo:
                break


def is_filename_length_gt_255(filename):
    if len(filename.encode("utf-8")) > 255:
        return True
    return False


def sumarize_tags(ori_tags: list[str], new_tags: list[str]) -> list[str]:
    """
    对种子 tag 进行更新：
    1. 取并集
    2. 相同类型取新 tag，可能类型有 Y(年份) / T(TMDB ID) / O(offset) / S(季)
    """
    tags = deepcopy(ori_tags)
    for tag in new_tags:
        # 匹配关键字 tag
        match = re.match(r"([TYOS])-?\d+", tag)
        if match:
            # 获取 tag 类型
            _type = match.group(1)
            for _ in ori_tags:
                if _.startswith(_type):
                    logger.info(f"Removing tag {_}")
                    tags.remove(_)
    return list(set(tags).union(new_tags))
