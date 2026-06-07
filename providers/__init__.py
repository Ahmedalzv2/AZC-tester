from __future__ import annotations

from providers.alphavantage import AlphaVantageProvider
from providers.azc_fixture import AzcFixtureProvider
from providers.base import BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse
from providers.local_file import LocalFileProvider
from providers.binance import BinanceProvider
from providers.yahoo import YahooFinanceProvider

PROVIDERS: dict[str, BaseDataProvider] = {
    YahooFinanceProvider.name: YahooFinanceProvider(),
    BinanceProvider.name: BinanceProvider(),
    LocalFileProvider.name: LocalFileProvider(),
    AzcFixtureProvider.name: AzcFixtureProvider(),
    AlphaVantageProvider.name: AlphaVantageProvider(),
}
# StooqProvider exists (providers/stooq.py) but Stooq now gates the CSV API behind
# an apikey, so it's not registered. yahoo period='max' is the free long-history source.


def get_provider(name: str) -> BaseDataProvider:
    provider = PROVIDERS.get(name)
    if not provider:
        raise DataSourceError(f"Unknown data provider: {name}")
    return provider


def list_providers() -> dict[str, dict[str, object]]:
    return {name: provider.describe() for name, provider in PROVIDERS.items()}


__all__ = [
    "BaseDataProvider",
    "DataSourceError",
    "DatasetRequest",
    "DatasetResponse",
    "PROVIDERS",
    "get_provider",
    "list_providers",
]
