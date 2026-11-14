"""Bounded public-media preflight checks used before human review."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException


_MAX_REDIRECTS = 3
_TIMEOUT_SECONDS = 8.0


def _public_https_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("網址必須是沒有帳密的公開 HTTPS 網址")
    return url


def _assert_public_host(url: str) -> None:
    hostname = urlparse(url).hostname
    if not hostname:
        raise ValueError("網址缺少主機名稱")
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("無法解析網址主機名稱") from exc
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global:
            raise ValueError("網址不可指向本機、內網或保留網路")


def validate_public_media_url(url: str, *, expected_type: str) -> None:
    """Confirm one public URL is reachable and advertises the expected media type.

    Redirects are handled one at a time so every destination receives the same
    HTTPS and public-network checks. Only response headers are read; no media
    file is downloaded during review submission.
    """
    current_url = _public_https_url(url)
    headers = {"User-Agent": "NTUMaker-Media-Preflight/1.0", "Range": "bytes=0-0"}
    with httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            _assert_public_host(current_url)
            response = client.head(current_url, headers=headers)
            if response.status_code in {405, 501}:
                # Some CDNs disallow HEAD. Request only the first byte instead
                # of downloading a potentially large video file.
                with client.stream("GET", current_url, headers=headers) as streamed:
                    status_code, response_headers = streamed.status_code, streamed.headers
            else:
                status_code, response_headers = response.status_code, response.headers
            if status_code in {301, 302, 303, 307, 308}:
                location = response_headers.get("location")
                if not location:
                    raise ValueError("網址重新導向缺少目的地")
                current_url = _public_https_url(urljoin(current_url, location))
                continue
            if not 200 <= status_code < 300:
                raise ValueError(f"網址回應 HTTP {status_code}")
            content_type = response_headers.get("content-type", "").split(";", 1)[0].lower()
            if not content_type.startswith(f"{expected_type}/"):
                raise ValueError(
                    f"網址回傳 {content_type or '未知類型'}，不是可用的 {expected_type} 素材"
                )
            return
    raise ValueError("網址重新導向次數過多")


def validate_action_media(action) -> None:
    """Validate all URLs required by a draft before it can enter review."""
    payload = action.payload
    post_format = payload.get("post_format", "image")
    checks: list[tuple[str, str]] = []
    if post_format != "reel":
        checks.extend((url, "image") for url in payload.get("image_urls", []))
    if post_format != "image":
        checks.extend((url, "video") for url in payload.get("video_urls", []))

    for url, expected_type in checks:
        try:
            validate_public_media_url(str(url), expected_type=expected_type)
        except (ValueError, httpx.HTTPError) as exc:
            kind = "圖片" if expected_type == "image" else "影片"
            raise HTTPException(422, f"{kind}網址無法公開讀取：{url}（{exc}）") from exc
