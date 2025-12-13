import traceback
from time import sleep
from typing import Union

from src.log import logger

from .emby import Emby
from .plex import Plex


def send_scan_request(
    scan_folders: Union[str, list, tuple],
    plex=True,
    emby=True,
    interval=0,
    random_interval=False,
):
    # handle scan request
    if not isinstance(scan_folders, (list, tuple)):
        scan_folders = [scan_folders]
    media_servers = []
    if plex:
        retry = 0
        while retry < 3:
            try:
                _plex = Plex()
            except Exception as e:
                logger.error(f"Failed to initialize Plex due to: {e}")
                logger.error(traceback.format_exc())
            else:
                media_servers.append(_plex)
                break
            retry += 1
    if emby:
        _emby = Emby()
        media_servers.append(_emby)
    for server in media_servers:
        while True:
            try:
                server.scan(
                    path=set(scan_folders),
                    interval=interval,
                    random_interval=random_interval,
                )
            except Exception as e:
                logger.error(f"Send scan request failed due to: {e}")
                logger.error(traceback.format_exc())
                sleep(60)
                continue
            else:
                break
