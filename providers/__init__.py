from __future__ import annotations

from providers.azc_fixture import AzcFixtureProvider
from providers.base import BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse
from providers.local_file import LocalFileProvider
from providers.yahoo import YahooFinanceProvider

PROVIDERS = {
    YahooFinanceProvider.name: YahooFinanceProvider(),
    LocalFileProvider.name: LocalFileProvider(),
    AzcFixtureProvider.name: AzcFixtureProvider(),
}


def get_provider(name: str) -> BaseDataProvider:
    provider = PROVIDERS.get(name)
    if not provider:
        raise DataSourceError(f"Unknown data provider: {name}")
    return provider


def list_providers() -> dict[str, dict[str, object]]:
    return {
        name: {
            "label": provider.label,
            "supports_files": provider.supports_files,
        }
        for name, provider in PROVIDERS.items()
    }


__all__ = [
    "BaseDataProvider",
    "DataSourceError",
    "DatasetRequest",
    "DatasetResponse",
    "PROVIDERS",
    "get_provider",
    "list_providers",
]
