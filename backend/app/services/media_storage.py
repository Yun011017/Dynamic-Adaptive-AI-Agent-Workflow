"""Direct-to-R2 media uploads, validation, and expired-upload cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MediaAsset

_MEDIA_TYPES = {
    "image": {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"},
    "video": {"video/mp4": ".mp4", "video/quicktime": ".mov"},
}
_PRESIGN_SECONDS = 15 * 60
_CONTENT_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "video/x-m4v": "video/mp4",
}


def _r2_client():
    if not settings.r2_enabled:
        raise HTTPException(503, "Cloudflare R2 尚未設定，請先完成後端環境變數設定")
    return boto3.client(
        "s3", endpoint_url=settings.r2_endpoint_url, aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(), region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _detect_content_type(head: bytes, requested_kind: str) -> str | None:
    if requested_kind == "image":
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
    if requested_kind == "video" and len(head) >= 12 and head[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _normalize_content_type(content_type: str) -> str:
    clean = content_type.lower().strip()
    return _CONTENT_TYPE_ALIASES.get(clean, clean)


def _assert_declared_upload(*, media_type: str, filename: str, content_type: str, size_bytes: int) -> str:
    content_type = _normalize_content_type(content_type)
    if media_type not in _MEDIA_TYPES or content_type not in _MEDIA_TYPES[media_type]:
        accepted = "、".join(_MEDIA_TYPES.get(media_type, {}))
        raise HTTPException(422, f"不支援的素材格式（目前收到：{content_type or '未知'}；支援：{accepted}）")
    if size_bytes > settings.r2_max_upload_bytes:
        maximum_mb = settings.r2_max_upload_bytes // (1024 * 1024)
        raise HTTPException(413, f"檔案超過 {maximum_mb} MB 上限")
    extension = _MEDIA_TYPES[media_type][content_type]
    allowed_extensions = {extension, ".jpeg"} if extension == ".jpg" else {extension}
    if Path(filename).suffix.lower() not in allowed_extensions:
        raise HTTPException(422, "檔案副檔名與素材格式不一致")
    return extension


def create_direct_upload(*, db: Session, workspace_id: int, media_type: str, filename: str, content_type: str, size_bytes: int) -> dict:
    """Issue a short-lived presigned R2 form; the file never crosses Vercel."""
    content_type = _normalize_content_type(content_type)
    extension = _assert_declared_upload(media_type=media_type, filename=filename, content_type=content_type, size_bytes=size_bytes)
    key = f"workspaces/{workspace_id}/instagram/{media_type}s/{uuid4().hex}{extension}"
    public_url = f"{settings.r2_public_base_url.rstrip('/')}/{key}"
    asset = MediaAsset(
        workspace_id=workspace_id, object_key=key, public_url=public_url, media_type=media_type,
        content_type=content_type, size_bytes=size_bytes, status="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.media_upload_ttl_hours),
    )
    db.add(asset)
    db.flush()
    try:
        signed = _r2_client().generate_presigned_post(
            settings.r2_bucket_name, key, Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, settings.r2_max_upload_bytes]],
            ExpiresIn=_PRESIGN_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        db.delete(asset)
        raise HTTPException(502, "無法建立 Cloudflare R2 上傳連結，請稍後再試") from exc
    return {"asset_id": asset.id, "url": public_url, "upload_url": signed["url"], "fields": signed["fields"], "expires_in_seconds": _PRESIGN_SECONDS}


def upload_media_via_proxy(*, file: UploadFile, workspace_id: int, media_type: str) -> dict:
    """Small-file fallback when a browser cannot complete the R2 CORS request."""
    stream = file.file
    stream.seek(0, 2)
    size_bytes = stream.tell()
    stream.seek(0)
    if not size_bytes:
        raise HTTPException(422, "上傳檔案不可為空")
    if size_bytes > settings.r2_proxy_fallback_max_bytes:
        maximum_mb = settings.r2_proxy_fallback_max_bytes // (1024 * 1024)
        raise HTTPException(413, f"此素材超過 {maximum_mb} MB，請確認 R2 直傳設定後重試")
    head = stream.read(32)
    stream.seek(0)
    detected_type = _detect_content_type(head, media_type)
    if media_type not in _MEDIA_TYPES or detected_type not in _MEDIA_TYPES[media_type]:
        raise HTTPException(422, "不支援的素材格式")
    key = f"workspaces/{workspace_id}/instagram/{media_type}s/{uuid4().hex}{_MEDIA_TYPES[media_type][detected_type]}"
    try:
        _r2_client().upload_fileobj(
            stream, settings.r2_bucket_name, key, ExtraArgs={"ContentType": detected_type},
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(502, "上傳至 Cloudflare R2 失敗，請稍後再試") from exc
    return {
        "url": f"{settings.r2_public_base_url.rstrip('/')}/{key}",
        "media_type": media_type,
        "size_bytes": size_bytes,
    }


def complete_direct_upload(*, db: Session, workspace_id: int, asset_id: int) -> dict:
    """Verify the actual R2 object before exposing its public URL to a draft."""
    asset = db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.workspace_id == workspace_id))
    if asset is None:
        raise HTTPException(404, "找不到上傳中的素材")
    if asset.status == "READY":
        return {"url": asset.public_url, "media_type": asset.media_type, "size_bytes": asset.size_bytes}
    if asset.status != "PENDING":
        raise HTTPException(409, "此素材無法完成上傳")
    client = _r2_client()
    try:
        head = client.head_object(Bucket=settings.r2_bucket_name, Key=asset.object_key)
        actual_size = int(head.get("ContentLength", 0))
        actual_type = str(head.get("ContentType", "")).split(";", 1)[0].lower()
        initial_bytes = client.get_object(Bucket=settings.r2_bucket_name, Key=asset.object_key, Range="bytes=0-31")["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(422, "R2 尚未收到素材，請等待上傳完成後再試") from exc
    detected_type = _detect_content_type(initial_bytes, asset.media_type)
    content_mismatch = detected_type != actual_type if asset.media_type == "image" else detected_type is None
    if not actual_size or actual_size > settings.r2_max_upload_bytes or actual_size != asset.size_bytes or actual_type not in _MEDIA_TYPES[asset.media_type] or content_mismatch:
        try:
            client.delete_object(Bucket=settings.r2_bucket_name, Key=asset.object_key)
        except (BotoCoreError, ClientError):
            pass
        asset.status = "FAILED"
        raise HTTPException(422, "素材驗證失敗，已拒絕此上傳")
    asset.status = "READY"
    return {"url": asset.public_url, "media_type": asset.media_type, "size_bytes": actual_size}


def mark_media_assets_referenced(*, db: Session, workspace_id: int, urls: list[str]) -> None:
    unique_urls = list({url for url in urls if isinstance(url, str) and url})
    if not unique_urls:
        return
    assets = db.scalars(select(MediaAsset).where(MediaAsset.workspace_id == workspace_id, MediaAsset.public_url.in_(unique_urls), MediaAsset.status.in_(("PENDING", "READY")))).all()
    now = datetime.now(timezone.utc)
    for asset in assets:
        asset.status = "REFERENCED"
        asset.referenced_at = now


def cleanup_expired_media_assets(*, db: Session, limit: int = 100) -> int:
    """Delete unreferenced R2 objects after their draft-saving grace period."""
    expired = db.scalars(select(MediaAsset).where(MediaAsset.status.in_(("PENDING", "READY", "FAILED")), MediaAsset.expires_at < datetime.now(timezone.utc)).order_by(MediaAsset.expires_at).limit(limit)).all()
    if not expired:
        return 0
    client = _r2_client()
    deleted = 0
    for asset in expired:
        try:
            client.delete_object(Bucket=settings.r2_bucket_name, Key=asset.object_key)
        except (BotoCoreError, ClientError):
            continue
        asset.status = "DELETED"
        deleted += 1
    return deleted
