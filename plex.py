#!/user/bin/env python3

from typing import Optional

import re
from time import sleep

from plexapi.server import PlexServer
from plexapi.myplex import Section
from settings import PLEX_BASE_URL, PLEX_API_TOKEN
from log import logger


class Plex:
    """class Plex"""

    def __init__(self, base_url: str=PLEX_BASE_URL, token: str=PLEX_API_TOKEN):
        self.plex_server = PlexServer(baseurl=base_url, token=token)

    def get_section_by_location(self, location: str) -> Optional[Section]:
        for section in self.plex_server.library.sections():
            if location in section.locations:
                return section

        return None

    def get_lastest_added_item(self, section: Section):
        return section.recentlyAdded(1)[0]

    def is_scanned(self, section: Section, path: str) -> bool:
        media = self.get_lastest_added_item(section)
        # 根据最近添加的项目的名字来大致确认是否扫描成功
        titles = [title for title in [media.title, media.originalTitle] if title]
        if re.search(r"|".join(titles), path):
            return True
        return False

    def scan(self, location: str, path: str):
        section = self.get_section_by_location(location)
        if not section:
            logger.error("Section Not found")
            return False
        while True:
            try:
                section.update(path)
            except Exception as e:
                logger.error(e)
                sleep(10)
                continue
            else:
                logger.info(f"Sent scan request successfully: {path}")
                sleep(60)
                if self.is_scanned(section, path):
                    logger.info("Processed scan request successfully")
                    break
                logger.warn("Processed scan request unsuccessfully, try again")




