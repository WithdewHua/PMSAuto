import os
from pathlib import Path
from typing import Union

from src.log import logger
from src.utils import is_filename_length_gt_255


def rename_media(old_path, new_path, dryrun=False, replace=True):
    if os.path.exists(new_path):
        if not replace:
            logger.warning(f"{os.path.basename(new_path)} exists in {new_path}")
            return True
        else:
            if not dryrun:
                if os.path.isfile(new_path):
                    logger.info(f"Removing existed file {new_path}")
                    os.remove(new_path)
    if not dryrun:
        if os.path.isdir(old_path) and os.path.exists(new_path):
            for path in os.listdir(old_path):
                rename_media(
                    os.path.join(old_path, path),
                    os.path.join(new_path, path),
                    dryrun,
                    replace,
                )
        else:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            os.rename(old_path, new_path)
    logger.info(old_path + " --> " + new_path)

    return True


def check_and_handle_long_filename(folder: Union[str, Path], offset: int = 0):
    """处理文件名过长的问题"""
    if isinstance(folder, str):
        folder = Path(folder)
    for file in folder.rglob("*"):
        if not file.is_file():
            continue
        if is_filename_length_gt_255(file.name, extra_len=offset):
            logger.warning(f"文件名过长，尝试重命名: {file}")
            new_name = file.name.split(" - ", 1)[-1]
            new_path = file.with_name(new_name)
            try:
                file.rename(new_path)
                logger.info(f"重命名成功: {file} --> {new_path}")
            except Exception as e:
                logger.error(f"重命名失败: {file}, 错误: {e}")
                continue


def remove_hidden_files(root_dir_path, dryrun=False):
    removed_files = []
    for file in os.listdir(root_dir_path):
        if file.startswith("."):
            removed_files.append((file, 1 if os.path.isdir(file) else 0))
            if not dryrun:
                os.remove(os.path.join(root_dir_path, file))
            logger.info("Removed hidden file: " + os.path.join(root_dir_path, file))
    return removed_files


def remove_small_files(root_dir_path, threshold=128 * 1024 * 1024, dryrun=False):
    for file in os.listdir(root_dir_path):
        filepath = os.path.join(root_dir_path, file)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            if size < threshold:
                if not dryrun:
                    os.remove(filepath)
                logger.info("Removed file: " + filepath + f", size {size}")


def set_ownership(
    path: Path,
    uid: Union[str, int],
    gid: Union[str, int],
    recursive=True,
    start_prefix=None,
):
    if recursive:
        current_path = ""
        file_parts = str(path).strip("/").split("/")
        for part in file_parts:
            if not part:
                continue
            current_path = f"{current_path}/{part}" if current_path else f"/{part}"
            if start_prefix and start_prefix not in current_path:
                continue
            os.chown(current_path, uid=uid, gid=gid)
            logger.info(f"修改文件(夹)权限：{current_path} ({uid}:{gid})")
    else:
        os.chown(path, uid, gid)
        logger.info(f"修改文件(夹)权限：{current_path} ({uid}:{gid})")
