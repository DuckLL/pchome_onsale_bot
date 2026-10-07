"""PChome 24h product API."""

import logging
import re
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

API = "https://ecapi.pchome.com.tw/ecshop/prodapi/v2/prod/{pid}&fields=Name,Price&_callback=."
# PChome answers bare scripted requests with errors; a browser UA and a pause
# before every call is what has kept it working since 2023.
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) "
                         "Gecko/20100101 Firefox/140.0"}
ATTEMPTS = 5
PAUSE = 1.0

PID_RE = re.compile(r"[A-Z0-9]{6}-[A-Z0-9]{9}")
URL_RE = re.compile(r"https://24h\.pchome\.com\.tw/prod/([A-Z0-9]{6}-[A-Z0-9]{9})")


def prod_url(pid: str) -> str:
    return f"https://24h.pchome.com.tw/prod/{pid}"


@dataclass(frozen=True)
class Product:
    pid: str
    name: str
    price: int


def fetch(pid: str, *, client: httpx.Client | None = None, sleep=time.sleep) -> Product | None:
    """Current name and price, or None if PChome does not return the product.

    None covers both "delisted" (PChome answers 200 with `[]`) and "kept
    failing"; the caller counts either as an error and only gives up on a
    product after many hours of them.
    """
    own = client is None
    client = client or httpx.Client(headers=HEADERS, timeout=15)
    try:
        res = None
        for _ in range(ATTEMPTS):
            sleep(PAUSE)
            try:
                res = client.get(API.format(pid=pid))
            except httpx.HTTPError as e:
                log.warning("pchome %s: %s", pid, e)
                continue
            if res.status_code == 200:
                break
        if res is None or res.status_code != 200:
            log.warning("pchome %s: giving up (HTTP %s)", pid, res and res.status_code)
            return None
        try:
            data = res.json()
        except ValueError:
            log.warning("pchome %s: not JSON: %.100s", pid, res.text)
            return None
        item = data.get(f"{pid}-000") if isinstance(data, dict) else None
        if not item:
            log.info("pchome %s: not found", pid)
            return None
        return Product(pid, item["Name"], int(item["Price"]["P"]))
    finally:
        if own:
            client.close()
