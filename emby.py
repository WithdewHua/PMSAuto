#! /usr/bin/env python3

import json
import re
from pathlib import Path
from time import sleep
from typing import Dict, List, Optional, Sequence, Union

import requests
from log import logger
from settings import EMBY_API_TOKEN, EMBY_BASE_URL, STRM_FILE_PATH
from strm import create_strm_file


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
                _id = _.get("Id")
                _libraries.append({"library": name, "path": path, "id": _id})
        return _libraries

    def get_library_by_location(self, path: str) -> Optional[str]:
        """通过路径获取库"""
        for lib in self.libraries:
            if path.startswith(lib.get("path")):
                return lib.get("library")
        return None

    def get_items(
        self,
        parent_id=None,
        item_types="Movie,Episode,Series,Audio,Music,Game,Book,MusicVideo,BoxSet",
        recursive=True,
    ):
        """
        获取媒体项目

        Args:
            parent_id: 父级ID (媒体库ID)
            item_types: 项目类型
            recursive: 是否递归查询
        """
        try:
            url = f"{self.base_url}/Items"
            params = {
                "api_key": self.token,
                "Recursive": str(recursive).lower(),
                "IncludeItemTypes": item_types,
                "Fields": "Path,MediaSources",
                "EnableTotalRecordCount": "false",
            }

            if parent_id:
                params["ParentId"] = parent_id

            response = requests.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            return data.get("Items", [])

        except Exception as e:
            logger.info(f"获取媒体项目失败: {e}")
            return []

    def get_all_items(self, filter=None):
        """获取所有视频信息"""
        logger.info("获取媒体库...")
        if filter is None:
            filter = []
        libraries = self.libraries

        all_items = []

        for library in libraries:
            lib_name = library.get("library")
            lib_id = library.get("id")
            if filter and lib_name not in filter:
                logger.info(f"媒体库 {lib_name} 不在过滤列表 ({filter}) 中，跳过...")
                continue

            logger.info(f"处理媒体库: {lib_name}, Subfolder ID: {lib_id}")

            # 获取该库中的所有视频项目
            items = self.get_items(parent_id=lib_id)

            for item in items:
                if item.get("Path") and item.get("MediaSources"):
                    all_items.append(
                        {
                            "id": item["Id"],
                            "name": item.get("Name", ""),
                            "path": item["Path"],
                            "type": item.get("Type", ""),
                            "library": lib_name,
                            "media_sources": item.get("MediaSources", []),
                        }
                    )

        logger.info(f"找到 {len(all_items)} 个视频文件")
        return all_items

    def create_strm_file_for_existed_items(self, filter=None):
        items = self.get_all_items(filter=filter)
        for item in items:
            file_path: str = item.get("path")
            # 跳过 strm 文件
            if file_path.endswith(".strm"):
                continue
            file_path = file_path.replace("/Media2", "/Media")
            strm_path = Path(STRM_FILE_PATH) / (
                re.sub(r"/M\d{2}", "", file_path).removeprefix("/Media/") + ".strm"
            )
            create_strm_file(Path(file_path), strm_file_path=strm_path)

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


if __name__ == "__main__":
    e = Emby()
    e.create_strm_file_for_existed_items(filter=["TV Shows"])
