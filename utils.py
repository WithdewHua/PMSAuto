#!/usr/bin/env python3

import json
import os
import requests
from settings import TG_API_KEY
from log import logger


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=4, separators=(',', ': '))


# BOT
TG_BOT_MSG = f'https://api.telegram.org/bot{TG_API_KEY}/sendMessage'
# TG_BOT_PIC = f'https://api.telegram.org/bot{API_KEY}/sendPhoto'

def send_tg_msg(chat_id, text, parse_mode="markdownv2"):
    """Send telegram message"""
    if isinstance(chat_id, str):
        payload = dict(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode
        )
        try_send = 1
        while try_send <=3:
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
            payload = dict(
                chat_id=_chat_id,
                text=text,
                parse_mode=parse_mode
            )
            try_send = 1
            while try_send <=3:
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


def remove_empty_folder(root="/Media/Inbox", folders=["Anime", "Movies", "TVShows", "NSFW", "NC17-Movies", "Concerts"]):
    """Remove empty folder"""

    for dir in folders:
        root_folder = os.path.join(root, dir)
        logger.debug(f"Checking folder: {root_folder}")
        folders = os.listdir(root_folder) if os.path.exists(root_folder) else []
        for folder in folders:
            folder_path = os.path.join(root_folder, folder)
            if os.path.isdir(folder_path) and (not os.listdir(folder_path)):
                logger.info(f"Removing empty foler: {folder_path}")
                os.rmdir(folder_path)


