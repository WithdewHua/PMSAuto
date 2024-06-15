#! /usr/bin/env python3

import requests
import json

from time import sleep
from typing import List, Dict, Optional, Union, Sequence

from settings import EMBY_BASE_URL, EMBY_API_TOKEN
from log import logger


class Emby:
    "Emby Class"

    def __init__(
        self, base_url: str = EMBY_BASE_URL, token: str = EMBY_API_TOKEN
    ) -> None:
        self.token = token
        self.base_url = base_url

    @property
    def libraries(self) -> List[Dict[str, str]]:
        res = requests.get(
            f"{self.base_url}/Library/SelectableMediaFolders?api_key={self.token}"
        )
        if res.status_code != requests.codes.ok:
            logger.error(f"Error: fail to get libraries: {res.text}")
            res.raise_for_status()
        _libraries = []
        for lib in res.json():
            name = lib.get("Name")
            subfolders = lib.get("SubFolders")
            for _ in subfolders:
                path = _.get("Path")
                _libraries.append({"library": name, "path": path})
        return _libraries

    def get_library_by_location(self, path: str) -> Optional[str]:
        """通过路径获取库"""
        for lib in self.libraries:
            if path.startswith(lib.get("path")):
                return lib.get("library")
        return None

    def scan(self, path: Union[str, Sequence]) -> None:
        """发送扫描请求"""
        if isinstance(path, str):
            path = [path]
        _path = set(path)
        for p in set(path):
            lib = self.get_library_by_location(p)
            if not lib:
                logger.warning(f"Warning: library not found for {p}")
                _path.remove(p)
        if not _path:
            return

        payload = {"Updates": [{"Path": p} for p in _path]}

        headers = {"Content-Type": "application/json"}

        while True:
            try:
                res = requests.post(
                    url=f"{self.base_url}/Library/Media/Updated?api_key={self.token}",
                    data=json.dumps(payload),
                    headers=headers,
                )
                res.raise_for_status()
            except (requests.Timeout, requests.ConnectionError) as e:
                logger.error(e)
                sleep(10)
                continue
            except requests.HTTPError:
                logger.error(f"Error: {res.status_code}, {res.text}")
                sleep(10)
                continue
            else:
                logger.info(f"Sent scan request successfully: {_path}")
                break
