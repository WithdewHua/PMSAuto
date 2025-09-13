import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from log import logger
from settings import GID, STRM_FILE_PATH, STRM_MEDIA_SOURCE, UID


def create_strm_file(
    file_path: Path,
    strm_path: Path = Path(STRM_FILE_PATH),
    strm_file_path: Optional[Path] = None,
    media_source: str = STRM_MEDIA_SOURCE,
):
    """
    创建 .strm 文件

    Args:
        file_path: 媒体文件的完整路径
        strm_path: .strm 文件存放目录
        strm_file_path: 指定 .strm 文件的完整路径（包含文件名），优先级高于 strm_path
        media_source: 媒体源 URL 前缀
    """
    try:
        # 优先使用 strm_file_path 参数
        if strm_file_path:
            strm_path = strm_file_path.parent
        # 确保 strm 目录存在
        strm_path.mkdir(parents=True, exist_ok=True)

        # 构造 .strm 文件的内容
        strm_content = f"{media_source.rstrip('/')}/{quote(str(file_path).lstrip('/'))}"

        # 构造 .strm 文件的完整路径
        strm_file_name = file_path.name + ".strm"
        strm_file_full_path = (
            (strm_path / strm_file_name) if not strm_file_path else strm_file_path
        )

        # 写入 .strm 文件
        strm_file_full_path.write_text(strm_content, encoding="utf-8")

        # 设置权限
        for item in strm_path.rglob("*"):
            shutil.chown(str(item), user=UID, group=GID)
        shutil.chown(str(strm_path), user=UID, group=GID)

        logger.info(f"为 {file_path} 创建 strm 文件成功: {strm_file_full_path}")
        return True
    except Exception as e:
        logger.error(f"为 {file_path} 创建 strm 文件失败: {e}")
        return False


if __name__ == "__main__":
    create_strm_file(
        Path(
            "/Media/TVShows/Aired_2002/M06/[火线] The Wire (2002) {tmdb-1438}/Season 04/[火线] The Wire (2002) {tmdb-1438} - S04E06 - The.Wire.S04E06.2006.1080p.Blu-ray.x265.10bit.AC3￡cXcY@FRDS.mkv"
        ),
        Path("./data"),
    )
