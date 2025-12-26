#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Union

import requests
from src.log import logger
from src.settings import MEDIA_SUFFIX, TG_API_KEY


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=4, separators=(",", ": "))


# BOT
TG_BOT_MSG = f"https://api.telegram.org/bot{TG_API_KEY}/sendMessage"
# TG_BOT_PIC = f'https://api.telegram.org/bot{API_KEY}/sendPhoto'

# 消息缓存：用于防止短时间内发送重复消息
# 格式: {message_hash: last_send_timestamp}
_tg_msg_cache = {}
_tg_msg_cache_lock = threading.Lock()
_TG_MSG_INTERVAL = 300  # 5分钟 = 300秒


def send_tg_msg(chat_id, text, parse_mode="markdownv2"):
    """Send telegram message

    相同消息在5分钟内只发送一次，避免触发Telegram的消息限制
    """
    # 生成消息的唯一标识（使用 chat_id 和 text 组合）
    msg_key = f"{chat_id}:{text}"

    # 检查是否需要发送
    current_time = time.time()
    with _tg_msg_cache_lock:
        last_send_time = _tg_msg_cache.get(msg_key, 0)
        if current_time - last_send_time < _TG_MSG_INTERVAL:
            logger.debug(
                f"消息被限流跳过（距上次发送 {int(current_time - last_send_time)}秒）: {text[:50]}..."
            )
            return

        # 更新发送时间
        _tg_msg_cache[msg_key] = current_time

        # 清理过期的缓存记录（超过10分钟的）
        expired_keys = [
            k
            for k, v in _tg_msg_cache.items()
            if current_time - v > _TG_MSG_INTERVAL * 2
        ]
        for k in expired_keys:
            del _tg_msg_cache[k]

    if isinstance(chat_id, (str, int)):
        chat_id = [chat_id]
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    with requests.Session() as session:
        for _chat_id in chat_id:
            try_send = 1
            while try_send <= 3:
                try:
                    res = session.post(
                        TG_BOT_MSG,
                        data=json.dumps(
                            {
                                "chat_id": _chat_id,
                                "text": text,
                                "parse_mode": parse_mode,
                            }
                        ),
                        headers=headers,
                        timeout=10,
                    )
                    res.raise_for_status()
                except Exception as e:
                    try_send += 1
                    logger.error(f"Send notification failed due to {e}")
                    continue
                else:
                    break


def remove_empty_folder(
    root="/Media/Inbox",
    folders=["Anime", "Movies", "TVShows", "NSFW", "NC17-Movies", "Concerts"],
    remove_root_folder=False,
    exclude_filter: str = None,
    delete_file_filter: str = None,
):
    """Remove empty folder
    args:
        exclude_filter: folders to exclude
        delete_file_filter: folders only contains the specified file will be deleted
    """

    if not folders:
        folders = [root]

    for folder in folders:
        root_folder = folder if folder == root else os.path.join(root, folder)
        logger.debug(f"Checking folder: {root_folder}")
        if not os.path.exists(root_folder):
            continue

        for rootdir, subdir, files in os.walk(root_folder, topdown=False):
            # 跳过匹配 exclude_filter 的文件夹
            if exclude_filter and re.search(rf"{exclude_filter}", rootdir):
                continue
            if os.path.basename(rootdir) == root_folder and not remove_root_folder:
                continue
            # 空文件夹
            if not files and not subdir:
                logger.info(f"Removing empty foler: {rootdir}")
                os.rmdir(rootdir)
            # 文件夹中只包含匹配 delete_file_filter 的文件
            if not subdir and delete_file_filter:
                all_match = True
                for file in files:
                    if not re.search(rf"{delete_file_filter}", file):
                        all_match = False
                        break
                if all_match:
                    shutil.rmtree(rootdir, ignore_errors=True)
                    logger.info(f"Removing foler: {rootdir}, which contains {files}")


def is_filename_length_gt_255(filename, extra_len=0):
    if len(filename.encode("utf-8")) + extra_len > 255:
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


def remove_original_title_from_file(path: str) -> None:
    """对指定路径下的文件进行重命名,移除 tmdb 名字中的原标题"""
    files = iterdir_recursive(path)
    for file in files:
        new_name = re.sub(r"\[(.*)\].*(\(\d{4}\)\s+{tmdb-\d+})", r"\1 \2", file.name)
        if new_name == file.name:
            continue
        if is_filename_length_gt_255(new_name):
            new_name = new_name.split(" - ", 1)[1].strip()
        file.rename(file.parent / new_name)
        logger.info(f"Renaming {file.name} to {new_name}")


def iterdir_recursive(path: Union[str, Path]) -> list[Path]:
    """递归获取指定路径下所有文件"""
    files = []
    for p in Path(path).iterdir():
        if p.is_dir():
            files.extend(iterdir_recursive(p))
        files.append(p)
    return files


def remove_folder_contains_no_media(path):
    for dir in Path(path).iterdir():
        if re.search(r"Aired_", dir.name):
            continue
        remove_flag = True
        for file in iterdir_recursive(dir.absolute()):
            suffix = file.name.split(".")[-1]
            if suffix in MEDIA_SUFFIX:
                logger.info(f"file {file.name} is media, skip...")
                remove_flag = False
                break
        if remove_flag:
            logger.info(f"Removing folder: {dir.absolute()}")
            shutil.rmtree(dir.absolute())


def get_file_list(path):
    try:
        rslt = subprocess.run(
            f'rclone lsjson -R "{path}"',
            encoding="utf-8",
            shell=True,
            capture_output=True,
        )
        if rslt.returncode:
            return False, f"Failed to check {path}: {rslt.stdout}"
        files = json.loads(rslt.stdout.strip())
        files = [file.get("Path") for file in files]
        return True, files
    except Exception as e:
        return False, f"Failed to check {path} due to: {e}"


class Singleton(type):
    _instance_lock = threading.Lock()

    def __call__(cls, *args, **kwds):
        with Singleton._instance_lock:
            if not hasattr(cls, "_instance"):
                cls._instance = super().__call__(*args, **kwds)
        return cls._instance
