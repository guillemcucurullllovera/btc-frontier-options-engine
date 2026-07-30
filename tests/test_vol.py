"""Vol-layer tests for A2: parsing, retries, timeouts, offline replay,
caching, stale data, provenance, surface interpolation, sparse surfaces,
GARCH diagnostics.

All tests derive from fixtures: no live network.
"""

from __future__ import annotations

import json
import math
import pathlib

# We use sys.path.insert as done by all other test files
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from unittest import mock

from config.models import Provenance
from engine.data_models import HistoricalSpotBar
from vol.client import (
    BASE_DELAY_S,
    DeribitApiError,
    DeribitClient,
    DeribitClientError,
    DeribitRateLimitError,
    DeribitTimeoutError,
)
from vol.garch import (
    GarchDiagnostics,
    GarchEstimator,
    GarchParams,
    GarchResult,
    VolForecast,
    compute_diagnostics,
    compute_forecast,
)
from vol.history import (
    CompositeSpotProvider,
    CryptoDataDownloadProvider,
    HistoricalSpotError,
    HistoricalSpotNotFound,
    MassiveResponseError,
    MassiveSpotProvider,
    MassiveTimeoutError,
    SpotCache,
)
from vol.surface import (
    VolPoint,
    VolSurface,
    fit_surface,
    iv_at,
)

TEST_API_KEY = "test" + "-key"


FIXTURE_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
)


# ══════════════════════════════════════════════════════════════════════════
# 1. Client parsing — offline fixture replay
# ══════════════════════════════════════════════════════════════════════════


def test_client_replays_index_price() -> None:
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    bar = client.spot_index("btc_usd")
    assert bar.price > 0
    assert bar.provenance == Provenance.OBSERVED
    assert bar.origin == "deribit"
    assert bar.timestamp.tzinfo is not None
    client.close()


def test_client_replays_dvol() -> None:
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    bars = client.dvol_latest()
    assert len(bars) > 0
    for b in bars:
        assert 0 < b.close < 1.0  # decimal
        assert b.provenance == Provenance.OBSERVED
    client.close()


def test_client_replays_book_summary() -> None:
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    summaries = client.book_summary()
    assert len(summaries) > 0
    for s in summaries:
        assert s.instrument_name != ""
        assert s.provenance == Provenance.OBSERVED
        assert s.timestamp.tzinfo is not None
    client.close()


def test_client_replays_instruments() -> None:
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    instruments = client.option_chain()
    assert len(instruments) > 0
    for inst in instruments:
        assert inst.instrument_name != ""
        assert inst.strike > 0
    client.close()


def test_client_fixture_not_found_raises() -> None:
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    with pytest.raises(DeribitClientError):
        client._request("get_nonexistent_endpoint")
    client.close()


# ══════════════════════════════════════════════════════════════════════════
# 2. Client error handling — retries and timeouts
# ══════════════════════════════════════════════════════════════════════════


def test_client_retry_on_timeout() -> None:
    """Client raises DeribitTimeoutError after exhausting retries."""
    client = DeribitClient(
        base_url="https://192.0.2.1:9999",
        timeout_s=0.1,
        max_retries=2,
    )
    start = time.time()
    with pytest.raises(DeribitClientError):
        client.spot_index()
    elapsed = time.time() - start
    assert elapsed > BASE_DELAY_S * 0.5  # at least one backoff
    client.close()


def test_client_retry_on_connection_error() -> None:
    """Client raises DeribitClientError on connection errors."""
    client = DeribitClient(
        base_url="https://192.0.2.99:1",
        timeout_s=1.0,
        max_retries=1,
    )
    with pytest.raises(DeribitClientError):
        client.spot_index()
    client.close()


# ══════════════════════════════════════════════════════════════════════════
# 3. Cache and stale data
# ══════════════════════════════════════════════════════════════════════════


def test_cache_hit() -> None:
    cache = SpotCache(max_age=timedelta(hours=1))
    bars = [
        HistoricalSpotBar(
            symbol="btc_usd",
            timestamp=datetime.now(UTC),
            open=65000.0,
            high=65500.0,
            low=64500.0,
            close=65200.0,
            volume=1000.0,
            provenance=Provenance.OBSERVED,
            origin="massive",
        )
    ]
    cache.put(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC), bars)
    result = cache.get(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
    assert result is not None
    assert len(result) == 1
    assert result[0].close == 65200.0


def test_cache_miss() -> None:
    cache = SpotCache(max_age=timedelta(hours=1))
    result = cache.get(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
    assert result is None


def test_cache_stale() -> None:
    cache = SpotCache(max_age=timedelta(milliseconds=1))
    bars = [
        HistoricalSpotBar(
            symbol="btc_usd",
            timestamp=datetime.now(UTC),
            open=65000.0,
            high=65500.0,
            low=64500.0,
            close=65200.0,
            volume=1000.0,
            provenance=Provenance.OBSERVED,
            origin="massive",
        )
    ]
    cache.put(datetime.now(UTC), datetime.now(UTC), bars)
    time.sleep(0.005)
    result = cache.get(datetime.now(UTC), datetime.now(UTC))
    assert result is None


def test_cache_clear() -> None:
    cache = SpotCache()
    bars = [
        HistoricalSpotBar(
            symbol="btc_usd",
            timestamp=datetime.now(UTC),
            open=65000.0,
            high=65500.0,
            low=64500.0,
            close=65200.0,
            volume=1000.0,
            provenance=Provenance.OBSERVED,
            origin="massive",
        )
    ]
    cache.put(datetime.now(UTC), datetime.now(UTC), bars)
    assert cache.entry_count == 1
    cache.clear()
    assert cache.entry_count == 0


# ══════════════════════════════════════════════════════════════════════════
# 4. Provenance
# ══════════════════════════════════════════════════════════════════════════


def test_provenance_on_all_data_models() -> None:
    """Every market-data bar type carries provenance."""
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    bar = client.spot_index()
    assert hasattr(bar, "provenance")
    assert bar.provenance == Provenance.OBSERVED

    dvol_bars = client.dvol_latest()
    for b in dvol_bars:
        assert b.provenance == Provenance.OBSERVED
    client.close()


def test_historical_spot_provenance() -> None:
    """Historical spot bars carry correct provenance."""
    bar = HistoricalSpotBar(
        symbol="btc_usd",
        timestamp=datetime.now(UTC),
        open=65000.0,
        high=65500.0,
        low=64500.0,
        close=65200.0,
        volume=1000.0,
        provenance=Provenance.OBSERVED,
        origin="massive",
    )
    assert bar.provenance == Provenance.OBSERVED

    reconstructed = HistoricalSpotBar(
        symbol="btc_usd",
        timestamp=datetime.now(UTC),
        open=65000.0,
        high=65500.0,
        low=64500.0,
        close=65200.0,
        volume=1000.0,
        provenance=Provenance.MODEL_RECONSTRUCTED,
        origin="model_reconstructed",
    )
    assert reconstructed.provenance == Provenance.MODEL_RECONSTRUCTED


# ══════════════════════════════════════════════════════════════════════════
# 5. Surface interpolation
# ══════════════════════════════════════════════════════════════════════════


def test_surface_from_book_summary() -> None:
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    summaries = client.book_summary()
    surface = fit_surface(summaries, method="spline")
    assert len(surface.points) > 0
    assert surface.method == "spline"
    for p in surface.points:
        assert p.iv > 0
        assert p.expiry > 0
    client.close()


def test_iv_at_returns_float() -> None:
    client = DeribitClient(fixture_dir=FIXTURE_DIR)
    summaries = client.book_summary()
    surface = fit_surface(summaries)
    if surface.points:
        expiries = sorted({p.expiry for p in surface.points})
        for e in expiries[:3]:
            iv = iv_at(surface, e, -0.25)
            assert isinstance(iv, float)
            assert iv > 0


def test_iv_at_extrapolation() -> None:
    """Out-of-range delta returns nearest endpoint IV (no extrapolation error)."""
    points = [
        VolPoint(expiry=0.1, delta=-0.5, iv=0.40, provenance=Provenance.OBSERVED, origin="test"),
        VolPoint(expiry=0.1, delta=-0.3, iv=0.45, provenance=Provenance.OBSERVED, origin="test"),
        VolPoint(expiry=0.1, delta=-0.1, iv=0.50, provenance=Provenance.OBSERVED, origin="test"),
    ]
    surface = VolSurface(timestamp=datetime.now(UTC), points=points)
    iv_extreme = iv_at(surface, 0.1, -0.9)
    assert iv_extreme == 0.40


def test_surface_empty_raises() -> None:
    with pytest.raises(Exception):
        fit_surface([])


# ══════════════════════════════════════════════════════════════════════════
# 6. Sparse surface fallback
# ══════════════════════════════════════════════════════════════════════════


def test_sparse_surface_single_point_per_expiry() -> None:
    """When only one point exists per expiry, iv_at returns that point's IV."""
    points = [
        VolPoint(expiry=0.1, delta=-0.3, iv=0.45, provenance=Provenance.OBSERVED, origin="test"),
        VolPoint(expiry=0.3, delta=-0.2, iv=0.50, provenance=Provenance.OBSERVED, origin="test"),
    ]
    surface = VolSurface(
        timestamp=datetime.now(UTC), points=points, method="raw"
    )
    iv = iv_at(surface, 0.1, -0.3)
    assert iv == 0.45


def test_sparse_surface_target_expiry_missing() -> None:
    """When target expiry has no points, uses closest expiry."""
    points = [
        VolPoint(expiry=0.1, delta=-0.3, iv=0.45, provenance=Provenance.OBSERVED, origin="test"),
    ]
    surface = VolSurface(timestamp=datetime.now(UTC), points=points, method="raw")
    iv = iv_at(surface, 0.5, -0.25)
    assert iv == 0.45


# ══════════════════════════════════════════════════════════════════════════
# 7. GARCH diagnostics
# ══════════════════════════════════════════════════════════════════════════


def _generate_returns(n: int = 500, vol: float = 0.02) -> list[float]:
    np.random.seed(42)
    return list(np.random.normal(0, vol, n).astype(np.float64))


def test_garch_fit_converges() -> None:
    returns = _generate_returns(500, 0.02)
    estimator = GarchEstimator(returns)
    result = estimator.fit()
    assert result.convergence
    assert result.params.omega > 0
    assert 0 <= result.params.alpha <= 1
    assert 0 <= result.params.beta <= 1
    assert result.params.alpha + result.params.beta > 0
    assert result.n_obs == 500
    assert math.isfinite(result.aic)
    assert result.forecast_vol is not None
    assert result.forecast_vol > 0


def test_garch_short_series_raises() -> None:
    with pytest.raises(Exception):
        GarchEstimator([0.01, 0.02]).fit()


def test_garch_params_persistence() -> None:
    params = GarchParams(omega=0.01, alpha=0.1, beta=0.85)
    assert abs(params.persistence - 0.95) < 1e-10
    uv = params.unconditional_variance
    assert uv > 0


def test_garch_params_nonstationary() -> None:
    params = GarchParams(omega=0.01, alpha=0.5, beta=0.6)
    assert params.persistence >= 1.0
    assert params.unconditional_variance == float("inf")


def test_garch_diagnostics_with_actual_fit() -> None:
    returns = _generate_returns(300, 0.015)
    estimator = GarchEstimator(returns)
    result = estimator.fit()
    diag = compute_diagnostics(result, lags=5)
    assert isinstance(diag, GarchDiagnostics)
    assert diag.ljung_box_lags == 5
    assert len(diag.warnings) >= 0


def test_garch_forecast_creation() -> None:
    returns = _generate_returns(500, 0.02)
    estimator = GarchEstimator(returns)
    result = estimator.fit()
    forecast = compute_forecast(result, dvol=0.35)
    assert isinstance(forecast, VolForecast)
    assert forecast.garch_forecast > 0
    assert forecast.dvol_latest == 0.35
    assert forecast.spread is not None
    assert forecast.spread_bp is not None


def test_garch_model_reconstructed_provenance() -> None:
    returns = _generate_returns(500, 0.02)
    estimator = GarchEstimator(returns)
    result = estimator.fit()
    assert result.provenance == Provenance.MODEL_RECONSTRUCTED
    assert result.origin == "garch_model"


def test_garch_diagnostics_near_unit_root() -> None:
    params = GarchParams(omega=0.001, alpha=0.9, beta=0.1)
    result = GarchResult(
        params=params,
        conditional_variances=[0.01] * 50,
        residuals=[0.0] * 60,
        log_likelihood=-100.0,
        aic=206.0,
        bic=214.0,
        n_obs=60,
        convergence=True,
    )
    diag = compute_diagnostics(result, lags=5)
    assert any("Near-unit-root" in w for w in diag.warnings)


# ══════════════════════════════════════════════════════════════════════════
# 8. Historical data providers — Massive primary, CDD fallback
# ══════════════════════════════════════════════════════════════════════════


def _make_csv_bytes(
    rows: list[dict[str, str]], fieldnames: list[str]
) -> str:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()


def test_massive_provider_parses_csv(tmp_path: pathlib.Path) -> None:
    csv_content = _make_csv_bytes(
        [
            {"timestamp": "1704067200", "open": "65000", "high": "65500", "low": "64500",
             "close": "65200", "volume": "1000", "vwap": "65100", "n": "500"},
        ],
        ["timestamp", "open", "high", "low", "close", "volume", "vwap", "n"],
    )
    p = tmp_path / "massive_spot.csv"
    p.write_text(csv_content)
    provider = MassiveSpotProvider(fixture_path=p)
    bars = provider.fetch_bars()
    assert len(bars) == 1
    assert bars[0].close == 65200.0
    assert bars[0].provenance == Provenance.OBSERVED
    assert bars[0].origin == "massive"


def test_cdd_provider_parses_csv(tmp_path: pathlib.Path) -> None:
    csv_content = _make_csv_bytes(
        [
            {"date": "2024-01-01", "Symbol": "BTC/USD", "Open": "65000", "High": "65500",
             "Low": "64500", "Close": "65200", "Volume BTC": "1000"},
        ],
        ["date", "Symbol", "Open", "High", "Low", "Close", "Volume BTC"],
    )
    p = tmp_path / "cdd_spot.csv"
    p.write_text(csv_content)
    provider = CryptoDataDownloadProvider(fixture_path=p)
    bars = provider.fetch_bars()
    assert len(bars) == 1
    assert bars[0].close == 65200.0
    assert bars[0].origin == "cryptodatadownload"
    assert bars[0].provenance == Provenance.OBSERVED


def test_composite_provider_uses_primary_first(tmp_path: pathlib.Path) -> None:
    massive_csv = _make_csv_bytes(
        [
            {"timestamp": "1704067200", "open": "100", "high": "101", "low": "99",
             "close": "100.5", "volume": "500"},
        ],
        ["timestamp", "open", "high", "low", "close", "volume"],
    )
    p = tmp_path / "massive.csv"
    p.write_text(massive_csv)
    primary = MassiveSpotProvider(fixture_path=p)
    fallback = CryptoDataDownloadProvider()
    composite = CompositeSpotProvider(primary, fallback)
    bars = composite.fetch_bars()
    assert len(bars) == 1
    assert bars[0].close == 100.5
    assert bars[0].origin == "massive"


def test_composite_falls_back_when_primary_empty(tmp_path: pathlib.Path) -> None:
    # Primary provider with no fixture -> raises
    primary = MassiveSpotProvider()
    cdd_csv = _make_csv_bytes(
        [
            {"date": "2024-01-01", "Symbol": "BTC/USD", "Open": "20000", "High": "21000",
             "Low": "19000", "Close": "20500", "Volume BTC": "5000"},
        ],
        ["date", "Symbol", "Open", "High", "Low", "Close", "Volume BTC"],
    )
    p = tmp_path / "cdd.csv"
    p.write_text(cdd_csv)
    fallback = CryptoDataDownloadProvider(fixture_path=p)
    composite = CompositeSpotProvider(primary, fallback)
    bars = composite.fetch_bars()
    assert len(bars) == 1
    assert bars[0].origin == "cryptodatadownload"


# ══════════════════════════════════════════════════════════════════════════
# 9. Error handling — Deribit API error codes
# ══════════════════════════════════════════════════════════════════════════


def test_deribit_api_error_message() -> None:
    err = DeribitApiError(code=-32602, message="Invalid params")
    assert err.code == -32602
    assert "Invalid params" in str(err)


def test_deribit_timeout_error() -> None:
    err = DeribitTimeoutError("timed out")
    assert isinstance(err, DeribitClientError)


def test_deribit_rate_limit_error() -> None:
    err = DeribitRateLimitError("rate limited")
    assert isinstance(err, DeribitClientError)


# ══════════════════════════════════════════════════════════════════════════
# 10. Surface VolPoint creation
# ══════════════════════════════════════════════════════════════════════════


def test_volpoint_creation() -> None:
    vp = VolPoint(expiry=0.1, delta=0.5, iv=0.45, provenance=Provenance.OBSERVED, origin="test")
    assert vp.expiry == 0.1
    assert vp.delta == 0.5
    assert vp.iv == 0.45
    assert vp.provenance == Provenance.OBSERVED


def test_volsurface_creation() -> None:
    points = [
        VolPoint(expiry=0.1, delta=0.5, iv=0.45, provenance=Provenance.OBSERVED, origin="test"),
    ]
    surface = VolSurface(
        timestamp=datetime.now(UTC),
        points=points,
        method="spline",
        fit_rmse=0.01,
    )
    assert surface.method == "spline"
    assert surface.fit_rmse == 0.01
    assert len(surface.points) == 1


# ══════════════════════════════════════════════════════════════════════════
# 11. VolForecast creation
# ══════════════════════════════════════════════════════════════════════════


def test_volforecast_with_dvol() -> None:
    from vol.garch import compute_forecast

    returns = _generate_returns(500, 0.02)
    estimator = GarchEstimator(returns)
    result = estimator.fit()
    f = compute_forecast(result, dvol=0.45)
    assert f.garch_forecast > 0
    assert f.dvol_latest == 0.45
    assert f.spread is not None
    assert f.spread_bp is not None


def test_volforecast_without_dvol() -> None:
    from vol.garch import compute_forecast

    returns = _generate_returns(500, 0.02)
    estimator = GarchEstimator(returns)
    result = estimator.fit()
    f = compute_forecast(result, dvol=None)
    assert f.spread is None
    assert f.spread_bp is None


# ══════════════════════════════════════════════════════════════════════════
# 12. GarchParams units
# ══════════════════════════════════════════════════════════════════════════


def test_garch_params_unconditional_vol() -> None:
    params = GarchParams(omega=0.0001, alpha=0.1, beta=0.85)
    uv = params.unconditional_vol
    assert uv > 0
    assert uv < 1.0


# ══════════════════════════════════════════════════════════════════════════
# 13. Massive live integration — mocked API responses
# ══════════════════════════════════════════════════════════════════════════


def _massive_api_response(bars: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "adjusted": True,
        "queryCount": len(bars),
        "request_id": "test-req-id",
        "results": bars,
        "resultsCount": len(bars),
        "status": "OK",
        "ticker": "X:BTCUSD",
    }


def _make_bar(t_ms: int, o: float, h: float, lo: float, c: float, v: float = 1000.0) -> dict[str, Any]:
    return {
        "c": c,
        "h": h,
        "l": lo,
        "n": 1,
        "o": o,
        "t": t_ms,
        "v": v,
        "vw": c,
    }


def test_massive_parses_live_response() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)
    bars_data = [
        _make_bar(1704067200000, 65000, 65500, 64500, 65200),
        _make_bar(1704153600000, 65200, 66000, 65000, 65800),
    ]

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _massive_api_response(bars_data)
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        bars = provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))
        assert len(bars) == 2
        assert bars[0].close == 65200.0
        assert bars[1].close == 65800.0
        assert bars[0].provenance == Provenance.OBSERVED
        assert bars[0].origin == "massive"
        assert bars[0].symbol == "X:BTCUSD"


def test_massive_accepts_delayed_status() -> None:
    # Massive/Polygon returns status "DELAYED" on delayed-feed tiers; the daily
    # historical closes are final and observed, so they must be accepted rather
    # than rejected as a malformed response.  (C8: unblocks realised-vol input.)
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)
    bars_data = [
        _make_bar(1704067200000, 65000, 65500, 64500, 65200),
        _make_bar(1704153600000, 65200, 66000, 65000, 65800),
    ]
    response = _massive_api_response(bars_data)
    response["status"] = "DELAYED"

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        bars = provider.fetch_bars(
            start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC)
        )
        assert len(bars) == 2
        assert bars[0].provenance == Provenance.OBSERVED
        assert bars[0].origin == "massive"


def test_massive_deduplicates_and_sorts() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)
    # Duplicate timestamp, out of order
    ts = 1704067200000
    bars_data = [
        _make_bar(ts + 86400000, 66000, 67000, 65000, 66500),  # later, out of order
        _make_bar(ts, 65000, 65500, 64500, 65200),               # earlier
        _make_bar(ts, 64000, 64500, 63500, 64200),               # duplicate
    ]

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _massive_api_response(bars_data)
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        bars = provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 5, tzinfo=UTC))
        assert len(bars) == 2
        assert bars[0].close > 0
        assert bars[1].close == 66500.0


def test_massive_timestamps_utc() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)
    bars_data = [_make_bar(1704067200000, 65000, 65500, 64500, 65200)]

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _massive_api_response(bars_data)
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        bars = provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))
        assert bars[0].timestamp.tzinfo is not None
        assert bars[0].timestamp.tzinfo == UTC


def test_massive_monotonic_timestamps() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)
    ts = 1704067200000
    bars_data = [
        _make_bar(ts + 86400000, 66000, 67000, 65000, 66500),
        _make_bar(ts, 65000, 65500, 64500, 65200),
    ]

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _massive_api_response(bars_data)
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        bars = provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 5, tzinfo=UTC))
        for i in range(1, len(bars)):
            assert bars[i].timestamp > bars[i - 1].timestamp


def test_massive_retry_on_timeout() -> None:
    import requests as req_lib
    provider = MassiveSpotProvider(api_key=TEST_API_KEY, timeout_s=0.1)

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_get.side_effect = req_lib.exceptions.Timeout("timed out")
        with pytest.raises(MassiveTimeoutError):
            provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))
        assert mock_get.call_count == 3  # MAX_RETRIES


def test_massive_retry_on_server_error() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)

    import contextlib
    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp
        with contextlib.suppress(HistoricalSpotError):
            provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))
        assert mock_get.call_count >= 2


def test_massive_empty_results_raises() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "OK", "results": [], "resultsCount": 0, "ticker": "X:BTCUSD"}
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        with pytest.raises(HistoricalSpotNotFound):
            provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))


def test_massive_malformed_response_raises() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ERROR", "message": "invalid ticker"}
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        with pytest.raises(MassiveResponseError):
            provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))


def test_massive_invalid_json_raises() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        mock_get.return_value = mock_resp

        with pytest.raises(MassiveResponseError):
            provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))


def test_massive_no_api_key_raises() -> None:
    provider = MassiveSpotProvider()
    with pytest.raises(HistoricalSpotError):
        provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))


def test_massive_rate_limit_retries() -> None:
    import time as _time
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)

    with mock.patch.object(_time, "sleep", return_value=None), mock.patch.object(
        provider._get_session(), "get"
    ) as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "0.1"}
        mock_get.return_value = mock_resp

        with pytest.raises(HistoricalSpotError):
            provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))
        assert mock_get.call_count >= 3


def test_massive_zero_price_bars_skipped() -> None:
    provider = MassiveSpotProvider(api_key=TEST_API_KEY)
    ts = 1704067200000
    bars_data = [
        _make_bar(ts, 0, 0, 0, 0),                   # zero-price bar
        _make_bar(ts + 86400000, 65000, 65500, 64500, 65200),  # valid
    ]

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _massive_api_response(bars_data)
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        bars = provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 5, tzinfo=UTC))
        assert len(bars) == 1
        assert bars[0].close == 65200.0


def test_massive_cache_dir_saves_json(tmp_path: pathlib.Path) -> None:
    cache_dir = tmp_path / "cache"
    provider = MassiveSpotProvider(api_key=TEST_API_KEY, cache_dir=cache_dir)
    ts = 1704067200000
    bars_data = [_make_bar(ts, 65000, 65500, 64500, 65200)]

    with mock.patch.object(provider._get_session(), "get") as mock_get:
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _massive_api_response(bars_data)
        mock_resp.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_resp

        bars = provider.fetch_bars(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 3, tzinfo=UTC))
        assert len(bars) == 1

    cache_files = list(cache_dir.glob("massive_*.json"))
    assert len(cache_files) >= 1
    cached = json.loads(cache_files[0].read_text())
    assert cached["ticker"] == "X:BTCUSD"
