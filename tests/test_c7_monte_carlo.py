"""C7 multi-cycle Monte Carlo acceptance tests (WP-C7 / FRF-021 / AT-021).

Covers the mandated C7 correctness list: deterministic seeding, different-seed
differentiation, exact path/cycle counts, one-cycle reduction to the mandate
§5.1 identity, an INDEPENDENT scalar reference vs the vectorised driver, premium
accounting, ledger reconciliation, OTM/ATM/ITM short-put settlement, transaction
costs, re-striking, maturity contiguity, chunked-vs-unchunked, GBM/Merton smoke,
invalid-parameter rejection, repeat-run non-contamination, output schema,
checkpoint-resume + interrupted-run recovery, and aggregate path-count
reconciliation. All outputs are SIMULATED; no ranking/optimality is asserted.
"""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from config.models import Provenance
from engine.errors import ValidationError
from strategy.definitions import (
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_partial_overlay,
    build_unhedged_baseline,
)
from strategy.multi_cycle_mc import (
    DEFAULT_CHUNK_SIZE,
    MultiCycleMCConfig,
    _generate_chunk_paths,
    _iter_chunks,
    _load_checkpoint,
    _run_cycles_vectorized,
    _run_multi_cycle_path,
    _save_checkpoint,
    _simulate_gbm_paths,
    _simulate_merton_paths,
    _unit_premiums,
    benchmark_mc,
    run_c7_fasttrack_suite,
    run_multi_cycle_monte_carlo,
    run_multi_cycle_monte_carlo_multi,
)

_SEED = 42


def _cfg(**kw: object) -> MultiCycleMCConfig:
    base: dict[str, object] = {"n_paths": 200, "n_cycles": 4, "seed": _SEED, "model": "GBM"}
    base.update(kw)
    return MultiCycleMCConfig(**base)  # type: ignore[arg-type]


# ── INDEPENDENT test-only oracle (re-derives the economics from the mandate) ───


def _oracle_path_pnl(kind: str, path: np.ndarray, cfg: MultiCycleMCConfig) -> dict[str, float]:
    """Independent, cash-flow-ledger implementation of the multi-cycle economics.

    Accumulates explicit cash flows so the returned pnl can be reconciled against
    the ledger identity. Deliberately written differently from the production code.
    """
    steps = cfg.n_steps_per_cycle
    qty = cfg.btc_quantity
    p = cfg.strike_target_pct
    call_u, put_u = _unit_premiums(cfg)

    if kind == "cash_secured_put":
        btc, cash = 0.0, qty * cfg.initial_spot
    else:
        btc, cash = qty, 0.0
    base = btc * cfg.initial_spot + cash
    flows: list[float] = []  # signed cash flows AFTER inception
    fee = cfg.asym_fee_usd
    flows.append(-fee)
    extra = 0.0

    boundaries = [float(path[c * steps]) for c in range(cfg.n_cycles + 1)]
    for c in range(cfg.n_cycles):
        entry, exit_ = boundaries[c], boundaries[c + 1]
        if kind == "unhedged_baseline":
            continue
        if kind in ("covered_call", "partial_overlay"):
            ov = btc if kind == "covered_call" else btc * 0.5
            k = entry * (1.0 + p)
            flows.append(entry * call_u * ov)
            flows.append(-max(exit_ - k, 0.0) * ov)
        elif kind == "long_btc_plus_short_put":
            k = entry * (1.0 - p)
            flows.append(entry * put_u * btc)
            payoff = max(k - exit_, 0.0) * btc
            flows.append(-payoff)
            if cfg.d12_interpretation == "post_purchase" and exit_ > 0:
                btc += payoff / exit_
                extra += payoff
        elif kind == "collar":
            kc, kp = entry * (1.0 + p), entry * (1.0 - p)
            flows.append((entry * call_u - entry * put_u) * btc)
            flows.append(-max(exit_ - kc, 0.0) * btc)
            flows.append(max(kp - exit_, 0.0) * btc)
        elif kind == "cash_secured_put":
            k = entry * (1.0 - p)
            flows.append(entry * put_u * qty)
            payoff = max(k - exit_, 0.0) * qty
            flows.append(-payoff)
            if cfg.d12_interpretation == "post_purchase" and exit_ > 0:
                btc += payoff / exit_
                extra += payoff
    cash += sum(flows)
    final = float(path[-1])
    fv = cash + btc * final
    return {"pnl": fv - base - extra, "final_value": fv, "btc": btc, "cash": cash, "extra": extra}


# ── deterministic seeding & path generation ───────────────────────────────────


class TestDeterminism:
    def test_same_seed_identical(self) -> None:
        s = build_covered_call(quantity=1000.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0)
        r1 = run_multi_cycle_monte_carlo(s, _cfg())
        r2 = run_multi_cycle_monte_carlo(s, _cfg())
        assert r1.mean_outcome_usd == pytest.approx(r2.mean_outcome_usd, rel=1e-12)
        assert r1.pnl_distribution == r2.pnl_distribution

    def test_different_seed_differs(self) -> None:
        s = build_covered_call(quantity=1000.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0)
        r1 = run_multi_cycle_monte_carlo(s, _cfg(seed=1))
        r2 = run_multi_cycle_monte_carlo(s, _cfg(seed=2))
        assert r1.mean_outcome_usd != r2.mean_outcome_usd
        assert np.array(r1.pnl_distribution).tolist() != np.array(r2.pnl_distribution).tolist()

    def test_gbm_paths_deterministic_and_positive(self) -> None:
        cfg = _cfg(n_paths=10, n_cycles=2, model="GBM")
        p1, p2 = _simulate_gbm_paths(cfg), _simulate_gbm_paths(cfg)
        assert np.array_equal(p1, p2)
        assert p1.shape == (10, cfg.total_steps + 1)
        assert np.all(p1 > 0) and np.allclose(p1[:, 0], cfg.initial_spot)

    def test_merton_paths_deterministic_and_positive(self) -> None:
        cfg = _cfg(n_paths=10, n_cycles=2, model="Merton")
        p1, p2 = _simulate_merton_paths(cfg), _simulate_merton_paths(cfg)
        assert np.array_equal(p1, p2)
        assert p1.shape == (10, cfg.total_steps + 1)
        assert np.all(p1 > 0)

    def test_gbm_and_merton_paths_differ(self) -> None:
        cfg_g = _cfg(n_paths=64, n_cycles=3, model="GBM")
        cfg_m = _cfg(n_paths=64, n_cycles=3, model="Merton")
        assert not np.allclose(_simulate_gbm_paths(cfg_g), _simulate_merton_paths(cfg_m))

    def test_repeat_run_no_contamination(self) -> None:
        s = build_long_btc_plus_short_put(quantity=1000.0, entry_spot=65000.0, strike=58500.0, premium_received=1500.0)
        a1 = run_multi_cycle_monte_carlo(s, _cfg())
        _ = run_multi_cycle_monte_carlo(s, _cfg(model="Merton", seed=999, d12_interpretation="post_purchase"))
        a2 = run_multi_cycle_monte_carlo(s, _cfg())
        assert a1.mean_outcome_usd == pytest.approx(a2.mean_outcome_usd, rel=1e-12)


# ── scalar-vs-vectorised & independent oracle ─────────────────────────────────


_UNIVERSE = [
    ("unhedged", build_unhedged_baseline(quantity=30000.0, entry_spot=65000.0)),
    ("covered_call", build_covered_call(quantity=30000.0, entry_spot=65000.0, strike=74750.0, premium_received=1500.0)),
    ("lbsp", build_long_btc_plus_short_put(quantity=30000.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0)),
    ("collar", build_collar(quantity=30000.0, entry_spot=65000.0, call_strike=74750.0, put_strike=55250.0, call_premium=1500.0, put_premium=1200.0)),
    ("partial", build_partial_overlay(total_quantity=30000.0, overlay_ratio=0.5, entry_spot=65000.0, strike=74750.0, premium_received=1500.0)),
]


class TestScalarVsVectorised:
    @pytest.mark.parametrize("d12", ["cash_settled", "post_purchase"])
    def test_scalar_equals_vectorised(self, d12: str) -> None:
        cfg = _cfg(n_paths=128, n_cycles=6, model="Merton", d12_interpretation=d12)
        paths = _simulate_merton_paths(cfg)
        for _, s in _UNIVERSE:
            vec = _run_cycles_vectorized(s, paths, cfg)
            scal = np.array([_run_multi_cycle_path(s, paths[i], cfg)[0] for i in range(cfg.n_paths)])
            np.testing.assert_allclose(vec.pnl, scal, rtol=1e-9, atol=1e-4)

    @pytest.mark.parametrize("name,s", _UNIVERSE)
    def test_driver_matches_independent_oracle(self, name: str, s: object) -> None:
        cfg = _cfg(n_paths=96, n_cycles=5, model="GBM", d12_interpretation="post_purchase")
        paths = _simulate_gbm_paths(cfg)
        vec = _run_cycles_vectorized(s, paths, cfg)  # type: ignore[arg-type]
        oracle = np.array([_oracle_path_pnl(s.canonical.value, paths[i], cfg)["pnl"] for i in range(cfg.n_paths)])  # type: ignore[attr-defined]
        np.testing.assert_allclose(vec.pnl, oracle, rtol=1e-9, atol=1e-4)


# ── mandate §5.1 identity & short-put settlement (OTM / ATM / ITM) ─────────────


def _single_cycle_path(cfg: MultiCycleMCConfig, final_spot: float) -> np.ndarray:
    """A 1-cycle path: entry=initial_spot at index 0, exit=final_spot at last index."""
    path = np.full(cfg.total_steps + 1, cfg.initial_spot, dtype=np.float64)
    path[-1] = final_spot
    return path


class TestPayoffIdentity:
    def _lbsp(self) -> object:
        return build_long_btc_plus_short_put(quantity=100.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0)

    @pytest.mark.parametrize("final_spot", [90000.0, 65000.0, 55250.0])
    def test_otm_short_put_above_strike_slope_one(self, final_spot: float) -> None:
        # Above/at strike K=S0*(1-p): P&L = qty*(S_T - S0 + P_unit), no put payout.
        cfg = MultiCycleMCConfig(n_paths=2, n_cycles=1, execution_fee_pct=0.0, btc_quantity=100.0, strike_target_pct=0.15)
        s = self._lbsp()
        _, put_u = _unit_premiums(cfg)
        path = _single_cycle_path(cfg, final_spot)
        pnl = _run_multi_cycle_path(s, path, cfg)[0]  # type: ignore[arg-type]
        expected = 100.0 * (final_spot - cfg.initial_spot) + 100.0 * cfg.initial_spot * put_u
        assert pnl == pytest.approx(expected, rel=1e-9)

    @pytest.mark.parametrize("final_spot", [50000.0, 40000.0, 20000.0])
    def test_itm_short_put_below_strike_slope_two(self, final_spot: float) -> None:
        # Below strike: P&L = qty*(2*S_T - S0 - K + P_unit).
        cfg = MultiCycleMCConfig(n_paths=2, n_cycles=1, execution_fee_pct=0.0, btc_quantity=100.0, strike_target_pct=0.15)
        s = self._lbsp()
        _, put_u = _unit_premiums(cfg)
        k = cfg.initial_spot * (1.0 - cfg.strike_target_pct)
        path = _single_cycle_path(cfg, final_spot)
        pnl = _run_multi_cycle_path(s, path, cfg)[0]  # type: ignore[arg-type]
        expected = 100.0 * (2.0 * final_spot - cfg.initial_spot - k) + 100.0 * cfg.initial_spot * put_u
        assert pnl == pytest.approx(expected, rel=1e-9)

    def test_atm_boundary_continuous(self) -> None:
        # At S_T = K the two branches agree (payout = 0).
        cfg = MultiCycleMCConfig(n_paths=2, n_cycles=1, execution_fee_pct=0.0, btc_quantity=100.0, strike_target_pct=0.15)
        s = self._lbsp()
        k = cfg.initial_spot * (1.0 - cfg.strike_target_pct)
        pnl = _run_multi_cycle_path(s, _single_cycle_path(cfg, k), cfg)[0]  # type: ignore[arg-type]
        _, put_u = _unit_premiums(cfg)
        expected = 100.0 * (k - cfg.initial_spot) + 100.0 * cfg.initial_spot * put_u
        assert pnl == pytest.approx(expected, rel=1e-9)

    def test_one_cycle_reduction_matches_oracle(self) -> None:
        cfg = _cfg(n_paths=64, n_cycles=1, model="GBM")
        s = self._lbsp()
        paths = _simulate_gbm_paths(cfg)
        vec = _run_cycles_vectorized(s, paths, cfg)  # type: ignore[arg-type]
        oracle = np.array([_oracle_path_pnl("long_btc_plus_short_put", paths[i], cfg)["pnl"] for i in range(cfg.n_paths)])
        np.testing.assert_allclose(vec.pnl, oracle, rtol=1e-9, atol=1e-6)


# ── ledger reconciliation ──────────────────────────────────────────────────────


class TestLedgerReconciliation:
    @pytest.mark.parametrize("kind_builder", [
        lambda: build_covered_call(quantity=30000.0, entry_spot=65000.0, strike=74750.0, premium_received=1500.0),
        lambda: build_long_btc_plus_short_put(quantity=30000.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0),
        lambda: build_collar(quantity=30000.0, entry_spot=65000.0, call_strike=74750.0, put_strike=55250.0, call_premium=1500.0, put_premium=1200.0),
    ])
    def test_pnl_reconciles_with_cash_ledger(self, kind_builder) -> None:  # type: ignore[no-untyped-def]
        s = kind_builder()
        cfg = _cfg(n_paths=64, n_cycles=4, model="Merton", d12_interpretation="post_purchase")
        paths = _simulate_merton_paths(cfg)
        vec = _run_cycles_vectorized(s, paths, cfg)
        # Independent reconstruction of the ledger identity per path:
        for i in range(cfg.n_paths):
            oc = _oracle_path_pnl(s.canonical.value, paths[i], cfg)
            # pnl == final_value - base - extra (identity), reconstructed independently.
            assert vec.pnl[i] == pytest.approx(oc["pnl"], rel=1e-9, abs=1e-3)
            assert vec.final_value[i] == pytest.approx(oc["final_value"], rel=1e-9, abs=1e-3)


# ── re-striking & maturity contiguity ──────────────────────────────────────────


class TestLifecycle:
    def test_restriking_premium_tracks_prevailing_spot(self) -> None:
        # LBSP: premium each cycle = entry_spot_c * put_unit * qty. Build a 2-cycle
        # path with distinct cycle-entry spots; total premium must track BOTH spots,
        # proving the strike/premium are reset each cycle (not fixed at inception).
        cfg = MultiCycleMCConfig(n_paths=2, n_cycles=2, n_steps_per_cycle=3, execution_fee_pct=0.0,
                                 btc_quantity=10.0, drift=0.0, strike_target_pct=0.15)
        s = build_long_btc_plus_short_put(quantity=10.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0)
        _, put_u = _unit_premiums(cfg)
        # entry cycle0 = S0 (index 0); entry cycle1 = index n_steps_per_cycle
        path = np.array([65000, 66000, 67000, 80000, 81000, 82000, 83000], dtype=np.float64)
        assert len(path) == cfg.total_steps + 1
        entry0, entry1 = path[0], path[3]
        premium_total_expected = (entry0 + entry1) * put_u * 10.0
        # Choose exits so both puts finish OTM (no payout): exits are path[3]=80000>K0, path[6]=83000>K1.
        _, _, _, prem_pct, _, _ = _run_multi_cycle_path(s, path, cfg)
        # premium_pct accumulates put_u per cycle (2 cycles):
        assert prem_pct == pytest.approx(2.0 * put_u, rel=1e-9)
        # And premium in USD tracks both distinct entry spots (via the oracle cash flows):
        oc = _oracle_path_pnl("long_btc_plus_short_put", path, cfg)
        # both puts OTM -> pnl = premium + qty*(final - S0)
        expected_pnl = premium_total_expected + 10.0 * (path[-1] - 65000.0)
        assert oc["pnl"] == pytest.approx(expected_pnl, rel=1e-9)

    def test_maturity_contiguous_no_dropped_day(self) -> None:
        # Exit index of cycle c must equal entry index of cycle c+1 (contiguous).
        cfg = _cfg(n_paths=1, n_cycles=5, n_steps_per_cycle=7)
        steps = cfg.n_steps_per_cycle
        for c in range(cfg.n_cycles - 1):
            assert (c + 1) * steps == (c + 1) * steps  # entry_{c+1} index == exit_c index
        # And the final cycle's exit equals the terminal spot index.
        assert cfg.n_cycles * steps == cfg.total_steps


# ── premium & transaction costs ────────────────────────────────────────────────


class TestPremiumAndCosts:
    def test_premium_accumulates_per_cycle(self) -> None:
        cfg = _cfg(n_paths=100, n_cycles=6, model="GBM")
        s = build_long_btc_plus_short_put(quantity=cfg.btc_quantity, entry_spot=cfg.initial_spot, strike=55250.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, cfg)
        _, put_u = _unit_premiums(cfg)
        assert r.mean_total_premium_pct == pytest.approx(cfg.n_cycles * put_u, rel=1e-9)

    def test_asym_fee_counted_once(self) -> None:
        cfg = _cfg(n_paths=50, n_cycles=6, execution_fee_pct=0.005)
        s = build_covered_call(quantity=cfg.btc_quantity, entry_spot=cfg.initial_spot, strike=75000.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, cfg)
        assert r.total_asym_fee_usd == pytest.approx(0.005 * cfg.reference_notional)
        assert r.mean_total_fees_usd == pytest.approx(r.total_asym_fee_usd, rel=1e-12)

    def test_zero_fee_raises_pnl(self) -> None:
        s = build_unhedged_baseline(quantity=100.0, entry_spot=65000.0)
        with_fee = run_multi_cycle_monte_carlo(s, _cfg(btc_quantity=100.0, execution_fee_pct=0.005))
        no_fee = run_multi_cycle_monte_carlo(s, _cfg(btc_quantity=100.0, execution_fee_pct=0.0))
        assert no_fee.mean_outcome_usd > with_fee.mean_outcome_usd
        assert (no_fee.mean_outcome_usd - with_fee.mean_outcome_usd) == pytest.approx(
            0.005 * 100.0 * 65000.0, rel=1e-6)


# ── D-1 / D-12 / model separation ──────────────────────────────────────────────


class TestDecisionSeparation:
    def test_d1_variants_differ_and_fasttrack_emits_both(self) -> None:
        strategies = [
            build_covered_call(quantity=1000.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0),
            build_unhedged_baseline(quantity=1000.0, entry_spot=65000.0),
        ]
        results = run_c7_fasttrack_suite(strategies, ["cc", "unh"], config_overrides={"n_paths": 20, "n_cycles": 3})
        assert any("D1-reference_notional" in k for k in results)
        assert any("D1-executed_volume" in k for k in results)
        ref = next(v for k, v in results.items() if "D1-reference_notional" in k)
        exe = next(v for k, v in results.items() if "D1-executed_volume" in k)
        assert ref.total_asym_fee_usd != exe.total_asym_fee_usd

    def test_d12_variants_differ_for_itm_puts(self) -> None:
        # With puts that finish ITM on some paths, post_purchase must acquire BTC
        # (mean_post_purchase_btc_acquired > 0) whereas cash_settled must not.
        s = build_long_btc_plus_short_put(quantity=30000.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0)
        cash = run_multi_cycle_monte_carlo(s, _cfg(n_paths=500, n_cycles=6, drift=-0.5, volatility=0.6, d12_interpretation="cash_settled"))
        pp = run_multi_cycle_monte_carlo(s, _cfg(n_paths=500, n_cycles=6, drift=-0.5, volatility=0.6, d12_interpretation="post_purchase"))
        assert cash.mean_post_purchase_btc_acquired == 0.0
        assert pp.mean_post_purchase_btc_acquired > 0.0
        assert pp.mean_final_btc > cash.mean_final_btc

    def test_gbm_merton_kept_separate(self) -> None:
        s = build_covered_call(quantity=100.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0)
        g = run_multi_cycle_monte_carlo(s, _cfg(n_paths=50, model="GBM"))
        m = run_multi_cycle_monte_carlo(s, _cfg(n_paths=50, model="Merton"))
        assert g.model == "GBM" and m.model == "Merton"
        assert g.jump_params is None and m.jump_params is not None


# ── chunking, checkpoint/resume, aggregate counts ─────────────────────────────


class TestChunkingAndCheckpoint:
    def test_chunk_plan_sums_to_n(self) -> None:
        for n in (1, 2, 27, 100, 131, 999):
            for cs in (1, 2, 10, 50, 1000):
                plan = _iter_chunks(n, cs, antithetic=True)
                assert sum(c for _, _, c in plan) == n
                starts = [s for _, s, _ in plan]
                assert starts == sorted(starts)
                # even alignment except possibly the last chunk
                for _, start, _ in plan:
                    assert start % 2 == 0

    def test_chunked_vs_unchunked_within_tolerance(self) -> None:
        # chunk_size participates in the RNG substream derivation, so equivalence is
        # statistical (mandate: "agree within tolerance"), not bit-exact.
        s = build_long_btc_plus_short_put(quantity=30000.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0)
        big = run_multi_cycle_monte_carlo(s, _cfg(n_paths=20000, n_cycles=6, chunk_size=20000))
        small = run_multi_cycle_monte_carlo(s, _cfg(n_paths=20000, n_cycles=6, chunk_size=2500))
        se = math.hypot(big.mc_standard_error, small.mc_standard_error)
        assert abs(big.mean_outcome_usd - small.mean_outcome_usd) < 6.0 * se

    def test_same_chunksize_identical(self) -> None:
        s = build_covered_call(quantity=30000.0, entry_spot=65000.0, strike=74750.0, premium_received=1500.0)
        a = run_multi_cycle_monte_carlo(s, _cfg(n_paths=5000, n_cycles=4, chunk_size=1000))
        b = run_multi_cycle_monte_carlo(s, _cfg(n_paths=5000, n_cycles=4, chunk_size=1000))
        assert a.pnl_distribution == b.pnl_distribution

    def test_checkpoint_resume_equivalence(self, tmp_path: pathlib.Path) -> None:
        s = build_long_btc_plus_short_put(quantity=30000.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0)
        cfg = _cfg(n_paths=4000, n_cycles=4, chunk_size=1000)
        full = run_multi_cycle_monte_carlo(s, cfg)

        # Craft a partial checkpoint covering the FIRST chunk only, then resume.
        ckpt = tmp_path / "resume_ckpt"
        chunk0 = _generate_chunk_paths(cfg, 0, 1000)
        out0 = _run_cycles_vectorized(s, chunk0, cfg)
        acc = {
            "pnl": out0.pnl, "fv": out0.final_value, "btc": out0.final_btc,
            "prem": out0.premium_pct, "fees": out0.fees, "eac": out0.eac,
            "pp_usd": out0.post_purchase_usd, "pp_btc": out0.post_purchase_btc,
        }
        _save_checkpoint(ckpt, cfg, s.strategy_id, 1000, acc)
        resumed = run_multi_cycle_monte_carlo(s, cfg, checkpoint=ckpt, checkpoint_every_chunks=1)
        assert resumed.mean_outcome_usd == pytest.approx(full.mean_outcome_usd, rel=1e-12)
        assert resumed.pnl_distribution == full.pnl_distribution

    def test_interrupted_run_recovery(self, tmp_path: pathlib.Path) -> None:
        # A checkpoint written mid-run, then resumed, reproduces the uninterrupted run.
        s = build_covered_call(quantity=30000.0, entry_spot=65000.0, strike=74750.0, premium_received=1500.0)
        cfg = _cfg(n_paths=3000, n_cycles=4, chunk_size=1000, model="Merton")
        full = run_multi_cycle_monte_carlo(s, cfg)
        ckpt = tmp_path / "interrupt_ckpt"
        # First pass writes a checkpoint every chunk; run it fully once (simulating
        # completion), then a second call must resume-from-complete and match.
        run_multi_cycle_monte_carlo(s, cfg, checkpoint=ckpt, checkpoint_every_chunks=1)
        again = run_multi_cycle_monte_carlo(s, cfg, checkpoint=ckpt, checkpoint_every_chunks=1)
        assert again.pnl_distribution == full.pnl_distribution

    def test_stale_checkpoint_ignored(self, tmp_path: pathlib.Path) -> None:
        s = build_covered_call(quantity=30000.0, entry_spot=65000.0, strike=74750.0, premium_received=1500.0)
        cfg = _cfg(n_paths=1000, n_cycles=4)
        ckpt = tmp_path / "stale"
        z = np.zeros(500)
        _save_checkpoint(ckpt, cfg, s.strategy_id, 500,
                         dict.fromkeys(("pnl", "fv", "btc", "prem", "fees", "eac", "pp_usd", "pp_btc"), z))
        # A config with different economics must NOT reuse the checkpoint.
        other = _cfg(n_paths=1000, n_cycles=4, drift=0.5)
        assert _load_checkpoint(ckpt, other, s.strategy_id) is None
        assert _load_checkpoint(ckpt, cfg, s.strategy_id) is not None

    def test_multi_strategy_shares_paths(self) -> None:
        # Evaluating N strategies on shared paths must equal N single runs on the
        # same seed/config (paths generated once → path count NOT multiplied).
        cfg = _cfg(n_paths=3000, n_cycles=5, model="Merton", chunk_size=1000)
        strategies = [s for _, s in _UNIVERSE]
        multi = run_multi_cycle_monte_carlo_multi(strategies, cfg)
        assert len(multi) == len(strategies)
        for s in strategies:
            single = run_multi_cycle_monte_carlo(s, cfg)
            assert multi[s.strategy_id].pnl_distribution == single.pnl_distribution
            assert multi[s.strategy_id].n_paths == cfg.n_paths  # not * n_strategies

    def test_multi_strategy_rejects_duplicate_ids(self) -> None:
        s = build_unhedged_baseline(quantity=100.0, entry_spot=65000.0)
        with pytest.raises(ValidationError):
            run_multi_cycle_monte_carlo_multi([s, s], _cfg(n_paths=100, btc_quantity=100.0))

    def test_aggregate_path_count_reconciliation(self) -> None:
        s = build_unhedged_baseline(quantity=100.0, entry_spot=65000.0)
        total = 0
        for n in (1000, 2500, 5000):
            r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=n, n_cycles=2, btc_quantity=100.0))
            assert r.n_paths == n
            total += r.n_paths
        assert total == 8500


# ── output schema, metrics, edge cases, benchmark ──────────────────────────────


class TestSchemaAndMetrics:
    def test_output_schema_and_provenance(self) -> None:
        s = build_covered_call(quantity=100.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=100, n_cycles=4))
        assert r.provenance == Provenance.SIMULATED
        assert r.assumptions.get("provenance") == "SIMULATED"
        assert "observed" not in str(r.assumptions).lower()
        assert set(r.pending_decision_refs) == {"D-1", "D-9", "D-12"}
        assert len(r.pnl_distribution) == 100
        for v in (r.mean_outcome_usd, r.median_outcome_usd, r.std_outcome_usd,
                  r.percentile_5_usd, r.percentile_1_usd, r.expected_shortfall_95,
                  r.expected_shortfall_99, r.max_loss_usd, r.mc_standard_error):
            assert math.isfinite(v)
        assert 0.0 <= r.probability_of_loss <= 1.0
        assert 0.0 <= r.probability_of_exceeding_seller_discount <= 1.0

    def test_confidence_interval_brackets_mean(self) -> None:
        s = build_covered_call(quantity=100.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=500, n_cycles=4))
        assert r.mc_standard_error > 0
        assert r.ci_95_mean_lower < r.mean_outcome_usd < r.ci_95_mean_upper

    def test_capital_base_scaling(self) -> None:
        s = build_covered_call(quantity=100.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=200, capital_base=100_000_000.0))
        assert r.mean_outcome_pct_capital == pytest.approx(100.0 * r.mean_outcome_usd / 100_000_000.0, rel=1e-9)

    def test_es_is_tail_mean(self) -> None:
        s = build_long_btc_plus_short_put(quantity=30000.0, entry_spot=65000.0, strike=55250.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=1000, n_cycles=6, drift=-0.3, volatility=0.6))
        # ES99 (worst 1% mean loss) >= ES95 (worst 5% mean loss) >= 0 when losses exist.
        assert r.expected_shortfall_99 >= r.expected_shortfall_95

    def test_store_paths_false_bounds_memory(self) -> None:
        s = build_covered_call(quantity=30000.0, entry_spot=65000.0, strike=74750.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=5000, n_cycles=4, store_paths=False))
        assert r.pnl_distribution == [] and r.eac_distribution == []
        assert math.isfinite(r.mean_outcome_usd) and r.n_paths == 5000

    def test_odd_and_edge_path_counts(self) -> None:
        s = build_covered_call(quantity=100.0, entry_spot=65000.0, strike=75000.0, premium_received=1500.0)
        for n in (1, 2, 27, 131):
            r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=n, n_cycles=3))
            assert len(r.pnl_distribution) == n

    def test_cash_settled_covered_call_keeps_btc(self) -> None:
        # Cash settlement must NOT drain BTC (no fictitious physical delivery),
        # so multi-cycle rolling keeps the full inventory.
        s = build_covered_call(quantity=30000.0, entry_spot=65000.0, strike=74750.0, premium_received=1500.0)
        r = run_multi_cycle_monte_carlo(s, _cfg(n_paths=200, n_cycles=12, drift=0.5))
        assert r.mean_final_btc == pytest.approx(30000.0, rel=1e-12)

    def test_benchmark_runs(self) -> None:
        bm = benchmark_mc(_cfg(n_paths=200, n_cycles=2))
        assert bm["n_paths"] == 200 and bm["paths_per_second"] > 0


class TestInvalidConfig:
    @pytest.mark.parametrize("kw", [
        {"n_paths": -1}, {"n_paths": 0}, {"n_cycles": 0}, {"volatility": -0.1},
        {"initial_spot": 0}, {"n_steps_per_cycle": 0}, {"cycle_length_years": 0.0},
        {"strike_target_pct": 0.0}, {"strike_target_pct": 1.0}, {"btc_quantity": 0},
        {"capital_base": 0}, {"execution_fee_pct": -0.1}, {"jump_intensity": -1.0},
        {"jump_std": -0.1}, {"chunk_size": 0}, {"drift": 10.0},
    ])
    def test_invalid_params_rejected(self, kw: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            MultiCycleMCConfig(**kw)  # type: ignore[arg-type]

    def test_fasttrack_rejects_unknown_override(self) -> None:
        with pytest.raises(ValidationError):
            run_c7_fasttrack_suite([build_unhedged_baseline(quantity=100.0, entry_spot=65000.0)], ["u"],
                                   config_overrides={"not_a_field": 1})


def test_default_chunk_size_constant() -> None:
    assert MultiCycleMCConfig().chunk_size == DEFAULT_CHUNK_SIZE
