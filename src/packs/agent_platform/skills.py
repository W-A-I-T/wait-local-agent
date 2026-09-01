"""Versioned reusable skills with a side-effect-free validation harness."""

from __future__ import annotations

import builtins
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import TypedDict, cast

from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store

from .storage import (
    AgentPlatformConflictError,
    AgentPlatformError,
    AgentPlatformNotFoundError,
    actor_identifier,
    digest_json,
    ensure_schema,
    json_dumps,
    json_loads_list,
    json_loads_object,
    require_client,
    safe_json_value,
    utc_now,
    validate_identifier,
    validate_text,
)

MAX_SKILL_TOOLS = 16
MAX_SKILL_RESOURCES = 10
MAX_RESOURCE_BYTES = 20_000
MAX_SKILL_INSTRUCTIONS = 20_000
_TEMPLATE_RE = re.compile(r"\{\{\s*(input|memory)\.([A-Za-z0-9_.:-]{1,128})\s*\}\}")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_RESOURCE_MEDIA_TYPES = frozenset({"text/plain", "text/markdown", "application/json"})


class _RevisionPayload(TypedDict):
    instructions: str
    allowed_tools: list[str]
    input_schema: dict[str, object]
    resources: list[dict[str, object]]
    digest: str


@dataclass(frozen=True)
class SkillRevision:
    skill_id: str
    version: int
    instructions: str
    allowed_tools: list[str]
    input_schema: dict[str, object]
    resources: list[dict[str, object]]
    digest: str
    created_by: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SkillRecord:
    id: str
    client_id: str
    name: str
    slug: str
    description: str
    status: str
    current_version: int
    created_by: str
    created_at: str
    updated_at: str
    revision: SkillRevision

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SkillTestRun:
    id: int
    skill_id: str
    skill_version: int
    client_id: str
    actor: str
    input_digest: str
    status: str
    output: dict[str, object]
    error_detail: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SkillService:
    def __init__(self, store: Store, smart_actions: SmartActionService) -> None:
        self.store = store
        self.smart_actions = smart_actions
        ensure_schema(store)

    def create(
        self,
        *,
        client_id: str,
        name: str,
        slug: str,
        description: str,
        instructions: str,
        allowed_tools: builtins.list[str],
        input_schema: dict[str, object],
        resources: builtins.list[dict[str, object]],
        actor: str,
    ) -> SkillRecord:
        client_id = require_client(self.store, client_id)
        name = validate_text(name, "name", minimum=1, maximum=120)
        slug = _slug(slug)
        description = redact_text(validate_text(description, "description", maximum=2_000))
        actor = actor_identifier(actor)
        revision_payload = self._revision_payload(
            instructions=instructions,
            allowed_tools=allowed_tools,
            input_schema=input_schema,
            resources=resources,
        )
        skill_id = str(uuid.uuid4())
        now = utc_now()
        with self.store._connect() as connection:  # noqa: SLF001
            try:
                connection.execute(
                    """
                    insert into agent_skills (
                        id, client_id, name, slug, description, status,
                        current_version, created_by, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, 'active', 1, ?, ?, ?)
                    """,
                    (skill_id, client_id, name, slug, description, actor, now, now),
                )
                _insert_revision(
                    connection,
                    skill_id=skill_id,
                    version=1,
                    actor=actor,
                    created_at=now,
                    **revision_payload,
                )
            except sqlite3.IntegrityError as exc:
                raise AgentPlatformConflictError("a skill with that slug already exists") from exc
        self.store.add_audit_event(
            "agent_skill.created",
            skill_id,
            f"{slug} version=1",
            client_id=client_id,
            approver_id=actor,
        )
        return self.get(client_id=client_id, skill_id=skill_id)

    def update(
        self,
        *,
        client_id: str,
        skill_id: str,
        actor: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        allowed_tools: list[str] | None = None,
        input_schema: dict[str, object] | None = None,
        resources: list[dict[str, object]] | None = None,
    ) -> SkillRecord:
        current = self.get(client_id=client_id, skill_id=skill_id)
        if current.status != "active":
            raise AgentPlatformConflictError("archived skills cannot be updated")
        actor = actor_identifier(actor)
        next_name = (
            validate_text(name, "name", minimum=1, maximum=120) if name is not None else current.name
        )
        next_description = (
            redact_text(validate_text(description, "description", maximum=2_000))
            if description is not None
            else current.description
        )
        revision_payload = self._revision_payload(
            instructions=instructions if instructions is not None else current.revision.instructions,
            allowed_tools=allowed_tools if allowed_tools is not None else current.revision.allowed_tools,
            input_schema=input_schema if input_schema is not None else current.revision.input_schema,
            resources=resources if resources is not None else current.revision.resources,
        )
        next_version = current.current_version + 1
        now = utc_now()
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "select current_version from agent_skills where id = ? and client_id = ?",
                (current.id, current.client_id),
            ).fetchone()
            if row is None or int(row[0]) != current.current_version:
                raise AgentPlatformConflictError("skill was updated concurrently")
            _insert_revision(
                connection,
                skill_id=current.id,
                version=next_version,
                actor=actor,
                created_at=now,
                **revision_payload,
            )
            cursor = connection.execute(
                """
                update agent_skills
                set name = ?, description = ?, current_version = ?, updated_at = ?
                where id = ? and client_id = ? and current_version = ?
                """,
                (
                    next_name,
                    next_description,
                    next_version,
                    now,
                    current.id,
                    current.client_id,
                    current.current_version,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentPlatformConflictError("skill was updated concurrently")
        self.store.add_audit_event(
            "agent_skill.updated",
            current.id,
            f"{current.slug} version={next_version}",
            client_id=current.client_id,
            approver_id=actor,
        )
        return self.get(client_id=current.client_id, skill_id=current.id)

    def get(
        self,
        *,
        client_id: str,
        skill_id: str,
        version: int | None = None,
    ) -> SkillRecord:
        client_id = require_client(self.store, client_id)
        skill_id = validate_identifier(skill_id, "skill_id")
        with self.store._connect() as connection:  # noqa: SLF001
            skill = connection.execute(
                "select * from agent_skills where id = ? and client_id = ?",
                (skill_id, client_id),
            ).fetchone()
            if skill is None:
                raise AgentPlatformNotFoundError("skill was not found")
            selected_version = int(skill["current_version"]) if version is None else _version(version)
            revision = connection.execute(
                """
                select * from agent_skill_revisions
                where skill_id = ? and version = ?
                """,
                (skill_id, selected_version),
            ).fetchone()
        if revision is None:
            raise AgentPlatformNotFoundError("skill revision was not found")
        return _skill_record(skill, revision)

    def list(self, *, client_id: str, include_archived: bool = False) -> list[SkillRecord]:
        client_id = require_client(self.store, client_id)
        status_clause = "" if include_archived else "and status = 'active'"
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                f"""
                select * from agent_skills
                where client_id = ? {status_clause}
                order by name, id
                """,  # nosec B608 - status clause is fixed locally
                (client_id,),
            ).fetchall()
        return [self.get(client_id=client_id, skill_id=str(row["id"])) for row in rows]

    def revisions(self, *, client_id: str, skill_id: str) -> builtins.list[SkillRevision]:
        current = self.get(client_id=client_id, skill_id=skill_id)
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                """
                select * from agent_skill_revisions
                where skill_id = ? order by version desc
                """,
                (current.id,),
            ).fetchall()
        return [_revision(row) for row in rows]

    def archive(self, *, client_id: str, skill_id: str, actor: str) -> SkillRecord:
        current = self.get(client_id=client_id, skill_id=skill_id)
        if current.status == "archived":
            return current
        actor = actor_identifier(actor)
        with self.store._connect() as connection:  # noqa: SLF001
            connection.execute(
                """
                update agent_skills set status = 'archived', updated_at = ?
                where id = ? and client_id = ?
                """,
                (utc_now(), current.id, current.client_id),
            )
        self.store.add_audit_event(
            "agent_skill.archived",
            current.id,
            current.slug,
            client_id=current.client_id,
            approver_id=actor,
        )
        return self.get(client_id=current.client_id, skill_id=current.id)

    def test(
        self,
        *,
        client_id: str,
        skill_id: str,
        sample_input: dict[str, object],
        memory: dict[str, object],
        actor: str,
        version: int | None = None,
    ) -> SkillTestRun:
        skill = self.get(client_id=client_id, skill_id=skill_id, version=version)
        actor = actor_identifier(actor)
        sample_input = cast(dict[str, object], safe_json_value(redact_value(sample_input)))
        memory = cast(dict[str, object], safe_json_value(redact_value(memory), max_bytes=16_384))
        errors = _validate_schema(skill.revision.input_schema, sample_input, path="input")
        tool_catalog = {manifest.action_id: manifest for manifest in self.smart_actions.list()}
        missing_tools = [tool_id for tool_id in skill.revision.allowed_tools if tool_id not in tool_catalog]
        if missing_tools:
            errors.append(f"tool catalog no longer contains: {', '.join(sorted(missing_tools))}")
        rendered = _render(skill.revision.instructions, sample_input, memory)
        unresolved = sorted({match.group(0) for match in _TEMPLATE_RE.finditer(rendered)})
        if unresolved:
            errors.append(f"unresolved template values: {', '.join(unresolved)}")
        tool_plan = [
            {
                "tool_id": tool_id,
                "title": tool_catalog[tool_id].title,
                "risk_level": tool_catalog[tool_id].risk_level,
                "required_role": tool_catalog[tool_id].required_role,
                "approval_required": tool_catalog[tool_id].requires_approval,
                "access_mode": tool_catalog[tool_id].access_mode,
            }
            for tool_id in skill.revision.allowed_tools
            if tool_id in tool_catalog
        ]
        status = "failed" if errors else "passed"
        output: dict[str, object] = {
            "side_effects": False,
            "skill_id": skill.id,
            "skill_version": skill.revision.version,
            "rendered_instructions": redact_text(rendered)[:MAX_SKILL_INSTRUCTIONS],
            "tool_plan": tool_plan,
            "resource_manifest": [
                {
                    "name": resource["name"],
                    "media_type": resource["media_type"],
                    "byte_size": resource["byte_size"],
                    "sha256": resource["sha256"],
                }
                for resource in skill.revision.resources
            ],
            "validation_errors": errors,
        }
        created_at = utc_now()
        with self.store._connect() as connection:  # noqa: SLF001
            cursor = connection.execute(
                """
                insert into agent_skill_test_runs (
                    skill_id, skill_version, client_id, actor, input_digest,
                    status, output_json, error_detail, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill.id,
                    skill.revision.version,
                    skill.client_id,
                    actor,
                    digest_json(sample_input),
                    status,
                    json_dumps(output),
                    "; ".join(errors)[:4_000],
                    created_at,
                ),
            )
            assert cursor.lastrowid is not None
            run_id = int(cursor.lastrowid)
        self.store.add_audit_event(
            "agent_skill.tested",
            skill.id,
            f"version={skill.revision.version} status={status} side_effects=false",
            client_id=skill.client_id,
            approver_id=actor,
        )
        return SkillTestRun(
            id=run_id,
            skill_id=skill.id,
            skill_version=skill.revision.version,
            client_id=skill.client_id,
            actor=actor,
            input_digest=digest_json(sample_input),
            status=status,
            output=output,
            error_detail="; ".join(errors)[:4_000],
            created_at=created_at,
        )

    def test_runs(self, *, client_id: str, skill_id: str, limit: int = 20) -> builtins.list[SkillTestRun]:
        skill = self.get(client_id=client_id, skill_id=skill_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise AgentPlatformError("limit must be an integer between 1 and 100")
        with self.store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                """
                select * from agent_skill_test_runs
                where client_id = ? and skill_id = ?
                order by id desc limit ?
                """,
                (skill.client_id, skill.id, limit),
            ).fetchall()
        return [_test_run(row) for row in rows]

    def _revision_payload(
        self,
        *,
        instructions: str,
        allowed_tools: builtins.list[str],
        input_schema: dict[str, object],
        resources: builtins.list[dict[str, object]],
    ) -> _RevisionPayload:
        instructions = validate_text(
            instructions,
            "instructions",
            minimum=1,
            maximum=MAX_SKILL_INSTRUCTIONS,
            strip=False,
        )
        normalized_tools = _tools(allowed_tools)
        catalog = {manifest.action_id for manifest in self.smart_actions.list()}
        unknown = [tool_id for tool_id in normalized_tools if tool_id not in catalog]
        if unknown:
            raise AgentPlatformError(f"unknown tool IDs: {', '.join(sorted(unknown))}")
        normalized_schema = _schema(input_schema)
        normalized_resources = _resources(resources)
        digest = digest_json(
            {
                "instructions": instructions,
                "allowed_tools": normalized_tools,
                "input_schema": normalized_schema,
                "resources": normalized_resources,
            }
        )
        return {
            "instructions": instructions,
            "allowed_tools": normalized_tools,
            "input_schema": normalized_schema,
            "resources": normalized_resources,
            "digest": digest,
        }


def _insert_revision(
    connection: sqlite3.Connection,
    *,
    skill_id: str,
    version: int,
    instructions: object,
    allowed_tools: object,
    input_schema: object,
    resources: object,
    digest: object,
    actor: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        insert into agent_skill_revisions (
            skill_id, version, instructions, allowed_tools_json,
            input_schema_json, resources_json, digest, created_by, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            skill_id,
            version,
            str(instructions),
            json_dumps(allowed_tools),
            json_dumps(input_schema),
            json_dumps(resources),
            str(digest),
            actor,
            created_at,
        ),
    )


def _skill_record(skill: sqlite3.Row, revision: sqlite3.Row) -> SkillRecord:
    return SkillRecord(
        id=str(skill["id"]),
        client_id=str(skill["client_id"]),
        name=str(skill["name"]),
        slug=str(skill["slug"]),
        description=str(skill["description"]),
        status=str(skill["status"]),
        current_version=int(skill["current_version"]),
        created_by=str(skill["created_by"]),
        created_at=str(skill["created_at"]),
        updated_at=str(skill["updated_at"]),
        revision=_revision(revision),
    )


def _revision(row: sqlite3.Row) -> SkillRevision:
    return SkillRevision(
        skill_id=str(row["skill_id"]),
        version=int(row["version"]),
        instructions=str(row["instructions"]),
        allowed_tools=[str(value) for value in json_loads_list(str(row["allowed_tools_json"]))],
        input_schema=cast(dict[str, object], json_loads_object(str(row["input_schema_json"]))),
        resources=[
            cast(dict[str, object], value)
            for value in json_loads_list(str(row["resources_json"]))
            if isinstance(value, Mapping)
        ],
        digest=str(row["digest"]),
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
    )


def _test_run(row: sqlite3.Row) -> SkillTestRun:
    return SkillTestRun(
        id=int(row["id"]),
        skill_id=str(row["skill_id"]),
        skill_version=int(row["skill_version"]),
        client_id=str(row["client_id"]),
        actor=str(row["actor"]),
        input_digest=str(row["input_digest"]),
        status=str(row["status"]),
        output=cast(dict[str, object], json_loads_object(str(row["output_json"]))),
        error_detail=str(row["error_detail"]),
        created_at=str(row["created_at"]),
    )


def _slug(value: str) -> str:
    normalized = validate_text(value, "slug", minimum=1, maximum=63).lower()
    if not _SLUG_RE.fullmatch(normalized):
        raise AgentPlatformError("slug must use lowercase letters, numbers, and hyphens")
    return normalized


def _version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AgentPlatformError("version must be a positive integer")
    return value


def _tools(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > MAX_SKILL_TOOLS:
        raise AgentPlatformError(f"allowed_tools must contain at most {MAX_SKILL_TOOLS} items")
    normalized: list[str] = []
    for raw in values:
        tool_id = validate_identifier(raw, "tool_id")
        if tool_id not in normalized:
            normalized.append(tool_id)
    return normalized


def _schema(value: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AgentPlatformError("input_schema must be an object")
    normalized = cast(dict[str, object], safe_json_value(value, max_bytes=16_384))
    if normalized.get("type", "object") != "object":
        raise AgentPlatformError("input_schema root type must be object")
    allowed = {"type", "required", "properties", "additionalProperties", "description"}
    unsupported = set(normalized) - allowed
    if unsupported:
        raise AgentPlatformError(
            f"input_schema root contains unsupported fields: {', '.join(sorted(unsupported))}"
        )
    _validate_schema_definition(normalized, path="input_schema")
    return normalized


def _validate_schema_definition(schema: Mapping[str, object], *, path: str) -> None:
    schema_type = schema.get("type", "object")
    if schema_type not in {"object", "array", "string", "integer", "number", "boolean"}:
        raise AgentPlatformError(f"{path}.type is unsupported")
    properties = schema.get("properties", {})
    if schema_type == "object":
        if not isinstance(properties, Mapping) or len(properties) > 64:
            raise AgentPlatformError(f"{path}.properties must be an object with at most 64 entries")
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise AgentPlatformError(f"{path}.required must be an array of property names")
        if any(item not in properties for item in required):
            raise AgentPlatformError(f"{path}.required references an unknown property")
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                raise AgentPlatformError(f"{path}.properties is malformed")
            _validate_schema_definition(child, path=f"{path}.{name}")
    if schema_type == "array":
        items = schema.get("items")
        if items is not None:
            if not isinstance(items, Mapping):
                raise AgentPlatformError(f"{path}.items must be an object")
            _validate_schema_definition(items, path=f"{path}[]")


def _resources(values: list[dict[str, object]]) -> list[dict[str, object]]:
    if not isinstance(values, list) or len(values) > MAX_SKILL_RESOURCES:
        raise AgentPlatformError(f"resources must contain at most {MAX_SKILL_RESOURCES} files")
    normalized: list[dict[str, object]] = []
    names: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise AgentPlatformError("each resource must be an object")
        name = validate_text(str(raw.get("name", "")), "resource name", minimum=1, maximum=120)
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise AgentPlatformError("resource names must be plain filenames")
        if name.casefold() in names:
            raise AgentPlatformError("resource names must be unique")
        names.add(name.casefold())
        media_type = str(raw.get("media_type", "text/plain")).strip().lower()
        if media_type not in _RESOURCE_MEDIA_TYPES:
            raise AgentPlatformError("resource media_type is unsupported")
        content = validate_text(
            str(raw.get("content", "")),
            "resource content",
            maximum=MAX_RESOURCE_BYTES,
            strip=False,
        )
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_RESOURCE_BYTES:
            raise AgentPlatformError(f"resource content exceeds {MAX_RESOURCE_BYTES} bytes")
        if media_type == "application/json":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                raise AgentPlatformError(f"resource {name} contains invalid JSON") from exc
        normalized.append(
            {
                "name": name,
                "media_type": media_type,
                "content": content,
                "byte_size": len(encoded),
                "sha256": digest_json({"content": content}),
            }
        )
    return normalized


def _validate_schema(schema: Mapping[str, object], value: object, *, path: str) -> list[str]:
    errors: list[str] = []
    schema_type = schema.get("type", "object")
    type_checks = {
        "object": lambda item: isinstance(item, Mapping),
        "array": lambda item: isinstance(item, Sequence) and not isinstance(item, (str, bytes)),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }
    check = type_checks.get(str(schema_type))
    if check is None or not check(value):
        return [f"{path} must be {schema_type}"]
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path} must be one of the declared enum values")
    if schema_type == "object" and isinstance(value, Mapping):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if isinstance(required, list):
            for name in required:
                if name not in value:
                    errors.append(f"{path}.{name} is required")
        if isinstance(properties, Mapping):
            for name, child in properties.items():
                if name in value and isinstance(child, Mapping):
                    errors.extend(_validate_schema(child, value[name], path=f"{path}.{name}"))
        if schema.get("additionalProperties") is False and isinstance(properties, Mapping):
            for name in value:
                if name not in properties:
                    errors.append(f"{path}.{name} is not allowed")
    elif schema_type == "array" and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path} must contain at least {minimum} items")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{path} must contain at most {maximum} items")
        child = schema.get("items")
        if isinstance(child, Mapping):
            for index, item in enumerate(value):
                errors.extend(_validate_schema(child, item, path=f"{path}[{index}]"))
    elif schema_type == "string" and isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path} must contain at least {minimum} characters")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{path} must contain at most {maximum} characters")
    return errors[:100]


def _render(template: str, sample_input: Mapping[str, object], memory: Mapping[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        source = sample_input if match.group(1) == "input" else memory
        value: object = source
        for segment in match.group(2).split("."):
            if not isinstance(value, Mapping) or segment not in value:
                return match.group(0)
            value = value[segment]
        if isinstance(value, (dict, list)):
            return json_dumps(value)
        return str(value)

    return _TEMPLATE_RE.sub(replace, template)


__all__ = [
    "MAX_SKILL_INSTRUCTIONS",
    "SkillRecord",
    "SkillRevision",
    "SkillService",
    "SkillTestRun",
]
