from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

import tests.power_platform_support as power_platform_support
from tests.power_platform_support import CANONICAL_INPUT_ARTIFACT, assert_matches_golden
from wait_local_agent.power_platform_package import build_power_platform_package

_PROVEN_ROOT = Path(__file__).parent / "power_platform_reference" / "proven"


def _emitted_files() -> list[dict[str, object]]:
    package = build_power_platform_package(
        client_id="acme",
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory="/tmp/wla-employee-onboarding-source",
        artifacts=[CANONICAL_INPUT_ARTIFACT],
    )
    return cast(list[dict[str, object]], package["files"])


def _xml_files(files: Sequence[Mapping[str, object]]) -> dict[str, str]:
    return {
        Path(cast(str, file["path"])).name: cast(str, file["content"])
        for file in files
        if cast(str, file["path"]).endswith(".xml")
    }


def _element_tag_paths(xml: str) -> set[tuple[str, ...]]:
    root = ET.fromstring(xml)
    paths: set[tuple[str, ...]] = set()

    def visit(element: ET.Element, parent: tuple[str, ...]) -> None:
        path = (*parent, element.tag)
        paths.add(path)
        for child in element:
            visit(child, path)

    visit(root, ())
    return paths


def test_emitted_tree_matches_golden() -> None:
    assert_matches_golden(_emitted_files(), "employee_onboarding")


def test_emitted_xml_covers_every_element_the_proven_reference_carries() -> None:
    emitted = _xml_files(_emitted_files())
    proven = {
        filename: (_PROVEN_ROOT / filename).read_text(encoding="utf-8")
        for filename in ("Customizations.xml", "Solution.xml")
    }
    emitted_paths = {
        (filename, *path)
        for filename, xml in emitted.items()
        if filename in proven
        for path in _element_tag_paths(xml)
    }
    proven_paths = {
        (filename, *path)
        for filename, xml in proven.items()
        for path in _element_tag_paths(xml)
    }

    assert proven_paths <= emitted_paths


def test_every_emitted_xml_file_is_well_formed() -> None:
    for xml in _xml_files(_emitted_files()).values():
        ET.fromstring(xml)


def test_golden_regeneration_prints_diff_before_overwriting(tmp_path: Path, monkeypatch, capsys) -> None:
    golden_root = tmp_path / "golden"
    golden_file = golden_root / "fixture" / "Other" / "Solution.xml"
    golden_file.parent.mkdir(parents=True)
    golden_file.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(power_platform_support, "_GOLDEN_ROOT", golden_root)
    monkeypatch.setenv("WAIT_REGENERATE_GOLDEN", "1")

    assert_matches_golden(
        [{"path": "Other/Solution.xml", "content": "new\n"}],
        "fixture",
    )

    output = capsys.readouterr().out
    assert "--- golden/Other/Solution.xml" in output
    assert "+++ generated/Other/Solution.xml" in output
    assert "-old" in output
    assert "+new" in output
    assert golden_file.read_text(encoding="utf-8") == "new\n"


def test_golden_regeneration_refuses_ci_without_mutating_fixture(tmp_path: Path, monkeypatch) -> None:
    golden_root = tmp_path / "golden"
    golden_file = golden_root / "fixture" / "Other" / "Solution.xml"
    golden_file.parent.mkdir(parents=True)
    golden_file.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(power_platform_support, "_GOLDEN_ROOT", golden_root)
    monkeypatch.setenv("WAIT_REGENERATE_GOLDEN", "1")
    monkeypatch.setenv("CI", "1")

    with pytest.raises(RuntimeError, match="disabled when CI is set"):
        assert_matches_golden(
            [{"path": "Other/Solution.xml", "content": "new\n"}],
            "fixture",
        )

    assert golden_file.read_text(encoding="utf-8") == "old\n"
