#!/usr/local/bin/env python

import datetime

from tmdbv3api import TMDb, Search, TV, Movie
from settings import TMDB_API_KEY, LOG_LEVEL
from log import logger


class TMDB:
    def __init__(
        self,
        api_key: str = TMDB_API_KEY,
        language: str = "zh",
        movie: bool = False,
        log_level: str = LOG_LEVEL,
    ) -> None:
        self.tmdb = TMDb()
        self.tmdb.api_key = api_key
        self.tmdb.language = language
        if log_level == "DEBUG":
            self.tmdb.debug = True
        self.is_movie = movie
        self.tmdb_search = Search()
        if self.is_movie:
            self.tmdb_media = Movie()
        else:
            self.tmdb_media = TV()
        self.tmdb_id = None

    def get_name_from_tmdb(self, query_dict: dict, year_deviation: int = 0) -> str:
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

        retry = 0
        name = ""
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
                        query_year -= 1
                        continue
                    else:
                        for rslt in res:
                            date = (
                                rslt.release_date
                                if self.is_movie
                                else rslt.first_air_date
                            )
                            year = date.split("-")[0]
                            title = rslt.title if self.is_movie else rslt.name
                            original_title = (
                                rslt.original_title
                                if self.is_movie
                                else rslt.original_name
                            )
                            logger.debug(rslt)
                            if query_title in [title, original_title] or len(res) == 1:
                                if rslt.original_language == "zh":
                                    name = (
                                        f"{original_title} ({year}) {{tmdb-{rslt.id}}}"
                                    )
                                else:
                                    # 不存在 zh-CN 翻译的情况下
                                    if title == original_title:
                                        # 获取详细信息
                                        media = self.tmdb_media
                                        media_details = media.details(rslt.id)
                                        translations = media_details.get(
                                            "translations"
                                        ).get("translations")
                                        for translation in translations:
                                            if (
                                                translation.get("iso_3166_1") == "SG"
                                                and translation.get("iso_639_1") == "zh"
                                            ):
                                                title = (
                                                    translation.get("data")["name"]
                                                    if not self.is_movie
                                                    else translation.get("data")[
                                                        "title"
                                                    ]
                                                )
                                                break

                                    name = (
                                        f"[{title}] {original_title} ({year}) {{tmdb-{rslt.id}}}"
                                        if title != original_title
                                        else f"{original_title} ({year}) {{tmdb-{rslt.id}}}"
                                    )
                                    self.tmdb_id = rslt.id

                                logger.info(f"Renaming {query_title} to {name}")
                                break
                        break
                break
            except Exception as e:
                logger.error(f"Exception happens: {e}")
                retry += 1
                continue
        return name

    def get_name_from_tmdb_by_id(self, tmdb_id: str) -> str:
        tmdb_name = ""
        self.tmdb_id = tmdb_id
        details = self.tmdb_media.details(self.tmdb_id)
        date = details.release_date if self.is_movie else details.first_air_date
        year = date.split("-")[0]
        original_title = (
            details.original_title if self.is_movie else details.original_name
        )
        title = details.title if self.is_movie else details.name
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
                        title = translation.get("data")["name"]
                        break
            tmdb_name = (
                f"[{title}] {original_title} ({year}) {{tmdb-{self.tmdb_id}}}"
                if title != original_title
                else f"{original_title} ({year}) {{tmdb-{self.tmdb_id}}}"
            )

        return tmdb_name

    def get_movie_certification(self) -> bool:
        """Get movie's certifacation"""
        is_nc17 = False
        _ = {
            "US": "NC-17",
            "HK": "III",
            "JP": "R18+",
        }
        try:
            rslts = self.tmdb_media.release_dates(self.tmdb_id).get("results")
        except Exception:
            logger.exception(f"Getting certifacation of {self.tmdb_id} failed")
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
                    f"Getting certification of {self.tmdb_id} succeed: {certification}"
                )
                if certification == _cert:
                    return True

        return is_nc17
