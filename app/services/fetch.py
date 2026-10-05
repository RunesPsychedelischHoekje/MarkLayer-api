"""Download a file for /v1/inspect?url=..., without letting callers reach our private network.

LESSON (SSRF): a server that fetches URLs for strangers can be pointed at addresses only it can
reach (127.0.0.1, cloud metadata at 169.254.169.254, internal services). We resolve every host,
refuse anything that isn't a public address, and re-check each redirect hop ourselves.
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from app.errors import ApiError

MAX_REDIRECTS = 3


def _check_public(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ApiError(422, "invalid_url", "Only absolute http(s) URLs are supported.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ApiError(422, "unresolvable_url", f"Could not resolve host {parts.hostname}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ApiError(422, "forbidden_url", "URLs pointing to private or reserved addresses are not allowed.")


def fetch(url: str, max_bytes: int, timeout_s: float, user_agent: str) -> bytes:
    with httpx.Client(timeout=timeout_s, follow_redirects=False, headers={"User-Agent": user_agent}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _check_public(url)
            try:
                with client.stream("GET", url) as resp:
                    if resp.is_redirect:
                        url = urljoin(url, resp.headers.get("location", ""))
                        continue
                    if resp.status_code != 200:
                        raise ApiError(422, "fetch_failed", f"The URL returned HTTP {resp.status_code}.")
                    if int(resp.headers.get("content-length") or 0) > max_bytes:
                        raise ApiError(413, "file_too_large", f"The file is larger than {max_bytes // 2**20} MB.")
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            raise ApiError(413, "file_too_large", f"The file is larger than {max_bytes // 2**20} MB.")
                    return bytes(buf)
            except httpx.HTTPError as exc:
                raise ApiError(422, "fetch_failed", f"Could not download the URL ({type(exc).__name__}).") from exc
    raise ApiError(422, "fetch_failed", "Too many redirects.")
