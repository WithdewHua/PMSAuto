#!/usr/local/bin/env python

import logging
import datetime

from tmdbv3api import TMDb, Search, TV, Movie
from settings import TMDB_API_KEY


class TMDB():
    def __init__(self, api_key: str=TMDB_API_KEY, language: str="zh", movie: bool=False) -> None:
        self.tmdb = TMDb()
        self.tmdb.api_key = api_key
        self.tmdb.language = language
        self.is_movie = movie
        self.tmdb_search = Search()
        if self.is_movie:
            self.tmdb_media = Movie()
        else:
            self.tmdb_media = TV()
        self.tmdb_id = None
        
    def get_name_from_tmdb(self, query_dict: dict, year_deviation: int=0) -> str:
        """Get TV/Movie name from tmdb"""

        search_func = self.tmdb_search.movies if self.is_movie else self.tmdb_search.tv_shows

        query_title = query_dict["query"]
        query_year = query_dict.get("year", datetime.date.today().year) if self.is_movie else query_dict.get("first_air_date_year", datetime.date.today().year)

        retry = 0
        name = ""
        while retry < 3: 
            try:
                while year_deviation >= 0:
                    res = search_func({"query": query_title, "year": query_year}) if self.is_movie else search_func({"query": query_title, "first_air_date_year": query_year})
                    if not res:
                        logging.info(f"No result for {query_title}, exit")
                        year_deviation -= 1
                        query_year -= 1
                        continue
                    else:
                        for rslt in res:
                            date = rslt.release_date if self.is_movie else rslt.first_air_date
                            year = date.split("-")[0]
                            title = rslt.title if self.is_movie else rslt.name
                            original_title = rslt.original_title if self.is_movie else rslt.original_name
                            logging.debug(rslt)
                            if query_title in [title, original_title] or len(res) == 1:
                                if rslt.original_language == "zh":
                                    name = f"{original_title} ({year}) {{tmdb-{rslt.id}}}"
                                else:
                                    # 不存在 zh-CN 翻译的情况下
                                    if title == original_title:
                                        # 获取详细信息
                                        media = self.tmdb_media
                                        media_details = media.details(rslt.id)
                                        translations = media_details.get("translations").get("translations")
                                        for translation in translations:
                                            if translation.get("iso_3166_1") == "SG" and translation.get("iso_639_1") == "zh":
                                                title = translation.get("data")["name"]
                                                break

                                    name = f"[{title}] {original_title} ({year}) {{tmdb-{rslt.id}}}" if title != original_title else f"{original_title} ({year}) {{tmdb-{rslt.id}}}" 
                                    self.tmdb_id = rslt.id

                                logging.info(f"Renaming {query_title} to {name}")
                                break
                        break
                break
            except Exception as e:
                logging.error(f"Exception happens: {e}")
                retry += 1
                continue
        return name

    def get_movie_certification(self) -> bool:
        """Get movie's certifacation"""
        is_nc17 = False
        try:
            rslts = self.tmdb_media.release_dates(self.tmdb_id).get("results")
        except Exception:
            return is_nc17
        for rslt in rslts:
            release_dates = rslt.get("release_dates")
            for release_date in release_dates:
                certifacation = release_date.get("certifacation")
                if certifacation in ["18", "M/18", "NC-17", "III"]:
                    is_nc17 = True
                    break
            if is_nc17:
                break

        return is_nc17

