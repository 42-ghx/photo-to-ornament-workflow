"""Explicit, one-job OpenAI-compatible Images API worker. Never accepts keys via CLI.

Only this process reads ORNAMENT_IMAGE_API_KEY. The studio/browser never receives it.
Uses the standard library plus the studio's Pillow dependency; no automatic retries.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener
import uuid

from PIL import Image

MAX_IMAGE = 32 * 1024 * 1024
MAX_RESPONSE = 46 * 1024 * 1024
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class SafeError(Exception):
    """Only fixed, credential-free messages may leave this process."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def base_url(value, *, local_only=False):
    try:
        u = urlsplit(value)
        port = u.port
        loopback = u.hostname in {"127.0.0.1", "localhost", "::1"}
        valid = u.scheme == "https" or (u.scheme == "http" and loopback)
        if (not valid or not u.hostname or u.username is not None or u.password is not None
                or u.query or u.fragment or (local_only and not loopback)
                or not re.fullmatch(r"(?:/[A-Za-z0-9._~-]+)*/?", u.path)
                or (local_only and u.path not in {"", "/"})):
            raise ValueError()
        value.encode("ascii")
        return value.rstrip("/")
    except (ValueError, UnicodeError):
        raise SafeError("服务地址无效：仅允许 HTTPS 或本机 HTTP；不能含账号、密码、查询参数或片段。") from None


@dataclass(frozen=True)
class Config:
    endpoint: str = field(repr=False)
    model: str
    key: str = field(repr=False)

    @classmethod
    def from_env(cls):
        key = os.environ.get("ORNAMENT_IMAGE_API_KEY", "")
        model = os.environ.get("ORNAMENT_IMAGE_MODEL", "")
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise SafeError("请在本机进程环境设置 ORNAMENT_IMAGE_API_KEY；不要把密钥传给网页或命令参数。")
        if not MODEL.fullmatch(model) or key in model:
            raise SafeError("请设置有效的 ORNAMENT_IMAGE_MODEL，例如 gpt-image-1.5。")
        endpoint = base_url(os.environ.get("ORNAMENT_IMAGE_BASE_URL", "https://api.openai.com/v1"))
        if key in endpoint:
            raise SafeError("服务地址中不能包含密钥。")
        return cls(endpoint, model, key)


def transport(url, *, body=None, headers=None, limit=MAX_RESPONSE, timeout=300):
    # Do not send credentials to redirected hosts or ambient proxy servers.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise SafeError("响应超过大小限制。")
        return data
    except HTTPError as exc:
        # Never reflect the response body, URL, headers, or exception text.
        status = exc.code
        exc.close()
        raise SafeError(f"HTTP {status}：请求未完成；未自动重试，请在服务商后台确认任务和费用。") from None
    except SafeError:
        raise
    except Exception:
        raise SafeError("网络请求失败或超时；未自动重试，请在服务商后台确认任务和费用。") from None


def image_kind(data, *, png_only=False):
    if not 0 < len(data) <= MAX_IMAGE:
        raise SafeError("图片须小于等于 32 MiB。")
    try:
        with Image.open(io.BytesIO(data)) as image:
            kind = image.format
            if kind not in ({"PNG"} if png_only else {"PNG", "JPEG", "WEBP"}):
                raise ValueError()
            image.verify()
        return {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp")}[kind]
    except Exception:
        raise SafeError("图片格式或内容无效；结果必须是真实 PNG。") from None


def generate(config, prompt, images, *, size="auto", quality="auto", background="auto"):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 32000:
        raise SafeError("提示词须为 1–32000 字符。")
    if len(images) > 16 or sum(map(len, images)) > 100 * 1024 * 1024:
        raise SafeError("参考图最多 16 张，总大小不超过 100 MiB。")
    if config.key in prompt or any(config.key.encode() in data for data in images):
        raise SafeError("输入意外包含当前密钥，已拒绝发送。")
    if not re.fullmatch(r"auto|[1-9][0-9]{1,3}x[1-9][0-9]{1,3}", size):
        raise SafeError("size 应为 auto 或 WIDTHxHEIGHT。")
    if quality not in {"auto", "low", "medium", "high"} or background not in {"auto", "transparent", "opaque"}:
        raise SafeError("质量或背景选项无效。")
    fields = dict(model=config.model, prompt=prompt, n=1, size=size, quality=quality,
                  background=background, output_format="png")
    if images:
        boundary = "ornament-" + uuid.uuid4().hex
        chunks = []
        for name, value in fields.items():
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for index, data in enumerate(images):
            ext, mime = image_kind(data)
            name = "image[]" if len(images) > 1 else "image"
            chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="reference-{index + 1}.{ext}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), data, b"\r\n"])
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        content_type = "multipart/form-data; boundary=" + boundary
        route = "/images/edits"
    else:
        body = json.dumps(fields).encode()
        content_type = "application/json"
        route = "/images/generations"
    raw = transport(config.endpoint + route, body=body,
                    headers={"Authorization": "Bearer " + config.key, "Content-Type": content_type})
    try:
        response = json.loads(raw)
        encoded = response["data"][0]["b64_json"]
        if not isinstance(encoded, str):
            raise ValueError()
        data = base64.b64decode(encoded, validate=True)
    except Exception:
        raise SafeError("接口未返回有效的 data[0].b64_json。仅支持内联 base64 PNG，不自动下载返回的 URL。") from None
    image_kind(data, png_only=True)
    if config.key.encode() in data:
        raise SafeError("返回图片意外包含当前密钥，已拒绝保存。")
    metadata = {"provider": "openai_compatible", "requested_model": config.model}
    reported = response.get("image_model") or response.get("model")
    if isinstance(reported, str) and MODEL.fullmatch(reported) and config.key not in reported:
        metadata["reported_model"] = reported
    return data, metadata


def studio_json(studio, route, payload=None):
    raw = transport(studio + route, body=None if payload is None else json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"}, timeout=30)
    try:
        return json.loads(raw)
    except Exception:
        raise SafeError("工作台响应格式无效。") from None


def run_job(config, studio, job_id, **options):
    studio = base_url(studio, local_only=True)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", job_id):
        raise SafeError("任务 ID 无效。")
    pending = studio_json(studio, "/api/codex/requests")
    if isinstance(pending, dict):
        pending = pending.get("requests", [])
    task = next((r for r in pending if r.get("job_id") == job_id), None)
    if not task:
        raise SafeError("任务不在等待列表，已停止；不会重复调用服务商。")
    images, roles = [], []
    for slot in ("image", "mask", "guide"):
        path = task.get("references", {}).get(slot)
        if path:
            if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/") or "\\" in path:
                raise SafeError("工作台参考图路径无效。")
            data = transport(studio + "/files/" + quote(path, safe="/"), limit=MAX_IMAGE, timeout=30)
            image_kind(data)
            images.append(data)
            roles.append(f"Reference {len(images)}: {slot}")
    prompt = task.get("prompt", "")
    if roles:
        prompt = "\n".join(roles) + "\nThe mask reference is a material/UV guide, not an API inpainting mask.\n" + prompt
    # Atomic claim prevents two worker processes from charging for the same job.
    studio_json(studio, "/api/image-api/claim", {"job_id": job_id})
    try:
        data, metadata = generate(config, prompt, images, **options)
        uploaded = studio_json(studio, "/api/upload", {"name": "api-generated.png", "data": base64.b64encode(data).decode()})
        studio_json(studio, "/api/codex/complete", {"job_id": job_id, "path": uploaded["path"], "generation": metadata})
    except Exception as exc:
        message = str(exc) if isinstance(exc, SafeError) else "接口执行失败，未输出底层错误；请检查服务商任务状态。"
        try:
            studio_json(studio, "/api/codex/fail", {"job_id": job_id, "message": message})
        except Exception:
            pass
        raise SafeError(message) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="validate environment only; no network or billing")
    action.add_argument("--job", help="execute exactly one pending studio job")
    action.add_argument("--prompt-file", type=Path, help="standalone generation/edit from a UTF-8 prompt file")
    parser.add_argument("--studio-url", default="http://127.0.0.1:8001")
    parser.add_argument("--image", action="append", type=Path, default=[])
    parser.add_argument("--out", type=Path, help="new PNG file for standalone mode")
    parser.add_argument("--size", default="auto")
    parser.add_argument("--quality", default="auto", choices=["auto", "low", "medium", "high"])
    parser.add_argument("--background", default="auto", choices=["auto", "transparent", "opaque"])
    args = parser.parse_args(argv)
    try:
        config = Config.from_env()
        options = dict(size=args.size, quality=args.quality, background=args.background)
        if args.check:
            print("配置有效；密钥和地址不显示。模型：" + config.model + "。尚未调用 API。")
        elif args.job:
            if args.image or args.out:
                raise SafeError("工作台模式只使用该任务的输入；不要传 --image 或 --out。")
            run_job(config, args.studio_url, args.job, **options)
            print("指定任务已完成并回填工作台。")
        else:
            if not args.out or args.out.suffix.lower() != ".png" or args.out.exists():
                raise SafeError("独立模式必须提供尚不存在的 --out PNG 路径。")
            if not args.out.parent.is_dir():
                raise SafeError("请先创建输出目录。")
            metadata_file = args.out.with_suffix(".generation.json")
            if metadata_file.exists():
                raise SafeError("模型记录已存在，请使用新文件名。")
            data, metadata = generate(config, args.prompt_file.read_text("utf-8"), [p.read_bytes() for p in args.image], **options)
            with args.out.open("xb") as stream:
                stream.write(data)
            with metadata_file.open("x", encoding="utf-8") as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2)
            print("图片与模型记录已保存；未保存密钥或服务地址。")
        return 0
    except SafeError as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print("执行失败；未显示底层路径、配置或响应内容，请检查本机文件和接口兼容性。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
