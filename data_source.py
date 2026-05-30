from __future__ import annotations

from typing import Any

from providers import DataSourceError, DatasetRequest, get_provider, list_providers


def fetch_history(
    symbol: str,
    interval: str = "1d",
    years: int = 5,
    refresh: bool = False,
    provider: str = "yahoo",
    file_path: str | None = None,
    market: str | None = None,
    timezone: str = "UTC",
    session: str | None = None,
):
    request = DatasetRequest(
        provider=provider,
        symbol=symbol.strip() if symbol else "",
        interval=interval,
        years=years,
        refresh=refresh,
        file_path=file_path,
        market=market,
        timezone=timezone,
        session=session,
    )
    response = get_provider(provider).fetch(request)
    combined_source = dict(response.source_info)
    combined_source["dataset"] = response.dataset_info
    return response.df, combined_source


def available_providers() -> dict[str, dict[str, Any]]:
    return list_providers()


__all__ = ["DataSourceError", "available_providers", "fetch_history"]
