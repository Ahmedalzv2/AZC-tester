from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from data_source import available_providers


def test_provider_registry_exposes_metadata() -> None:
    providers = available_providers()
    assert providers["yahoo"]["supports_remote"] is True
    assert providers["local_file"]["supports_files"] is True
    assert providers["azc_fixture"]["supports_catalog"] is True
    assert "notes" in providers["yahoo"]
