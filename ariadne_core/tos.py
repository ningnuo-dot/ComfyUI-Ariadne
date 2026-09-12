"""轻量 TOS（火山对象存储）客户端：服务端直传 + 预签名 GET 给方舟抓取（桶保持私有）。

TOS 的 SigV4 是自家变体（画布插件 tos.ts 已实测并对照官方 @volcengine/tos-sdk）：
- 算法串 TOS4-HMAC-SHA256（非 AWS4-）；service=tos；scope 终端标识 request（非 aws4_request）
- 预签名 query 前缀 X-Tos-*，且额外带 X-Tos-Content-Sha256
- 参与签名的头 = host + 全部 x-tos-* 头
- 只支持虚拟主机风格（https://{bucket}.{endpoint}/{key}）
"""
from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from datetime import datetime, timezone

ALGORITHM = "TOS4-HMAC-SHA256"
SERVICE = "tos"
IDENTIFIER = "request"

TOS_DEFAULTS = {"bucket": "huoshan-yinpin", "region": "cn-shanghai", "endpoint": "tos-cn-shanghai.volces.com"}


def _amz_date(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _canonic_date(now: datetime) -> str:
    return _amz_date(now)[:8]


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _signing_key(secret_key: str, date: str, region: str) -> bytes:
    k_date = _hmac(secret_key.encode(), date.encode())
    k_region = _hmac(k_date, region.encode())
    k_service = _hmac(k_region, SERVICE.encode())
    return _hmac(k_service, IDENTIFIER.encode())


def host_of(settings: dict) -> str:
    return f"{settings['bucket']}.{settings['endpoint']}"


def _encode_key(key: str) -> str:
    """按段编码：与官方 SDK/encodeURIComponent 一致，保留 !~*'() 原样（Windows 重名 (1) 等常见）。"""
    return "/".join(urllib.parse.quote(seg, safe="!~*'()") for seg in key.split("/"))


def _virtual_host_url(settings: dict, key: str) -> str:
    return f"https://{host_of(settings)}/{_encode_key(key)}"


def presign_get(settings: dict, key: str, now: datetime | None = None, expires_seconds: int = 7 * 24 * 3600) -> str:
    """预签名 GET URL（Query 签名，X-Tos-* 参数）；now 可注入以做确定性测试。"""
    now = now or datetime.now(timezone.utc)
    amz_date = _amz_date(now)
    date = _canonic_date(now)
    host = host_of(settings)
    scope = f"{date}/{settings['region']}/{SERVICE}/{IDENTIFIER}"
    credential = urllib.parse.quote(f"{settings['accessKey']}/{scope}", safe="")
    empty_hash = hashlib.sha256(b"").hexdigest()
    pairs = [
        f"X-Tos-Algorithm={ALGORITHM}",
        f"X-Tos-Content-Sha256={empty_hash}",
        f"X-Tos-Credential={credential}",
        f"X-Tos-Date={amz_date}",
        f"X-Tos-Expires={expires_seconds}",
        "X-Tos-SignedHeaders=host",
    ]
    canonical_query = "&".join(sorted(pairs, key=lambda item: item.split("=", 1)[0]))
    canonical_request = (
        f"GET\n/{_encode_key(key)}\n{canonical_query}\nhost:{host}\n\nhost\n{empty_hash}"
    )
    string_to_sign = f"{ALGORITHM}\n{amz_date}\n{scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    signature = hmac.new(
        _signing_key(settings["secretKey"], date, settings["region"]),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{_virtual_host_url(settings, key)}?{canonical_query}&X-Tos-Signature={signature}"


def upload_file(settings: dict, key: str, file_path: str, now: datetime | None = None) -> str:
    """上传本地文件（PUT，Header 签名），成功后返回可给方舟抓取的预签名 URL。"""
    import requests

    now = now or datetime.now(timezone.utc)
    amz_date = _amz_date(now)
    date = _canonic_date(now)
    host = host_of(settings)
    with open(file_path, "rb") as handle:
        body = handle.read()
    body_hash = hashlib.sha256(body).hexdigest()
    canonical_headers = f"host:{host}\nx-tos-content-sha256:{body_hash}\nx-tos-date:{amz_date}\n"
    signed_headers = "host;x-tos-content-sha256;x-tos-date"
    canonical_request = (
        f"PUT\n/{_encode_key(key)}\n\n{canonical_headers}\n{signed_headers}\n{body_hash}"
    )
    scope = f"{date}/{settings['region']}/{SERVICE}/{IDENTIFIER}"
    string_to_sign = f"{ALGORITHM}\n{amz_date}\n{scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    signature = hmac.new(
        _signing_key(settings["secretKey"], date, settings["region"]),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"{ALGORITHM} Credential={settings['accessKey']}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    response = requests.put(
        _virtual_host_url(settings, key),
        headers={
            "x-tos-content-sha256": body_hash,
            "x-tos-date": amz_date,
            "authorization": authorization,
        },
        data=body,
        timeout=600,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"TOS 上传失败（HTTP {response.status_code}）：{response.text[:300]}。"
            "请检查 AK/SK 与桶名（TOS 控制台）。"
        )
    return presign_get(settings, key, now)
