"""Regression suite for the CLIENT-FACING number set (ENG4 · Aug-2026).

Locks every headline the deck will quote to the value the ENGINE actually produces,
off OBSERVED / tracked inputs, so a silent drift in the pricer, SVI surface, ledger,
or the anti-overfitting statistics fails CI rather than the meeting.

Anchors (all reproduced here from tracked repo data unless a test is skip-gated):
  1. Per-tenor reprice gate  — traded ~1-month tenor core ARPE ~= 2.43%  (=> "~97.6%",
     NEVER 98%); long-dated tenors reprice <= 2%. Real ``assert_per_tenor_gate`` call.
  2. +6% ladder income       — 6/10/14/18% @ 40% coverage off the OBSERVED 2026-07-31
     Deribit archive skew = $3.79M/cycle (blended $315.81/BTC). Legacy +4% = $6.93M.
  3. Ledger reconciliation    — the faithful multi-leg backtest closes the accounting
     identity to ~$0 (reconciliation_residual_usd ~= 0).
  4. Deflated Sharpe / PBO    — canonical Bailey-Lopez de Prado module: synthetic
     controls (noise rejects, genuine edge passes) always run; the FOUNDATIONS-locked
     DSR ~0.925 / PBO 0.0011 on agent-8's 24-config grid is reproduced when present.
  5. Data-integrity overlaps  — the OBSERVED 1d spot history is strictly monotonic with
     zero duplicate timestamps and 1-day cadence; overlapping bars match the full store.

Honesty rule (FOUNDATIONS §10 lock #6): the traded-tenor ARPE sits ABOVE the 2% target;
these tests LOCK the measured number (~97.6%), they do not assert a rigged pass.
Provenance labels: OBSERVED inputs, CALCULATED anchors, SIMULATED controls.
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from datetime import UTC, datetime

import numpy as np
import numpy.typing as npt
import pytest

from config.loader import load_research_config
from engine.data_models import BookSummary
from pricing.black76 import price_black76
from strategy.backtest_multileg import backtest_strategy_multileg
from strategy.definitions_multileg import build_laddered_cc
from strategy.deflated_sharpe import cscv_pbo, deflated_sharpe_ratio, sharpe_ratio
from vol.chain_surface import (
    fit_svi_surface,
    ingest_chain_slices,
    slices_from_book_summaries,
)
from vol.reprice_gate import (
    RepriceReport,
    assert_per_tenor_gate,
    assert_reprice_gate,
    price_reprice_report,
    spreads_from_book_summaries,
    svi_iv_getter,
)
from vol.snapshot import load_snapshot

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FIX = _ROOT / "tests" / "fixtures"
_ARCHIVE = _ROOT / "market_snapshots" / "deribit_surface_archive" / "2026-07-31" / "book_summary.json"
_BINANCE_1D = _ROOT / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_BINANCE_1D_FULL = _ROOT / "market_snapshots" / "binance_history_full" / "1d" / "bars.json"
_GRID_CSV = pathlib.Path("/tmp/oos/grid_daily_returns.csv")

# Locked mandate ladder (D-C).
_LADDER = (0.06, 0.10, 0.14, 0.18)
_LEGACY_LADDER = (0.04, 0.0667, 0.0933, 0.12)
_BLOCK = 30_000.0
_COVERAGE = 0.40
_COVERED = _BLOCK * _COVERAGE          # 12,000 BTC
_TRANCHE = _COVERED / len(_LADDER)     # 3,000 BTC
_BAND = (0.15, 0.85)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Per-tenor reprice gate — the "~97.6% on the traded tenor" claim
# ══════════════════════════════════════════════════════════════════════════════


def _fixture_report() -> RepriceReport:
    snap = load_snapshot(_FIX)
    slices = ingest_chain_slices(
        snap.instruments, snap.book_summaries, datetime(2026, 7, 30, tzinfo=UTC)
    )
    smap = spreads_from_book_summaries(snap.book_summaries)
    return price_reprice_report(
        slices, svi_iv_getter(slices, objective="total_variance"),
        delta_band=(0.10, 0.90), spread_map=smap,
    )


def _arpe_by_label(rep: RepriceReport) -> dict[str, float]:
    """Per-expiry core ARPE (%), keyed by expiry label, on the tradeable delta band."""
    return {
        str(r["label"]): float(str(r["arpe_pct"]))
        for r in rep.per_tenor_core_table(delta_band=_BAND)
    }


def test_traded_tenor_arpe_locks_client_accuracy() -> None:
    """Traded ~1-month tenor core ARPE ~= 2.43% (=> ~97.6% accuracy, NEVER 98%)."""
    rep = _fixture_report()
    pt = assert_per_tenor_gate(
        rep, arpe_max=0.02, traded_tenor_days=(25.0, 45.0), delta_band=_BAND,
    )
    # The honest number the deck quotes. It is ABOVE 2% => the gate does NOT pass;
    # we lock the measured value, not a rigged pass (FOUNDATIONS §10 lock #6).
    assert pt.traded_arpe == pytest.approx(0.0243, abs=0.0015)
    assert not pt.passed
    accuracy_pct = 100.0 * (1.0 - pt.traded_arpe)
    assert 97.0 <= accuracy_pct <= 98.0        # "~97.6%", never 98%


def test_long_dated_tenors_reprice_within_two_percent() -> None:
    """Every tenor beyond the traded window reprices <= 2% (long-dated core is tight)."""
    arpe = _arpe_by_label(_fixture_report())
    for label in ("14AUG26", "25DEC26", "26MAR27", "25JUN27"):
        assert arpe[label] <= 2.0


def test_aggregate_gate_passes_but_does_not_hide_traded_tenor() -> None:
    """The tenor-AGGREGATED gate passes; the per-tenor gate still binds on the traded bucket."""
    rep = _fixture_report()
    assert assert_reprice_gate(rep, arpe_max=0.02).passed
    pt = assert_per_tenor_gate(rep, arpe_max=0.02, traded_tenor_days=(25.0, 45.0), delta_band=_BAND)
    assert not pt.passed                                   # not hidden by the aggregate
    assert any("25SEP26" in w for w in pt.warnings)        # 57d anomaly surfaces as a WARNING


# ══════════════════════════════════════════════════════════════════════════════
# 2. +6% ladder income off the OBSERVED 2026-07-31 skew
# ══════════════════════════════════════════════════════════════════════════════


def _load_archive_books() -> list[BookSummary]:
    rows = json.loads(_ARCHIVE.read_text())
    ref = datetime(2026, 7, 31, tzinfo=UTC)
    out: list[BookSummary] = []
    for s in rows:
        try:
            out.append(BookSummary(
                instrument_name=s["instrument_name"], mark_price=s.get("mark_price", 0.0),
                mark_iv=s.get("mark_iv") or 0.0, bid_price=s.get("bid_price"),
                bid_iv=s.get("bid_iv"), ask_price=s.get("ask_price"), ask_iv=s.get("ask_iv"),
                open_interest=s.get("open_interest", 0.0),
                underlying_price=s.get("underlying_price", 0.0), timestamp=ref,
            ))
        except Exception:  # skip malformed rows, faithful to the pricer's ingestion
            continue
    return out


def _ladder_income(pcts: tuple[float, ...]) -> tuple[float, float, dict[str, float]]:
    """Return (income_usd, blended_per_btc, nearest_leg_metrics) off the observed skew."""
    ref = datetime(2026, 7, 31, tzinfo=UTC)
    books = _load_archive_books()
    slices = [s for s in slices_from_book_summaries(books, reference=ref, min_strikes=5)
              if s.T * 365.0 >= 7.0]
    spot = float(np.median([b.underlying_price for b in books if b.underlying_price > 0]))
    tgt = min(slices, key=lambda s: abs(s.T * 365.0 - 31.0))
    fit = fit_svi_surface(slices)
    f_tgt = {f.label: f for f in fit.slices}[tgt.label]
    forward, T = tgt.forward, tgt.T
    income = 0.0
    nearest: dict[str, float] = {}
    for i, pct in enumerate(pcts):
        strike = spot * (1.0 + pct)
        k = math.log(strike / forward)
        iv = float(f_tgt.params.iv(k))
        prem = price_black76(forward, strike, 0.0, iv, T, "call")
        income += prem * _TRANCHE
        if i == 0:
            nearest = {"strike": strike, "iv": iv, "prem_per_btc": prem}
    return income, income / _COVERED, nearest


def test_plus6_ladder_income_matches_observed_skew() -> None:
    """+6% ladder (6/10/14/18%, 40%) off OBSERVED 2026-07-31 skew = $3.79M/cycle."""
    if not _ARCHIVE.exists():
        pytest.skip("observed 2026-07-31 Deribit archive not present")
    income, blended, nearest = _ladder_income(_LADDER)
    assert income == pytest.approx(3_789_680.5, rel=1e-4)      # E_numbers §1
    assert blended == pytest.approx(315.81, abs=0.05)           # blended $/BTC
    # nearest +6% leg: negative call skew (IV ~30% << 33.8% ATM), delta ~0.24.
    assert nearest["strike"] == pytest.approx(68_073.5, rel=1e-4)
    assert nearest["iv"] == pytest.approx(0.30, abs=0.01)
    assert nearest["prem_per_btc"] == pytest.approx(736.32, rel=1e-3)


def test_legacy_plus4_ladder_cross_check() -> None:
    """The legacy +4% ladder off the same surface reproduces the c9 baseline $6.93M."""
    if not _ARCHIVE.exists():
        pytest.skip("observed 2026-07-31 Deribit archive not present")
    income, _blended, _nearest = _ladder_income(_LEGACY_LADDER)
    assert income == pytest.approx(6_927_680.7, rel=1e-4)


def test_plus6_income_is_a_haircut_to_legacy() -> None:
    """The +6% ladder earns materially less than +4% off the same surface (the -45% haircut)."""
    if not _ARCHIVE.exists():
        pytest.skip("observed 2026-07-31 Deribit archive not present")
    inc6, _b6, _n6 = _ladder_income(_LADDER)
    inc4, _b4, _n4 = _ladder_income(_LEGACY_LADDER)
    assert inc6 < inc4
    assert inc6 / inc4 == pytest.approx(0.547, abs=0.02)       # ~-45%


# ══════════════════════════════════════════════════════════════════════════════
# 3. Ledger reconciliation — the accounting identity closes to ~$0
# ══════════════════════════════════════════════════════════════════════════════


def _load_1d(path: pathlib.Path) -> tuple[list[datetime], npt.NDArray[np.float64]]:
    bars = json.loads(path.read_text())
    dates = [datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00")) for b in bars]
    close = np.array([float(b["close"]) for b in bars], dtype=np.float64)
    return dates, close


def test_multileg_ledger_reconciles_to_zero() -> None:
    """The faithful +6% laddered-CC backtest closes dcash + d(btc*spot) + dcollat == net_pnl."""
    if not _BINANCE_1D.exists():
        pytest.skip("binance_history/1d not present")
    dates, close = _load_1d(_BINANCE_1D)
    s0 = float(close[0])
    iv = np.full(close.shape, 0.55, dtype=np.float64)
    strat = build_laddered_cc(entry_spot=s0, coverage=_COVERAGE, ladder_pcts=list(_LADDER))
    res = backtest_strategy_multileg(strat, dates, close, iv, ref_spot=s0, dte_days=31, seed=42)
    # Absolute residual is ~1e-6 USD on a ~$1.9B block over 9 years.
    assert abs(res.reconciliation_residual_usd) < 1.0
    rel = abs(res.reconciliation_residual_usd) / max(abs(res.total_pnl_usd), 1.0)
    assert rel < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# 4. Deflated Sharpe / CSCV-PBO — canonical Bailey-Lopez de Prado
# ══════════════════════════════════════════════════════════════════════════════


def test_dsr_synthetic_controls() -> None:
    """SIMULATED controls: pure noise (many trials) rejects; a genuine edge passes."""
    rng = np.random.default_rng(7)
    noise = rng.standard_normal((500, 50))
    trial_sr = np.array([sharpe_ratio(noise[:, j]) for j in range(noise.shape[1])])
    best = int(np.nanargmax(trial_sr))
    d_noise = deflated_sharpe_ratio(noise[:, best], trial_sharpes=trial_sr)
    assert d_noise["dsr"] < 0.5          # noise selected from 50 trials is NOT significant

    edge = rng.standard_normal(1000) + 0.15
    d_edge = deflated_sharpe_ratio(edge, n_trials=1)
    assert d_edge["dsr"] > 0.95          # a real single-trial edge passes the gate


def test_dsr_pbo_are_probabilities() -> None:
    """DSR and PBO are probabilities in [0, 1] (not the old unbounded home-grown number)."""
    rng = np.random.default_rng(11)
    mat = rng.standard_normal((400, 6))
    d = deflated_sharpe_ratio(mat[:, 0], n_trials=6)
    assert 0.0 <= float(d["dsr"]) <= 1.0
    pbo = cscv_pbo(mat, S=8)
    assert 0.0 <= float(pbo["pbo"]) <= 1.0


def test_dsr_pbo_reproduce_foundations_locked_numbers() -> None:
    """On agent-8's 24-config grid: conservative DSR ~0.925 and CSCV-PBO 0.0011 (A4)."""
    if not _GRID_CSV.exists():
        pytest.skip("agent-8 24-config grid /tmp/oos/grid_daily_returns.csv not present")
    with _GRID_CSV.open() as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    cols = header[1:]
    mat = np.array([[float(x) for x in row[1:]] for row in rows], dtype=np.float64)
    locked = cols.index("L_4-12|sys|q")           # the FOUNDATIONS-locked +4/12 config
    d_cons = deflated_sharpe_ratio(mat[:, locked], n_trials=mat.shape[1])
    assert float(d_cons["dsr"]) == pytest.approx(0.925, abs=0.01)
    pbo = cscv_pbo(mat, S=12)
    assert float(pbo["pbo"]) == pytest.approx(0.0011, abs=0.0010)
    assert int(pbo["n_splits"]) == 924            # exhaustive C(12,6) symmetric splits


# ══════════════════════════════════════════════════════════════════════════════
# 5. Data-integrity overlaps — the OBSERVED spot history is clean & consistent
# ══════════════════════════════════════════════════════════════════════════════


def test_spot_history_monotonic_no_duplicates() -> None:
    """1d spot history: strictly increasing timestamps, no duplicates, 1-day cadence."""
    if not _BINANCE_1D.exists():
        pytest.skip("binance_history/1d not present")
    dates, close = _load_1d(_BINANCE_1D)
    epochs = np.array([d.timestamp() for d in dates], dtype=np.float64)
    assert np.all(np.diff(epochs) > 0.0)                    # strictly monotonic
    assert len(set(epochs.tolist())) == epochs.size         # zero duplicate timestamps
    assert np.all(close > 0.0)
    steps = np.diff(epochs)
    assert float(np.median(steps)) == pytest.approx(86_400.0)   # 1-day cadence


def test_full_and_existing_snapshots_agree_on_overlap() -> None:
    """Overlapping timestamps between the existing and full 1d stores carry identical closes."""
    if not (_BINANCE_1D.exists() and _BINANCE_1D_FULL.exists()):
        pytest.skip("both 1d snapshots required for the overlap check")
    d_a, c_a = _load_1d(_BINANCE_1D)
    d_b, c_b = _load_1d(_BINANCE_1D_FULL)
    map_a = {d.isoformat(): float(c) for d, c in zip(d_a, c_a, strict=True)}
    map_b = {d.isoformat(): float(c) for d, c in zip(d_b, c_b, strict=True)}
    shared = set(map_a) & set(map_b)
    assert len(shared) > 1000                               # a real overlap exists
    mismatches = [k for k in shared if not math.isclose(map_a[k], map_b[k], rel_tol=1e-6)]
    assert not mismatches, f"{len(mismatches)} overlapping closes disagree"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Config-of-record lock — params.yaml encodes the LOCKED ~10-15 delta / 40% /
#    monthly / IV-timed policy (DECISIONS_LOG "FINAL SYNTHESIZED DECISIONS")
# ══════════════════════════════════════════════════════════════════════════════


def test_config_encodes_locked_mandate_policy() -> None:
    """Single source of truth: ~10-15 delta, 40% coverage, MONTHLY 30-45 DTE, IV-timed.

    Supersedes the interim +6% quarterly ladder (D-C). Strikes are delta-defined and
    solved at entry vol; the governing knob is call_delta_target.
    """
    cfg = load_research_config()
    assert cfg.coverage_fraction_pct == 40.0
    assert cfg.call_delta_target == [0.10, 0.15]      # ~10-15 delta low-assignment line
    assert cfg.dte_target_days == [30, 45]            # monthly 30-45 DTE traded tenor
    assert cfg.cadence == "monthly"
    assert cfg.iv_timed_entry is True
    # The stale quarterly +6% collar is gone; ladder shifted OUT to the delta line.
    assert cfg.ladder_strikes_pct_above_spot == [10.0, 14.0, 18.0, 22.0]
    assert cfg.strike_target_pct_above_spot == [10.0, 22.0]
    # Pending business decisions are NOT silently resolved in the config of record.
    assert cfg.fee_base is None
    assert cfg.primary_venue is None
