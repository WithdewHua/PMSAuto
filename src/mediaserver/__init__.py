import traceback
from time import sleep
from typing import Union

from src.log import logger

from .emby import Emby
from .plex import Plex


def send_scan_request(scan_folders: Union[str, list, tuple, set], plex=True, emby=True):
    # handle scan request
    if not isinstance(scan_folders, (list, tuple)):
        scan_folders = [scan_folders]
    media_servers = []
    if plex:
        _plex = Plex()
        media_servers.append(_plex)
    if emby:
        _emby = Emby()
        media_servers.append(_emby)
    for server in media_servers:
        while True:
            try:
                server.scan(path=set(scan_folders))
            except Exception as e:
                logger.error(f"Send scan request failed due to: {e}")
                logger.error(traceback.format_exc())
                sleep(60)
                continue
            else:
                break
