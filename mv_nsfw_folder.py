import os
from time import sleep
from log import logger
from plex import Plex
from emby import Emby

src_path = "/Media/Inbox/NSFW/Done"
dst_path = "/Media/NSFW"
limit = 20

src_dirs = os.listdir(src_path)
dst_dirs = os.listdir(dst_path)

count = 0
scan_folders = []
for src_dir in src_dirs:
    if os.path.isdir(os.path.join(src_path, src_dir)) and (
        src_dir not in ["failed", "佚名"]
    ):
        if not os.listdir(os.path.join(src_path, src_dir)):
            logger.info("Empty directory: " + src_dir)
            continue
        else:
            if src_dir in dst_dirs:
                logger.info("Directory already exists: " + src_dir)
                for dir in os.listdir(os.path.join(src_path, src_dir)):
                    if os.path.exists(os.path.join(dst_path, src_dir, dir)):
                        logger.warning("Folder already exists: " + dir)
                        continue
                    else:
                        os.rename(
                            os.path.join(src_path, src_dir, dir),
                            os.path.join(dst_path, src_dir, dir),
                        )
                        logger.info("Folder moved: " + dir)
                        count += 1
                        logger.info(f"Processed {count} movies")
                        scan_folders.append(os.path.join(dst_path, src_dir, dir))
                        logger.info(
                            f"Added scan folder {os.path.join(dst_path, src_dir, dir)}"
                        )

                # os.system(f'mv {src_path}/{src_dir}/* {dst_path}/{src_dir}')
            else:
                logger.info("Moving directory: " + src_dir)
                os.system(f'mv "{src_path}/{src_dir}" {dst_path}')
                count += 1
                logger.info(f"Processed {count} movies")
                scan_folders.append(os.path.join(dst_path, src_dir))
                logger.info(f"Added scan folder {os.path.join(dst_path, src_dir)}")
    if count > limit:
        break


# send scan request
plex = Plex()
emby = Emby()
for folder in set(scan_folders):
    logger.info(f"Sending scan request for {folder}")
    for media_server in [plex, emby]:
        media_server.scan(folder)
    sleep(10)
