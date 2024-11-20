# -*- encoding: utf-8 -*-
import typing
import json
import os.path
from pathlib import Path
import requests
import datetime
from dateutil.parser import parse as parsedate

from .error import ZKillboardClientError
from .zkillboard_client import ZKillboardClient


class ZKillboardInterface:
    def __init__(self, client: ZKillboardClient, cache_dir: str, offline_mode: bool = False):
        self.__server_url: str = "https://zkillboard.com/api/"
        self.__offline_mode: bool = offline_mode
        self.__cache_dir: str = cache_dir  # {tmp_dir}/.zkb_cache/
        self.setup_cache_dir(cache_dir)
        self.__is_last_data_updated: bool = False
        self.__last_modified: typing.Optional[datetime.datetime] = None
        if not isinstance(client, ZKillboardClient):
            raise ZKillboardClientError("You should use ZKillboardClient to configure interface")
        self.__client: ZKillboardClient = client

    @property
    def client(self) -> ZKillboardClient:
        """ ZKillboard https client implementation
        """
        return self.__client

    @property
    def server_url(self) -> str:
        """ url to ZKillboard interface (server)
        """
        return self.__server_url

    @property
    def cache_dir(self) -> str:
        """ path to directory with cache files
        """
        return self.__cache_dir

    def setup_cache_dir(self, cache_dir: str) -> None:
        """ configures path to directory where zkb/http cache files stored
        """
        if cache_dir[-1:] == '/':
            cache_dir = cache_dir[:-1]
        self.__cache_dir = cache_dir
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    @property
    def offline_mode(self) -> bool:
        """ flag which says that we are working offline, so zkillboard_interface will read data from file system
        (to optimize interaction with zkb servers)
        """
        return self.__offline_mode

    @property
    def online_mode(self) -> bool:
        """ flag which says that we are working offline, so zkillboard_interface will download & save data
        from zkb servers
        """
        return not self.__offline_mode

    @property
    def last_modified(self) -> typing.Optional[datetime.datetime]:
        """ Last-Modified property from http header
        :returns: :class:`datetime.datetime`
        """
        return self.__last_modified

    def __get_f_name(self, url: str) -> str:
        """ converts urls to filename to store it in filesystem, for example:
        url=/corporationID/787611831/
        filename=.cache_corporationID_787611831.json

        :param url: ZKillboard interface url
        :return: patched url to name of file
        """
        if url[-1:] == '/':
            url = url[:-1]
        url = url.replace('/', '_')
        url = url.replace('=', '-')
        url = url.replace('?', '')
        url = url.replace('&', '.')
        f_name: str = '{dir}/.cache_{nm}.json'.format(dir=self.__cache_dir, nm=url)
        return f_name

    @staticmethod
    def __get_cached_headers(data) -> typing.Dict[str, str]:
        """ gets http response headers and converts it data stored on cache files
        """
        cached_headers: typing.Dict[str, str] = {}
        if "Date" in data.headers:
            cached_headers.update({"date": data.headers["Date"]})
        if "Expires" in data.headers:
            cached_headers.update({"expires": data.headers["Expires"]})
        if "Last-Modified" in data.headers:
            cached_headers.update({"last-modified": data.headers["Last-Modified"]})
        return cached_headers

    def __dump_cache_into_file(self, url: str, data_headers, data_json) -> None:
        """ dumps data received from zkb servers into cache files
        """
        f_name: str = self.__get_f_name(url)
        cache: typing.Dict[str, typing.Any] = {"headers": data_headers, "json": data_json}
        s: str = json.dumps(cache, indent=1, sort_keys=False)
        with open(f_name, 'wt+', encoding='utf8') as f:
            try:
                f.write(s)
            finally:
                f.close()
        del s
        del cache
        del f_name

    def __take_cache_from_file(self, url: str) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """ reads cache data early received from CCP Servers
        """
        f_name: str = self.__get_f_name(url)
        if os.path.isfile(f_name):
            with open(f_name, 'rt', encoding='utf8') as f:
                try:
                    s: str = f.read()
                    cache_data: typing.Dict[str, typing.Any] = (json.loads(s))
                    return cache_data
                finally:
                    f.close()
        return None

    @staticmethod
    def __get_merged_pages(cached_data: typing.Dict[str, typing.Any]) -> typing.Optional[typing.List[typing.Any]]:
        if "json" in cached_data:
            merged: typing.List[typing.Any] = []
            for p in cached_data["json"]:
                merged += p
            return merged
        return None

    @staticmethod
    def __esi_raise_for_status(code: int, message: str) -> None:
        """ generates HTTPError to emulate 403, 404 exceptions when working in offline mode
        """
        rsp = requests.Response()
        rsp.status_code = code
        raise requests.exceptions.HTTPError(message, response=rsp)

    def get_zkb_data(self, url: str, body=None, fully_trust_cache: bool = False):
        """ performs ESI GET/POST-requests in online mode,
        or returns early retrieved data when working on offline mode

        :param url: ZKillboard Interface ulr
        :param body: parameters to send to ZKB API with POST request
        :param fully_trust_cache: if cache exists, trust it! (filesystem cache priority)
        """
        cached_data: typing.Optional[typing.Dict[str, typing.Any]] = self.__take_cache_from_file(url)
        self.__is_last_data_updated = False
        self.__last_modified = None
        if not self.__offline_mode and fully_trust_cache and not (cached_data is None) and ("json" in cached_data):
            # иногда возникает ситуация, когда данные по указанному url не закачались (упали с ошибкой), и так
            # и будут вечно восстанавливаться из кеша, - все ошибки обновляем в online-режиме!
            if not ("Http-Error" in cached_data["headers"]):
                url_time: typing.Optional[str] = cached_data["headers"].get("last-modified", None)
                if not (url_time is None):
                    self.__last_modified = parsedate(url_time)
                return cached_data.get("json", None)
        if self.__offline_mode:
            if cached_data is None:
                return None
            # Offline mode (выдаёт ранее сохранённый кэшированный набор json-данных)
            if "Http-Error" in cached_data["headers"]:
                code: int = int(cached_data["headers"]["Http-Error"])
                self.__esi_raise_for_status(
                    code,
                    '{} Client Error: Offline-cache for url: {}'.format(code, url))
            return cached_data.get("json", None)
        else:
            # Online mode (отправляем запрос, сохраняем кеш данных, перепроверяем по last-modified обновления)
            data_path: str = f"{self.server_url}{url}"
            # см. рекомендации по программированию тут
            # https://github.com/zKillboard/zKillboard/wiki/API-(Killmails)
            # рекомендации по кешированию ответов от zkillboard см. здесь:
            # https://developers.cloudflare.com/cache/concepts/cache-responses/
            if not (cached_data is None) and \
                    ("headers" in cached_data) and \
                    (type(cached_data["headers"]) is dict):
                last_modified: typing.Optional[str] = cached_data["headers"].get("last-modified")
            else:
                last_modified: typing.Optional[str] = None
            try:
                data: requests.Response = self.__client.send_zkb_request_http(data_path, last_modified, body)
                if data.status_code == 304:
                    url_time = cached_data["headers"].get("last-modified", None)
                    if not (url_time is None):
                        self.__last_modified = parsedate(url_time)
                    return cached_data.get("json", None)
                else:
                    self.__dump_cache_into_file(url, self.__get_cached_headers(data), data.json())
                    self.__is_last_data_updated = True
                    self.__last_modified = self.__client.last_modified
                    return data.json()
            except requests.exceptions.HTTPError as err:
                status_code = err.response.status_code
                if status_code == 403:  # 403-ответ для индикации запретов доступа
                    # сохраняем информацию в кеше и выходим с тем же кодом ошибки
                    self.__dump_cache_into_file(url, {"Http-Error": 403}, None)
                    raise
                elif status_code == 404:  # 404-ответ для индикации "нет данных"
                    # сохраняем информацию в кеше и выходим с тем же кодом ошибки
                    self.__dump_cache_into_file(url, {"Http-Error": 404}, None)
                    raise
            except:
                raise
