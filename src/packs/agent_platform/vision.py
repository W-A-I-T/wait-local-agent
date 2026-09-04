"""Private ticket-image storage and bounded multimodal analysis."""

from __future__ import annotations

import base64
import binascii
import builtins
import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import httpx

from wait_local_agent import fs_permissions
from wait_local_agent.config import Settings
from wait_local_agent.net_security import (
    NetSecurityError,
    build_pinned_client,
    validate_operator_url,
)
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.store import Store

from .memory import MemoryService
from .storage import (
    AgentPlatformError,
    AgentPlatformNotFoundError,
    actor_identifier,
    ensure_schema,
    json_dumps,
    json_loads_object,
    require_client,
    utc_now,
    validate_identifier,
    validate_text,
)

MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024
MAX_VISION_PROMPT = 2_000
MAX_PROVIDER_OUTPUT = 20_000
MAX_PROVIDER_RESPONSE_BYTES = 64_000
_ALLOWED_MEDIA_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_LOCAL_MULTIMODAL_PROVIDERS = frozenset({"openai-compatible", "ollama", "vllm"})
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class TicketAttachment:
    id: str
    client_id: str
    ticket_id: str
    filename: str
    media_type: str
    byte_size: int
    sha256: str
    status: str
    uploaded_by: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AttachmentAnalysis:
    id: int
    attachment_id: str
    client_id: str
    ticket_id: str
    status: str
    provider: str
    model: str
    result: dict[str, object]
    error_detail: str
    requested_by: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AttachmentService:
    def __init__(self, store: Store, settings: Settings, memories: MemoryService) -> None:
        self.store = store
        self.settings = settings
        self.memories = memories
        ensure_schema(store)
        self.root = settings.data_path.parent / "ticket-attachments"
        fs_permissions.create_private_directory(self.root)

    def upload(
        self,
        *,
        client_id: str,
        ticket_id: str,
        filename: str,
        media_type: str,
        content_base64: str,
        actor: str,
    ) -> TicketAttachment:
        client_id = require_client(self.store, client_id)
        ticket_id = validate_identifier(ticket_id, "ticket_id")
        if self.store.get_ticket(ticket_id, client_id=client_id) is None:
            raise AgentPlatformNotFoundError("ticket was not found")
        filename = _filename(filename)
        media_type = media_type.strip().lower()
        suffix = _ALLOWED_MEDIA_TYPES.get(media_type)
        if suffix is None:
            raise AgentPlatformError("media_type must be image/png, image/jpeg, or image/webp")
        if not isinstance(content_base64, str) or len(content_base64) > (MAX_ATTACHMENT_BYTES * 4 // 3) + 64:
            raise AgentPlatformError("attachment base64 content exceeds the bounded limit")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AgentPlatformError("attachment content is not valid base64") from exc
        if not content or len(content) > MAX_ATTACHMENT_BYTES:
            raise AgentPlatformError(
                f"attachment must contain between 1 and {MAX_ATTACHMENT_BYTES} bytes"
            )
        _validate_signature(content, media_type)
        sha256 = hashlib.sha256(content).hexdigest()
        actor = actor_identifier(actor)
        with self.store._connect() as connection:  # noqa: SLF001
            duplicate = connection.execute(
                """
                select * from ticket_attachments
                where client_id = ? and ticket_id = ? and sha256 = ? and status = 'stored'
                order by created_at desc limit 1
                """,
                (client_id, ticket_id, sha256),
            ).fetchone()
        if duplicate is not None:
            attachment = _attachment(duplicate)
            self.store.add_audit_event(
                "ticket_attachment.reused",
                attachment.id,
                f"ticket={ticket_id} sha256={sha256}",
                client_id=client_id,
                approver_id=actor,
            )
            return attachment
        attachment_id = str(uuid.uuid4())
        root = self.root.resolve(strict=True)
        client_directory = self.root / hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:16]
        if client_directory.is_symlink():
            raise AgentPlatformError("ticket attachment directory is invalid")
        fs_permissions.create_private_directory(client_directory)
        try:
            resolved_directory = client_directory.resolve(strict=True)
        except OSError as exc:
            raise AgentPlatformError("ticket attachment directory is unavailable") from exc
        if root not in resolved_directory.parents:
            raise AgentPlatformError("ticket attachment directory is outside private storage")
        path = resolved_directory / f"{attachment_id}{suffix}"
        fs_permissions.write_private_bytes(path, content, replace_existing=False)
        now = utc_now()
        try:
            with self.store._connect() as connection:  # noqa: SLF001
                connection.execute(
                    """
                    insert into ticket_attachments (
                        id, client_id, ticket_id, filename, media_type, byte_size,
                        sha256, storage_path, status, uploaded_by, created_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, 'stored', ?, ?)
                    """,
                    (
                        attachment_id,
                        client_id,
                        ticket_id,
                        filename,
                        media_type,
                        len(content),
                        sha256,
                        str(path),
                        actor,
                        now,
                    ),
                )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.store.add_audit_event(
            "ticket_attachment.stored",
            attachment_id,
            f"ticket={ticket_id} media_type={media_type} bytes={len(content)} sha256={sha256}",
            client_id=client_id,
            approver_id=actor,
        )
        return self.get(client_id=client_id, ticket_id=ticket_id, attachment_id=attachment_id)

    def get(
        self,
        *,
        client_id: str,
        ticket_id: str,
        attachment_id: str,
    ) -> TicketAttachment:
        client_id = require_client(self.store, client_id)
        ticket_id = validate_identifier(ticket_id, "ticket_id")
        attachment_id = validate_identifier(attachment_id, "attachment_id")
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                """
                select * from ticket_attachments
                where id = ? and client_id = ? and ticket_id = ? and status = 'stored'
                """,
                (attachment_id, client_id, ticket_id),
            ).fetchone()
        if row is None:
            raise AgentPlatformNotFoundError("ticket attachment was not found")
        return _attachment(row)

    def list(self, *, client_id: str, ticket_id: str) -> list[TicketAttachment]:
        client_id = require_client(self.store, client_id)
        ticket_id = validate_identifier(ticket_id, "ticket_id")
        if self.store.get_ticket(ticket_id, client_id=client_id) is None:
            raise AgentPlatformNotFoundError("ticket was not found")
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                """
                select * from ticket_attachments
                where client_id = ? and ticket_id = ? and status = 'stored'
                order by created_at desc limit 50
                """,
                (client_id, ticket_id),
            ).fetchall()
        return [_attachment(row) for row in rows]

    def analyze(
        self,
        *,
        client_id: str,
        ticket_id: str,
        attachment_id: str,
        prompt: str,
        actor: str,
    ) -> AttachmentAnalysis:
        attachment = self.get(
            client_id=client_id,
            ticket_id=ticket_id,
            attachment_id=attachment_id,
        )
        prompt = redact_text(validate_text(prompt, "prompt", maximum=MAX_VISION_PROMPT))
        actor = actor_identifier(actor)
        provider = ""
        model = ""
        status = "blocked"
        result: dict[str, object] = {
            "summary": "",
            "visible_text": [],
            "indicators": [],
            "confidence": 0.0,
            "limitations": [],
        }
        error_detail = ""
        configuration = self._model_configuration()
        if configuration["status"] != "ready":
            error_detail = str(configuration["message"])
            provider = str(configuration.get("provider", ""))
            model = str(configuration.get("model", ""))
        else:
            provider = str(configuration["provider"])
            model = str(configuration["model"])
            try:
                content = self._read_verified_content(attachment)
                timeout_value = configuration.get("timeout", 20.0)
                timeout = (
                    float(timeout_value)
                    if isinstance(timeout_value, (int, float)) and not isinstance(timeout_value, bool)
                    else 20.0
                )
                response = _request_analysis(
                    base_url=str(configuration["base_url"]),
                    model=model,
                    api_key=str(configuration.get("api_key", "")),
                    timeout=timeout,
                    media_type=attachment.media_type,
                    content=content,
                    prompt=prompt,
                    allow_insecure_transport=self.settings.allow_insecure_provider_transport,
                )
                result = _normalize_analysis(response)
                status = "ready"
            except AgentPlatformError as exc:
                status = "failed"
                error_detail = redact_text(str(exc))[:2_000]
            except Exception:  # provider details remain private
                status = "failed"
                error_detail = "multimodal provider request failed"
        analysis = self._persist_analysis(
            attachment=attachment,
            status=status,
            provider=provider,
            model=model,
            result=result,
            error_detail=error_detail,
            actor=actor,
        )
        self.store.add_audit_event(
            "ticket_attachment.analyzed",
            attachment.id,
            f"ticket={ticket_id} status={status} provider={provider or 'none'} model={model or 'none'}",
            client_id=attachment.client_id,
            approver_id=actor,
        )
        return analysis

    def analyses(
        self,
        *,
        client_id: str,
        ticket_id: str,
        attachment_id: str | None = None,
    ) -> builtins.list[AttachmentAnalysis]:
        client_id = require_client(self.store, client_id)
        ticket_id = validate_identifier(ticket_id, "ticket_id")
        clauses = ["client_id = ?", "ticket_id = ?"]
        params: list[object] = [client_id, ticket_id]
        if attachment_id is not None:
            clauses.append("attachment_id = ?")
            params.append(validate_identifier(attachment_id, "attachment_id"))
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                f"""
                select * from ticket_attachment_analyses
                where {' and '.join(clauses)}
                order by created_at desc, id desc limit 100
                """,  # nosec B608 - clauses are fixed strings
                params,
            ).fetchall()
        return [_analysis(row) for row in rows]

    def ticket_context(
        self,
        *,
        client_id: str,
        ticket_id: str,
        agent_id: str | None = None,
        technician_id: str | None = None,
    ) -> dict[str, object]:
        client_id = require_client(self.store, client_id)
        ticket_id = validate_identifier(ticket_id, "ticket_id")
        ticket = self.store.get_ticket(ticket_id, client_id=client_id)
        if ticket is None:
            raise AgentPlatformNotFoundError("ticket was not found")
        attachments = self.list(client_id=client_id, ticket_id=ticket_id)
        analyses = self.analyses(client_id=client_id, ticket_id=ticket_id)
        latest_by_attachment: dict[str, AttachmentAnalysis] = {}
        for analysis in analyses:
            latest_by_attachment.setdefault(analysis.attachment_id, analysis)
        memories = self.memories.resolve_context(
            client_id=client_id,
            agent_id=agent_id,
            technician_id=technician_id,
            ticket_id=ticket_id,
            limit=20,
        )
        return cast(
            dict[str, object],
            redact_value(
                {
                    "ticket": {
                        "id": ticket.id,
                        "subject": ticket.subject,
                        "priority": ticket.priority,
                        "status": ticket.status,
                        "client_id": ticket.client_id,
                    },
                    "attachments": [
                        {
                            **attachment.to_dict(),
                            "analysis": (
                                latest_by_attachment[attachment.id].to_dict()
                                if attachment.id in latest_by_attachment
                                else None
                            ),
                        }
                        for attachment in attachments
                    ],
                    "memories": memories,
                    "limits": {
                        "attachment_count": 50,
                        "memory_count": 20,
                        "raw_attachment_bytes_returned": False,
                    },
                }
            ),
        )

    def _model_configuration(self) -> dict[str, object]:
        settings = self.settings
        if not settings.allow_llm_inference:
            return {
                "status": "blocked",
                "message": "multimodal analysis is blocked until WAIT_ALLOW_LLM_INFERENCE=true",
            }
        local_provider = settings.local_model_provider.strip().lower()
        if local_provider in _LOCAL_MULTIMODAL_PROVIDERS:
            if not settings.local_model_base_url.strip() or not settings.local_model_name.strip():
                return {
                    "status": "blocked",
                    "provider": local_provider,
                    "message": "local multimodal model configuration is incomplete",
                }
            return {
                "status": "ready",
                "provider": local_provider,
                "base_url": settings.local_model_base_url,
                "model": settings.local_model_name,
                "api_key": "",
                "timeout": settings.local_model_timeout_seconds,
            }
        if settings.offline_mode:
            return {
                "status": "blocked",
                "provider": local_provider,
                "message": "configured local provider does not expose the supported multimodal contract",
            }
        remote_provider = settings.remote_model_provider.strip().lower()
        if not settings.allow_cloud_fallback:
            return {
                "status": "blocked",
                "provider": local_provider,
                "message": "no supported local multimodal provider is configured and cloud fallback is disabled",
            }
        if remote_provider != "openai-compatible":
            return {
                "status": "blocked",
                "provider": remote_provider,
                "message": "remote multimodal analysis currently requires an openai-compatible provider",
            }
        if not (
            settings.remote_model_base_url.strip()
            and settings.remote_model_name.strip()
            and settings.remote_model_api_key.strip()
        ):
            return {
                "status": "blocked",
                "provider": remote_provider,
                "message": "remote multimodal model configuration is incomplete",
            }
        return {
            "status": "ready",
            "provider": remote_provider,
            "base_url": settings.remote_model_base_url,
            "model": settings.remote_model_name,
            "api_key": settings.remote_model_api_key,
            "timeout": settings.remote_model_timeout_seconds,
        }

    def _read_verified_content(self, attachment: TicketAttachment) -> bytes:
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "select storage_path from ticket_attachments where id = ? and client_id = ?",
                (attachment.id, attachment.client_id),
            ).fetchone()
        if row is None:
            raise AgentPlatformNotFoundError("ticket attachment storage record was not found")
        path = Path(str(row[0]))
        try:
            if path.is_symlink():
                raise AgentPlatformError("ticket attachment storage path is invalid")
            resolved = path.resolve(strict=True)
            root = self.root.resolve(strict=True)
        except OSError as exc:
            raise AgentPlatformError("ticket attachment file is unavailable") from exc
        if root not in resolved.parents or not resolved.is_file():
            raise AgentPlatformError("ticket attachment storage path is invalid")
        try:
            content = resolved.read_bytes()
        except OSError as exc:
            raise AgentPlatformError("ticket attachment file could not be read") from exc
        if len(content) != attachment.byte_size or hashlib.sha256(content).hexdigest() != attachment.sha256:
            raise AgentPlatformError("ticket attachment integrity check failed")
        return content

    def _persist_analysis(
        self,
        *,
        attachment: TicketAttachment,
        status: str,
        provider: str,
        model: str,
        result: dict[str, object],
        error_detail: str,
        actor: str,
    ) -> AttachmentAnalysis:
        created_at = utc_now()
        safe_result = cast(dict[str, object], redact_value(result))
        with self.store._connect() as connection:  # noqa: SLF001
            cursor = connection.execute(
                """
                insert into ticket_attachment_analyses (
                    attachment_id, client_id, ticket_id, status, provider, model,
                    result_json, error_detail, requested_by, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment.id,
                    attachment.client_id,
                    attachment.ticket_id,
                    status,
                    provider[:120],
                    model[:240],
                    json_dumps(safe_result),
                    error_detail[:2_000],
                    actor,
                    created_at,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("attachment analysis insert did not return an ID")
            analysis_id = int(cursor.lastrowid)
        return AttachmentAnalysis(
            id=analysis_id,
            attachment_id=attachment.id,
            client_id=attachment.client_id,
            ticket_id=attachment.ticket_id,
            status=status,
            provider=provider[:120],
            model=model[:240],
            result=safe_result,
            error_detail=error_detail[:2_000],
            requested_by=actor,
            created_at=created_at,
        )


def _attachment(row: sqlite3.Row) -> TicketAttachment:
    return TicketAttachment(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        ticket_id=str(row["ticket_id"]),
        filename=str(row["filename"]),
        media_type=str(row["media_type"]),
        byte_size=int(row["byte_size"]),
        sha256=str(row["sha256"]),
        status=str(row["status"]),
        uploaded_by=str(row["uploaded_by"]),
        created_at=str(row["created_at"]),
    )


def _analysis(row: sqlite3.Row) -> AttachmentAnalysis:
    return AttachmentAnalysis(
        id=int(row["id"]),
        attachment_id=str(row["attachment_id"]),
        client_id=str(row["client_id"]),
        ticket_id=str(row["ticket_id"]),
        status=str(row["status"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        result=cast(dict[str, object], json_loads_object(str(row["result_json"]))),
        error_detail=str(row["error_detail"]),
        requested_by=str(row["requested_by"]),
        created_at=str(row["created_at"]),
    )


def _filename(value: str) -> str:
    normalized = validate_text(value, "filename", minimum=1, maximum=180)
    if Path(normalized).name != normalized or normalized in {".", ".."}:
        raise AgentPlatformError("filename must be a plain filename")
    return normalized


def _validate_signature(content: bytes, media_type: str) -> None:
    valid = (
        media_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
    ) or (
        media_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")
    ) or (
        media_type == "image/webp"
        and len(content) >= 12
        and content[:4] == b"RIFF"
        and content[8:12] == b"WEBP"
    )
    if not valid:
        raise AgentPlatformError("attachment bytes do not match the declared media_type")


def _request_analysis(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: float,
    media_type: str,
    content: bytes,
    prompt: str,
    allow_insecure_transport: bool = False,
) -> dict[str, object]:
    encoded = base64.b64encode(content).decode("ascii")
    url = (
        f"{_safe_base_url(base_url, allow_insecure_transport=allow_insecure_transport)}"
        "/chat/completions"
    )
    system_prompt = (
        "You assist an authorized IT technician by examining one ticket image. "
        "Use only visible evidence. Never claim that a command, remediation, or provider action ran. "
        "Do not infer passwords, secrets, identities, or hidden data. Return only JSON with fields: "
        "summary (string), visible_text (array of short strings), indicators (array of short strings), "
        "confidence (number from 0 to 1), and limitations (array of short strings)."
    )
    user_prompt = (
        "Attached ticket image. "
        f"Technician request: {prompt or 'Summarize visible diagnostic evidence.'}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{encoded}",
                            "detail": "low",
                        },
                    },
                ],
            },
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    host = urlsplit(url).hostname
    if host is None:
        raise AgentPlatformError("multimodal provider base URL must include a hostname")
    try:
        with build_pinned_client(
            allowed_hosts=(host,),
            timeout=timeout,
            max_response_bytes=MAX_PROVIDER_RESPONSE_BYTES,
            allow_loopback=True,
        ) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(0.25)
                response = client.post(url, headers=headers, json=payload)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise AgentPlatformError("multimodal provider request failed before receiving a response") from exc
    except httpx.HTTPError as exc:
        raise AgentPlatformError("multimodal provider request failed") from exc
    if response.status_code >= 400:
        if response.status_code in {401, 403}:
            raise AgentPlatformError("multimodal provider request was unauthorized")
        raise AgentPlatformError(f"multimodal provider request failed with HTTP {response.status_code}")
    if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
        raise AgentPlatformError("multimodal provider response exceeded the bounded limit")
    try:
        body = response.json()
    except ValueError as exc:
        raise AgentPlatformError("multimodal provider returned malformed JSON") from exc
    if not isinstance(body, Mapping):
        raise AgentPlatformError("multimodal provider returned a malformed response")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise AgentPlatformError("multimodal provider returned no completion")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise AgentPlatformError("multimodal provider returned a malformed message")
    raw_content = message.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise AgentPlatformError("multimodal provider returned empty content")
    if len(raw_content) > MAX_PROVIDER_OUTPUT:
        raise AgentPlatformError("multimodal provider output exceeded the bounded limit")
    match = _CODE_FENCE_RE.match(raw_content.strip())
    candidate = match.group(1) if match else raw_content.strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AgentPlatformError("multimodal provider content was not valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise AgentPlatformError("multimodal provider JSON must be an object")
    return dict(parsed)


def _safe_base_url(value: str, *, allow_insecure_transport: bool = False) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentPlatformError("multimodal provider base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AgentPlatformError(
            "multimodal provider base URL must not contain credentials or query data"
        )
    try:
        validate_operator_url(
            value,
            allow_insecure_transport=allow_insecure_transport,
            allow_loopback=True,
        )
    except NetSecurityError as exc:
        raise AgentPlatformError(str(exc)) from exc
    return value.strip().rstrip("/")


def _normalize_analysis(value: Mapping[str, object]) -> dict[str, object]:
    summary = redact_text(str(value.get("summary", "")))[:2_000]
    visible_text = _bounded_strings(value.get("visible_text"), limit=30, item_limit=500)
    indicators = _bounded_strings(value.get("indicators"), limit=30, item_limit=300)
    limitations = _bounded_strings(value.get("limitations"), limit=20, item_limit=300)
    raw_confidence = value.get("confidence", 0.0)
    confidence = (
        float(raw_confidence)
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool)
        else 0.0
    )
    confidence = min(max(confidence, 0.0), 1.0)
    if not summary and not visible_text and not indicators:
        raise AgentPlatformError("multimodal provider returned no usable bounded evidence")
    return cast(
        dict[str, object],
        redact_value(
            {
                "summary": summary,
                "visible_text": visible_text,
                "indicators": indicators,
                "confidence": confidence,
                "limitations": limitations,
                "evidence_only": True,
            }
        ),
    )


def _bounded_strings(value: object, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        redact_text(str(item))[:item_limit]
        for item in value[:limit]
        if isinstance(item, (str, int, float)) and str(item).strip()
    ]


__all__ = [
    "AttachmentAnalysis",
    "AttachmentService",
    "MAX_ATTACHMENT_BYTES",
    "TicketAttachment",
]
