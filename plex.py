#!/user/bin/env python3

from typing import Optional, Union, Sequence

import re
from time import sleep

from plexapi.server import PlexServer
from plexapi.myplex import Section
from settings import PLEX_BASE_URL, PLEX_API_TOKEN
from log import logger


class Plex:
    """class Plex"""

    def __init__(self, base_url: str = PLEX_BASE_URL, token: str = PLEX_API_TOKEN):
        self.plex_server = PlexServer(baseurl=base_url, token=token)

    def get_section_by_location(self, location: str) -> Optional[Section]:
        for section in self.plex_server.library.sections():
            for loc in section.locations:
                if re.search(rf"{loc}", location):
                    return section

        return None

    def _get_lastest_added_item(self, section: Section):
        return section.recentlyAdded(1)[0]

    def _is_scanned(self, section: Section, path: str) -> bool:
        media = self._get_lastest_added_item(section)
        # 根据最近添加的项目的名字来大致确认是否扫描成功
        titles = [title for title in [media.title, media.originalTitle] if title]
        if re.search(r"|".join(titles), path):
            return True
        return False

    def scan(self, path: Union[str, Sequence]):
        """发送扫描请求"""
        if isinstance(path, str):
            path = [path]
        _path = set(path)
        for p in set(path):
            section = self.get_section_by_location(p)
            if not section:
                logger.error("Section Not found")
                _path.remove(p)
        if not _path:
            return False

        for p in _path:
            while True:
                try:
                    section.update(p)
                except Exception as e:
                    logger.error(e)
                    sleep(10)
                    continue
                else:
                    logger.info(f"Sent scan request successfully: {path}")
                    break
