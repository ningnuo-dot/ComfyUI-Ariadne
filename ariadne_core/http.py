"""统一 HTTP 出站封装：超时、错误中文详注（画布插件 net.ts 的 Python 版）。"""
from __future__ import annotations

import requests


def request_json(
    method: str,
    url: str,
    *,
    phase: str,
    headers: dict | None = None,
    json_body: dict | None = None,
    data=None,
    timeout: int = 120,
):
    """发请求并解析 JSON；失败时抛出带阶段/URL/响应摘要的中文错误。"""
    try:
        response = requests.request(
            method, url, headers=headers, json=json_body, data=data, timeout=timeout
        )
    except requests.RequestException as error:
        raise RuntimeError(f"{phase}网络请求失败：{error}（URL: {url}）") from error
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response, payload


def request_bytes(method: str, url: str, *, phase: str, timeout: int = 600) -> bytes:
    """下载二进制（成片落盘用）；失败抛中文错误。"""
    try:
        response = requests.get(url, timeout=timeout, stream=True)
    except requests.RequestException as error:
        raise RuntimeError(f"{phase}下载失败：{error}（URL: {url}）") from error
    if response.status_code != 200:
        raise RuntimeError(f"{phase}下载失败（HTTP {response.status_code}）：{url}")
    return response.content
