from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

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
