"""See https://github.com/zKillboard/zKillboard/wiki/API-(Killmails)
"""
import ssl
import typing
import urllib
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import ssl
import sys
import base64
import hashlib
import secrets
import time
import datetime
from dateutil.parser import parse as parsedate


class ZKillboardClient:
    class TLSAdapter(requests.adapters.HTTPAdapter):
        def __init__(self, ssl_options=0, **kwargs):
            self.ssl_options = ssl_options
            super(ZKillboardClient.TLSAdapter, self).__init__(**kwargs)

        def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
            ctx = ssl.create_default_context()
            ctx.maximum_version = ssl.TLSVersion.TLSv1_2
            ctx.options = self.ssl_options
            self.poolmanager = PoolManager(
                num_pools=connections,
                maxsize=maxsize,
                block=block,
                ssl_context=ctx,
                **pool_kwargs)

    def __init__(self,
                 keep_alive: bool,
                 debug: bool = False,
                 logger: bool = True,
                 user_agent: typing.Optional[str] = None,
                 restrict_tls13: bool = False):
        # настройки клиента
        self.__attempts_to_reconnect: int = 5
        self.__debug: bool = debug
        self.__logger: bool = logger
        self.__server_name: str = 'zkillboard.com'
        # можно указать User-Agent в заголовках запросов
        self.__user_agent: typing.Optional[str] = user_agent
        # данные-состояния, которые были получены во время обработки http-запросов
        self.__last_modified: typing.Optional[datetime.datetime] = None
        # резервируем session-объект, для того чтобы не заниматься переподключениями, а пользоваться keep-alive
        self.__keep_alive: bool = keep_alive
        self.__restrict_tls13: bool = restrict_tls13
        self.__session: typing.Optional[requests.Session] = None
        self.__adapter: typing.Optional[ZKillboardClient.TLSAdapter] = None

    def __del__(self):
        # закрываем сессию
        if self.__session is not None:
            del self.__session
        if self.__adapter is not None:
            del self.__adapter

    @property
    def debug(self) -> bool:
        """ flag which says that we are in debug mode
        """
        return self.__debug

    def enable_debug(self) -> None:
        self.__debug = True

    def disable_debug(self) -> None:
        self.__debug = False

    @property
    def logger(self) -> bool:
        """ flag which says that we are in logger mode
        """
        return self.__logger

    def enable_logger(self) -> None:
        self.__logger = True

    def disable_logger(self) -> None:
        self.__logger = False

    @property
    def user_agent(self) -> str:
        """ User-Agent which used in http requests to ZKB Servers
        """
        return self.__user_agent

    def setup_user_agent(self, user_agent: str) -> None:
        """ configures User-Agent which used in http requests to CCP Servers, foe example:
        'https://github.com/Qandra-Si/ Maintainer: Qandra Si qandra.si@gmail.com'

        :param user_agent: format recomendation - '<project_url> Maintainer: <maintainer_name> <maintainer_email>'
        """
        self.__user_agent = user_agent

    @property
    def last_modified(self) -> typing.Optional[datetime.datetime]:
        """ Last-Modified property from http header
        :returns: :class:`datetime.datetime`
        """
        return self.__last_modified

    def __establish(self) -> requests.Session:
        if self.__session is not None:
            del self.__session
        if self.__adapter is not None:
            del self.__adapter
        if self.__logger:
            print("starting new HTTPS connection: {}:443".format(self.__server_name))
        self.__session = requests.Session()
        if self.__restrict_tls13:
            self.__adapter = ZKillboardClient.TLSAdapter(ssl.OP_NO_TLSv1_3)
            self.__session.mount("https://", self.__adapter)
        return self.__session

    def __keep_connection(self) -> requests.Session:
        if self.__session is None:
            self.__session = requests.Session()
            if self.__restrict_tls13:
                self.__adapter = ZKillboardClient.TLSAdapter(ssl.OP_NO_TLSv1_3)
                self.__session.mount("https://", self.__adapter)
        return self.__session

    def send_zkb_request_http(self, uri: str, last_modified: typing.Optional[str], body=None) -> requests.Response:
        headers: typing.Dict[str, str] = {}
        if not (last_modified is None) and (body is None):
            headers.update({"If-Modified-Since": last_modified})
        if self.__user_agent:
            headers.update({"User-Agent": self.__user_agent})

        res: typing.Optional[requests.Response] = None
        http_connection_times: int = 0
        self.__last_modified: typing.Optional[datetime.datetime] = None
        requests_get_times: int = 0
        timeout_connect: int = 3
        timeout_read: int = 7
        while True:
            try:
                proxy_error_times: int = 0
                throttle_error_times: int = 0
                while True:
                    if body is None:
                        requests_get_finished: bool = False
                        while not requests_get_finished:
                            try:
                                # при попытке загружать много страниц, может зависать метод get, и висеть бесконечно -
                                # добавил таймауты на переподключения, которые
                                # подобрал экспериментально, см. также https://ru.stackoverflow.com/a/1189363
                                requests_get_times += 1
                                if self.__keep_alive:
                                    # s может меняться, важно переиспользовать self.__session
                                    s: requests.Session = self.__keep_connection()
                                    res = s.get(uri, headers=headers, timeout=(timeout_connect, timeout_read))
                                else:
                                    res = requests.get(uri, headers=headers, timeout=(timeout_connect, timeout_read))
                            except (requests.ConnectionError, requests.Timeout):
                                continue
                            else:
                                requests_get_finished = True
                        if self.__debug:
                            print("\nMade GET request to {} with headers: "
                                  "{}\nAnd the answer {} was received with "
                                  "headers {} and encoding {}".
                                  format(uri,
                                         res.request.headers,
                                         res.status_code,
                                         res.headers,
                                         res.encoding))
                    else:
                        headers.update({"Content-Type": "application/json"})
                        if self.__keep_alive:
                            # s может меняться, важно переиспользовать self.__session
                            s: requests.Session = self.__keep_connection()
                            res = s.post(uri, data=body, headers=headers)
                        else:
                            res = requests.post(uri, data=body, headers=headers)
                        if self.__debug:
                            print("\nMade POST request to {} with data {} and headers: "
                                  "{}\nAnd the answer {} was received with "
                                  "headers {} and encoding {}".
                                  format(uri,
                                         body,
                                         res.request.headers,
                                         res.status_code,
                                         res.headers,
                                         res.encoding))
                    # вывод отладочной информации : код, uri, last-modified
                    if self.__logger:
                        log_line = str(res.status_code) + " " + uri[27:]
                        if 'Last-Modified' in res.headers:
                            url_time = str(res.headers['Last-Modified'])
                            self.__last_modified = parsedate(url_time)
                            log_line += " " + url_time[17:-4]
                        if requests_get_times > 1:
                            log_line += " (" + str(requests_get_times) + ")"
                        print(log_line)
                    if (res.status_code in [502, 504]) and (proxy_error_times < self.__attempts_to_reconnect):
                        # пять раз пытаемся повторить отправку сломанного запроса (часто случается
                        # при подключении через 3G-модем)
                        proxy_error_times = proxy_error_times + 1
                        continue
                    elif (res.status_code in [503]) and (proxy_error_times < self.__attempts_to_reconnect):
                        # может падать интерфейс к серверу
                        print(res.json())
                        # 503 Server Error: service unavailable for url: ...
                        # {'error': 'The datasource ... is temporarily unavailable'}
                        proxy_error_times = proxy_error_times + 1
                        time.sleep(2*proxy_error_times)
                        continue
                    elif (res.status_code in [520]) and (throttle_error_times < self.__attempts_to_reconnect):
                        # возможная ситация: сервер детектирует спам-запросы (на гитхабе написано, что порог
                        # срабатывания находится около 20 запросов в 10 секунд от одного персонажа), см. подробнее
                        # здесь: https://github.com/esi/esi-issues/issues/636#issuecomment-342150532
                        print(res.json())
                        # 520 Server Error: status code 520 for url: ...
                        # {'error': 'ConStopSpamming, details: {"remainingTime": 12038505}'}
                        throttle_error_times = throttle_error_times + 1
                        time.sleep(5)
                        continue
                    res.raise_for_status()
                    break
            except requests.exceptions.ConnectionError as err:
                print(err)
                # возможная ситуация: проблемы с доступом к серверам, возникает следующая ошибка:
                # HTTPSConnectionPool(host='...', port=443):
                # Max retries exceeded with url: ...
                # Caused by NewConnectionError('<urllib3.connection.VerifiedHTTPSConnection>:
                # Failed to establish a new connection: [Errno -3] Temporary failure in name resolution')
                if http_connection_times < self.__attempts_to_reconnect:
                    # повторям попытку подключения спустя секунду
                    http_connection_times += 1
                    time.sleep(1)
                    continue
                raise
            except requests.exceptions.HTTPError as err:
                # сюда попадают 403 и 404 ошибки, и это нормально
                print(err)
                print(res.json())
                raise
            except:
                print(sys.exc_info())
                raise
            break
        return res

    def send_zkb_request_json(self, uri: str, last_modified: typing.Optional[str], body=None):
        return self.send_zkb_request_http(uri, last_modified, body).json()
