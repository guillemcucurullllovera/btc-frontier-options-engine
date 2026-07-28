"""Vol-layer tests for A2: parsing, retries, timeouts, offline replay,
caching, stale data, provenance, surface interpolation, sparse surfaces,
GARCH diagnostics.

All tests derive from fixtures: no live network.
"""

from __future__ import annotations

import math
import pathlib

# We use sys.path.insert as done by all other test files
import sys
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

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
    MassiveSpotProvider,
    SpotCache,
)
from vol.surface import (
    VolPoint,
    VolSurface,
    fit_surface,
    iv_at,
)

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
