#!/user/bin/env python3

from typing import Optional

import logging
from time import sleep

from plexapi.server import PlexServer
from plexapi.myplex import Section
from settings import PLEX_BASE_URL, PLEX_API_TOKEN


class Plex:
    """class Plex"""

    def __init__(self, base_url: str=PLEX_BASE_URL, token: str=PLEX_API_TOKEN):
        self.plex_server = PlexServer(baseurl=base_url, token=token)

    def get_section_by_location(self, location: str) -> Optional[Section]:
        for section in self.plex_server.library.sections():
            if location in section.locations:
                return section

        return None

    def scan(self, location: str, path: str):
        section = self.get_section_by_location(location)
        if not section:
            logging.error("Section Not found")
            return False
        while True:
            try:
                section.update(path)
            except Exception as e:
                logging.error(e)
                sleep(10)
                continue
            else:
                logging.info(f"Sent scan request successfully: {path}")




