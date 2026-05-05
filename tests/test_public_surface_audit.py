from __future__ import annotations

from pathlib import Path

from scripts import public_surface_audit


def test_public_surface_audit_treats_extensionless_text_as_scannable(tmp_path: Path) -> None:
    notice = tmp_path / "NOTICE"
    notice.write_text("plain text", encoding="utf-8")

    assert public_surface_audit.is_text_file(notice) is True


def test_public_surface_audit_skips_binary_files(tmp_path: Path) -> None:
    binary = tmp_path / "binary-file"
    binary.write_bytes(b"\0\1\2")

    assert public_surface_audit.is_text_file(binary) is False

