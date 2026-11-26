import email.utils
import json
import logging
import random
import string
import time

import requests
from requests.adapters import HTTPAdapter

from . import constants as C
from . import upstream as U
from .errors import ApiError

log = logging.getLogger("l_toolkit")


def build_session():
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_retry_after(value, now=None):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return float(int(text))
    try:
        moment = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment is None:
        return None
    current = time.time() if now is None else now
    return max(0.0, moment.timestamp() - current)


class UpstreamClient:
    def __init__(
        self,
        session=None,
        country=C.DEFAULT_COUNTRY,
        platform=U.DEFAULT_PLATFORM,
        app_version=U.DEFAULT_APP_VERSION,
        singbox_version=U.DEFAULT_SINGBOX_VERSION,
        locale=U.DEFAULT_LOCALE,
        time_zone=U.DEFAULT_TIME_ZONE,
        user_agent=C.DEFAULT_USER_AGENT,
        account_url=U.ACCOUNT_URL,
        config_url=U.CONFIG_URL,
        rng=None,
        sleep=time.sleep,
        clock=time.time,
    ):
        self.session = session if session is not None else build_session()
        self.country = country
        self.platform = platform
        self.app_version = app_version
        self.singbox_version = singbox_version
        self.locale = locale
        self.time_zone = time_zone
        self.user_agent = user_agent
        self.account_url = account_url.rstrip("/")
        self.config_url = config_url.rstrip("/")
        self.rng = rng if rng is not None else random.SystemRandom()
        self.sleep = sleep
        self.clock = clock

    def _noise(self):
        size = self.rng.randrange(0, 300)
        return "".join(self.rng.choice(string.ascii_lowercase) for _ in range(size))

    def _headers(self, device_id, user_id=0):
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            U.HEADER_APP_VERSION: self.app_version,
            U.HEADER_VERSION: self.app_version,
            U.HEADER_PLATFORM: self.platform,
            U.HEADER_APP_NAME: U.APP_NAME,
            U.HEADER_DEVICE_ID: device_id,
            U.HEADER_NOISE: self._noise(),
        }
        if user_id > 0:
            headers[U.HEADER_USER_ID] = str(user_id)
        if self.time_zone:
            headers[U.HEADER_TIME_ZONE] = self.time_zone
        if self.country:
            headers[U.HEADER_CLIENT_COUNTRY] = self.country
        return headers

    def _backoff(self, attempt):
        delay = C.RETRY_BASE_DELAY * (2 ** (attempt - 1)) + self.rng.uniform(0, C.RETRY_JITTER)
        return min(C.RETRY_MAX_DELAY, delay)

    def _delay_after_status(self, response, attempt):
        header = None
        headers = getattr(response, "headers", None)
        if headers:
            header = headers.get("Retry-After")
        waited = parse_retry_after(header, now=self.clock())
        if waited is None:
            return self._backoff(attempt)
        if waited > C.RETRY_AFTER_CAP:
            return None
        return waited + self.rng.uniform(0, 1)

    def _post(self, url, headers, body, label, idempotent):
        attempts = C.CONFIG_ATTEMPTS if idempotent else 1
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.session.post(
                    url,
                    headers=headers,
                    data=body,
                    timeout=(C.CONNECT_TIMEOUT, C.READ_TIMEOUT),
                )
            except requests.RequestException as exc:
                if attempt >= attempts:
                    raise ApiError("%s failed after %d attempt(s): %s" % (label, attempt, type(exc).__name__)) from exc
                delay = self._backoff(attempt)
                log.warning("%s failed (%s), retrying in %.0fs", label, type(exc).__name__, delay)
                self.sleep(delay)
                continue
            if response.status_code in C.RETRY_STATUSES and attempt < attempts:
                delay = self._delay_after_status(response, attempt)
                if delay is None:
                    raise ApiError(
                        "%s returned HTTP %d with a Retry-After above %.0fs, not waiting"
                        % (label, response.status_code, C.RETRY_AFTER_CAP),
                        response.status_code,
                    )
                log.warning("%s returned HTTP %d, retrying in %.0fs", label, response.status_code, delay)
                self.sleep(delay)
                continue
            return response

    @staticmethod
    def _status_error(label, response):
        message = "%s returned HTTP %d" % (label, response.status_code)
        headers = getattr(response, "headers", None)
        retry_after = headers.get("Retry-After") if headers else None
        if response.status_code == 429 and retry_after:
            message += " (Retry-After: %s)" % str(retry_after)[:40]
        return ApiError(message, response.status_code)

    def create_account(self, device_id):
        url = self.account_url + U.ACCOUNT_PATH
        label = "account creation"
        response = self._post(url, self._headers(device_id), None, label, idempotent=False)
        if response.status_code != 200:
            raise self._status_error(label, response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError("%s returned invalid JSON" % label) from exc
        if not isinstance(data, dict):
            raise ApiError("%s returned an unexpected payload" % label)
        if data.get("error"):
            raise ApiError("%s reported an error" % label)
        user_id = data.get(U.ACCOUNT_FIELD_USER_ID)
        token = data.get(U.ACCOUNT_FIELD_TOKEN)
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ApiError("%s response has no valid user id" % label)
        if not isinstance(token, str) or not token:
            raise ApiError("%s response has no token" % label)
        return user_id, token

    def _config_body(self, state):
        body = {
            "device_id": state.device_id,
            "singbox_version": self.singbox_version,
            "platform": self.platform,
            "app_name": U.APP_NAME,
            "user_id": str(state.user_id),
            "pro_token": state.token,
            "backend": U.BACKEND,
            "locale": self.locale,
            "protocols": list(U.ADVERTISED_PROTOCOLS),
        }
        if U.ADVERTISED_CAPABILITIES:
            body["capabilities"] = list(U.ADVERTISED_CAPABILITIES)
        return json.dumps(body).encode("utf-8")

    def fetch_config(self, state):
        if not state.has_user:
            raise ApiError("cannot fetch the configuration without an account")
        url = self.config_url + U.CONFIG_PATH
        label = "configuration request"
        headers = self._headers(state.device_id, state.user_id)
        headers["Content-Type"] = "application/json"
        headers["Cache-Control"] = "no-cache"
        response = self._post(url, headers, self._config_body(state), label, idempotent=True)
        if response.status_code != 200:
            raise self._status_error(label, response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError("%s returned invalid JSON" % label) from exc
        if not isinstance(data, dict):
            raise ApiError("%s returned an unexpected payload" % label)
        return data
