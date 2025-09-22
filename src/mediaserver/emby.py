#! /usr/bin/env python3

import json
import re
from pathlib import Path
from time import sleep
from typing import Dict, List, Optional, Sequence, Union

import requests
from src.log import logger
from src.settings import EMBY_API_TOKEN, EMBY_BASE_URL, STRM_FILE_PATH
from src.strm import create_strm_file


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
        fields="Path,MediaSources",
        item_types="Movie,Episode,Series,Audio,Music,Game,Book,MusicVideo,BoxSet",
        recursive=True,
    ):
        """
        获取媒体项目

        Args:
            parent_id: 父级ID (媒体库ID)
            fields: 需要返回的字段
            item_types: 项目类型
            recursive: 是否递归查询
        """
        try:
            url = f"{self.base_url}/Items"
            params = {
                "api_key": self.token,
                "Recursive": str(recursive).lower(),
                "IncludeItemTypes": item_types,
                "Fields": fields,
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

    def delete_item(
        self,
        item_id: Union[str, int, list],
        parent_id: bool = False,
        item_types: str = "Folder,Season",
        max_retry=None,
    ) -> bool:
        """
        删除媒体项目

        Args:
            item_id: 媒体项目ID
            parent_id: 是否是父级ID, 如果是则遍历删除所有子项目，默认 False

        """
        try:
            if not isinstance(item_id, list):
                item_id = [item_id]
            if parent_id:
                to_delete_items = set()
                for _item_id in item_id:
                    items = self.get_items(
                        parent_id=_item_id,
                        recursive=True,
                        fields="Path,Settings",
                        item_types=item_types,
                    )
                    for item in items:
                        if not item.get("Path"):
                            logger.warning(f"跳过没有路径的项目: {item}")
                            continue
                        to_delete_items.add((item["Id"], item.get("Path")))
                # 排序，先删除子项目
                to_delete_items = sorted(
                    to_delete_items, key=lambda x: x[1].count("/"), reverse=True
                )
                logger.info(f"准备删除 {len(to_delete_items)} 个项目")
                for _id, path in to_delete_items:
                    retry = 0
                    while True:
                        retry += 1
                        if max_retry and retry > max_retry:
                            logger.error(
                                f"达到最大重试次数 {max_retry}，停止删除 {_id}, 路径: {path}"
                            )
                            break
                        if self._delete_item(_id):
                            logger.info(f"删除项目成功: {_id}, 路径: {path}")
                            logger.info(
                                f"当前进度 {to_delete_items.index((_id, path)) + 1}/{len(to_delete_items)}"
                            )
                            break
                        else:
                            logger.error(
                                f"删除项目失败: {_id}, 路径: {path}, 60s 后再次尝试"
                            )
                            sleep(60)
            else:
                for _item_id in item_id:
                    retry = 0
                    while True:
                        retry += 1
                        if max_retry and retry > max_retry:
                            logger.error(
                                f"达到最大重试次数 {max_retry}，停止删除 {_item_id}"
                            )
                            break
                        if self._delete_item(_item_id):
                            logger.info(f"删除项目成功: {_item_id}")
                            break
                        else:
                            logger.error(f"删除项目失败: {_item_id}, 60s 后再次尝试")
                            sleep(60)
        except Exception as e:
            logger.error(f"删除媒体项目 {item_id} 失败: {e}")

    def _delete_item(self, item_id: str) -> bool:
        """删除单个媒体项目"""
        try:
            url = f"{self.base_url}/emby/Items/Delete?Ids={item_id}"
            params = {
                "X-Emby-Client": "Emby Web",
                "X-Emby-Device-Name": "Google Chrome macOS",
                "X-Emby-Device-Id": "1abfc566-d6d0-477a-a56d-60ceb4833b3d",
                "X-Emby-Client-Version": "4.8.11.0",
                "X-Emby-Token": "ac4252bd8e8c450893e2964319658707",
                "X-Emby-Language": "zh-cn",
            }
            response = requests.post(url, params=params, timeout=600)
            response.raise_for_status()
            logger.info(f"删除媒体项目 {item_id} 成功")
            return True
        except Exception as e:
            logger.error(f"删除媒体项目 {item_id} 失败: {e}")
            return False

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
    # e.create_strm_file_for_existed_items(filter=["TV Shows"])
    e.delete_item(
        ["333478"], parent_id=True, item_types="Folder,Season,Video", max_retry=3
    )
