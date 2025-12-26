#!/usr/local/bin/env python

import datetime
import pickle
import threading
from pathlib import Path

import filelock
from src.http_session import get_http_session
from src.log import logger
from src.settings import DATA_DIR, LOG_LEVEL, TMDB_API_KEY
from src.utils import is_filename_length_gt_255
from tmdbv3api import TV, Movie, Search, TMDb

DATA_PATH = Path(DATA_DIR)


class TMDB:
    cache: Path = DATA_PATH / "tmdb_info.cache"
    cache_lock = filelock.FileLock("/tmp/tmdb_info.cache.lock")

    _instances = {}
    _instance_lock = threading.Lock()

    def __new__(cls, movie: bool = False, **kwargs):
        """
        根据 movie 参数返回对应的单例实例
        movie=True 返回电影实例，movie=False 返回电视剧实例
        """
        with cls._instance_lock:
            # 使用 movie 参数作为 key 来缓存实例
            instance_key = f"movie_{movie}"
            if instance_key not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[instance_key] = instance
                # 标记该实例尚未初始化
                instance._initialized = False
            return cls._instances[instance_key]

    def __init__(
        self,
        api_key: str = TMDB_API_KEY,
        language: str = "zh",
        movie: bool = False,
        log_level: str = LOG_LEVEL,
        timeout: int = 10,
    ) -> None:
        # 避免重复初始化同一个实例
        if self._initialized:
            return

        # 使用全局共享的 HTTP Session
        self._session = get_http_session(timeout)

        # 将 session 传递给 TMDb
        self.tmdb = TMDb(session=self._session)
        self.tmdb.api_key = api_key
        self.tmdb.language = language
        if log_level == "DEBUG":
            self.tmdb.debug = True
        self.is_movie = movie
        self.tmdb_search = Search(session=self._session)
        if self.is_movie:
            self.tmdb_media = Movie(session=self._session)
        else:
            self.tmdb_media = TV(session=self._session)

        # 标记为已初始化
        self._initialized = True

    def __enter__(self):
        """支持 with 语句(向后兼容,但不做任何资源管理)"""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    @classmethod
    def _read_cache(cls):
        """Read cache from file"""
        with cls.cache_lock:
            if cls.cache.exists():
                with open(cls.cache, "rb") as f:
                    return pickle.load(f)
            else:
                return {}

    @classmethod
    def _write_cache(cls, cache: dict):
        """Write cache to file"""
        with cls.cache_lock:
            with open(cls.cache, "wb") as f:
                pickle.dump(cache, f)

    @classmethod
    def get_cache_by_key(cls, key):
        """Get cache by key"""
        cache = cls._read_cache()
        if key in cache:
            logger.info(f"Cache hit for {key}")
            return cache[key]
        logger.info(f"No cache found for {key}")

    @classmethod
    def write_cache_by_key(cls, key, value):
        """Write cache by key"""
        cache = cls._read_cache()
        if key in cache:
            logger.info(f"Cache updated for {key}")
        else:
            logger.info(f"Cache added for {key}")
        cache[key] = value
        cls._write_cache(cache)

    @classmethod
    def delete_cache_by_key(cls, key):
        """Delete cache by key"""
        cache = cls._read_cache()
        if key in cache:
            del cache[key]
            cls._write_cache(cache)
            logger.info(f"Cache deleted for {key}")
        else:
            logger.info(f"No cache found for {key}")

    def get_info_from_tmdb(self, query_dict: dict, year_deviation: int = 0) -> tuple:
        """Get TV/Movie name from tmdb"""

        search_func = (
            self.tmdb_search.movies if self.is_movie else self.tmdb_search.tv_shows
        )

        query_title = query_dict["query"]
        query_year = (
            query_dict.get("year", datetime.date.today().year)
            if self.is_movie
            else query_dict.get("first_air_date_year", datetime.date.today().year)
        )
        tmdb_id = None
        retry = 0
        while retry < 3:
            try:
                while year_deviation >= 0:
                    res = (
                        search_func({"query": query_title, "year": query_year})
                        if self.is_movie
                        else search_func(
                            {"query": query_title, "first_air_date_year": query_year}
                        )
                    )
                    if not res:
                        logger.info(f"No result for {query_title}, exit")
                        year_deviation -= 1
                        if year_deviation > 0:
                            query_year -= 1
                        continue
                    else:
                        for rslt in res:
                            title = rslt.title if self.is_movie else rslt.name
                            original_title = (
                                rslt.original_title
                                if self.is_movie
                                else rslt.original_name
                            )
                            logger.debug(f"{rslt=}")
                            if query_title in [title, original_title] or len(res) == 1:
                                tmdb_id = str(rslt.id)

                                logger.info(f"Got tmdb_id for {query_title}: {tmdb_id}")
                                break
                        break
                break
            except Exception as e:
                logger.exception(e)
                retry += 1
                continue
        if tmdb_id is None:
            logger.error(f"Failed to get tmdb_id for {query_title}")
            return {}
        tmdb_info = self.get_info_from_tmdb_by_id(tmdb_id)
        tmdb_info.update({"tmdb_id": tmdb_id})

        return tmdb_info

    def get_info_from_tmdb_by_id(self, tmdb_id: str) -> dict:
        """Get movies/shows' details using tmdb_id"""
        tmdb_name = ""
        tmdb_id = str(tmdb_id)
        # 先从缓存中读取
        info = self.get_cache_by_key(tmdb_id)
        if info:
            logger.info(f"Cache hit for {tmdb_id}")
            return info

        details = self.tmdb_media.details(tmdb_id)
        date = details.release_date if self.is_movie else details.first_air_date
        date_list = date.split("-")
        if len(date_list) > 1:
            year, month = date_list[:2]
        else:
            year, month = date_list[0], None
        if not year or not month:
            raise Exception("Not found first_air_date")
        original_title = (
            details.original_title if self.is_movie else details.original_name
        )
        title = details.title if self.is_movie else details.name
        contries = "&".join(sorted(details.origin_country))
        if details.original_language == "zh":
            tmdb_name = f"{original_title} ({year}) {{tmdb-{tmdb_id}}}"
        else:
            if title == original_title:
                translations = details.get("translations").get("translations")
                for translation in translations:
                    if (
                        translation.get("iso_3166_1") == "SG"
                        and translation.get("iso_639_1") == "zh"
                    ):
                        title = (
                            translation.get("data")["name"]
                            if not self.is_movie
                            else translation.get("data")["title"]
                        )
                        break
            tmdb_name = (
                f"[{title}] {original_title} ({year}) {{tmdb-{tmdb_id}}}"
                if title and title != original_title
                else f"{original_title} ({year}) {{tmdb-{tmdb_id}}}"
            )
            if is_filename_length_gt_255(tmdb_name):
                tmdb_name = f"{original_title} ({year}) {{tmdb-{tmdb_id}}}"
        is_anime, is_documentary, is_variety = False, False, False
        is_nc17 = False
        # 判断电视剧分类
        if not self.is_movie:
            # 通过类型判断
            show_type = details.type
            if show_type == "Documentary":
                is_documentary = True
            if show_type in ["Talk Show", "Reality"]:
                is_variety = True
            # 通过 genre 分类判断
            genres = [int(genre.get("id")) for genre in details.genres]
            for genre_id in genres:
                if genre_id == 16:
                    is_anime = True
                    break
                # 10764-真人秀，10767-脱口秀
                if genre_id in [10764, 10767]:
                    is_variety = True
                    break
                # 99-纪录片, 18-剧情
                if genre_id == 99 and 18 not in genres:
                    is_documentary = True
                    break
        # 判断是否为 nc17
        else:
            is_nc17 = self.get_movie_certification(tmdb_id)

        info = {
            "tmdb_name": tmdb_name.replace("/", "／"),
            "title": title,
            "year": year,
            "month": month,
            "country": contries,
            "is_anime": is_anime,
            "is_documentary": is_documentary,
            "is_variety": is_variety,
            "is_nc17": is_nc17,
        }
        self.write_cache_by_key(tmdb_id, info)
        return info

    def get_movie_certification(self, tmdb_id: str) -> bool:
        """Get movie's certifacation"""
        is_nc17 = False
        _ = {
            "US": "NC-17",
            "HK": "III",
            "JP": "R18+",
        }
        try:
            rslts = self.tmdb_media.release_dates(tmdb_id).get("results")
        except Exception as e:
            logger.exception(f"Getting certifacation of {tmdb_id} failed")
            logger.exception(e)
            return is_nc17
        iso_3166_1_list = [__.get("iso_3166_1") for __ in rslts]
        for _iso, _cert in _.items():
            # 没有定义的国家的分级信息，则直接跳过
            # 以美国分级为主
            if _iso not in iso_3166_1_list or (
                "US" in iso_3166_1_list and _iso != "US"
            ):
                continue
            index = iso_3166_1_list.index(_iso)
            rslt = rslts[index]
            release_dates = rslt.get("release_dates")
            for release_date in release_dates:
                certification = release_date.get("certification")
                logger.debug(
                    f"Getting certification of {tmdb_id} succeed: {certification}"
                )
                if certification == _cert:
                    return True

        return is_nc17


if __name__ == "__main__":
    # 测试单例模式
    tmdb_movie_1 = TMDB(movie=True)
    tmdb_movie_2 = TMDB(movie=True)
    tmdb_tv_1 = TMDB(movie=False)
    tmdb_tv_2 = TMDB(movie=False)

    # 验证同类型的实例是同一个对象
    print(f"tmdb_movie_1 is tmdb_movie_2: {tmdb_movie_1 is tmdb_movie_2}")  # True
    print(f"tmdb_tv_1 is tmdb_tv_2: {tmdb_tv_1 is tmdb_tv_2}")  # True
    print(f"tmdb_movie_1 is tmdb_tv_1: {tmdb_movie_1 is tmdb_tv_1}")  # False

    # 测试功能
    print(tmdb_movie_1.get_info_from_tmdb_by_id(tmdb_id=27205))
    print(tmdb_tv_1.get_info_from_tmdb_by_id(tmdb_id=64197))
