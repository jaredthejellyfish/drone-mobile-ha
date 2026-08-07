"""Structural tests for the DroneMobile custom integration."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from custom_components.drone_mobile.const import DOMAIN, PLATFORMS

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / DOMAIN


def test_manifest_is_hacs_compatible() -> None:
    """The manifest contains the metadata and pinned dependency HACS needs."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())

    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "hub"
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["requirements"] == ["drone_mobile==0.4.1"]
    assert manifest["version"] == "0.1.5"
    assert manifest["codeowners"] == ["@jaredthejellyfish"]
    assert manifest["documentation"].endswith("/jaredthejellyfish/drone-mobile-ha")
    assert manifest["issue_tracker"].endswith("/drone-mobile-ha/issues")


def test_all_platforms_import_against_current_home_assistant() -> None:
    """All configured platforms import with the development HA version."""
    importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    for platform in PLATFORMS:
        importlib.import_module(f"custom_components.{DOMAIN}.{platform}")


def test_english_translation_matches_source_strings() -> None:
    """The checked-in English translation mirrors source strings."""
    source = json.loads((INTEGRATION / "strings.json").read_text())
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text())

    assert english == source


def test_hacs_metadata() -> None:
    """HACS metadata identifies this repository as DroneMobile."""
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["name"] == "DroneMobile"
