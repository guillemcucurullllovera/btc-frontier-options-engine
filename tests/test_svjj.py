"""C10 · N1.1 — asymmetric price-vol co-jump SV model (SVJJ): CF + MC validation.

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED jumps; canonical main untouched. Oracles: lambda=0 is
exactly Heston; mu_v=0 is exactly the factorised asymmetric-jump Bates (machine-epsilon); the CF is a
valid physical-process CF (phi(0)=1, |phi|<=1 real u, conjugate symmetry); the analytical CF matches the
QE + jump MC within k*SE (the key CF-vs-MC gate); the double-normal reproduces the downside asymmetry
(eta~1.4-1.5); and the fit recovers a simulated jump sample. (The CF is NOT a Q-martingale pricer — option
marks use the frozen Q_BATES; the vol co-jump's convexity is intentionally uncompensated in the physical
drift, and CF and MC share that convention, so CF-vs-MC holds.)
"""

from __future__ import annotations

import numpy as np

from pricing.cf.characteristic_functions import Heston
from pricing.cf.svjj import SVJJ, DoubleNormalJump, fit_double_normal
from strategy.svjj_sim import simulate_svjj_terminal

_J = DoubleNormalJump(0.446, 0.097, 0.0345, -0.0833, 0.1359)


def _model(lam: float = 4.5, mu_v: float = 0.10) -> SVJJ:
    return SVJJ(mu=0.0, v0=0.25, kappa=3.0, theta=0.25, sigma=0.6, rho=-0.4, lam=lam, jump=_J, mu_v=mu_v)


def test_svjj_reduces_to_heston_when_lambda_zero() -> None:
    m = _model(lam=0.0)
    h = Heston(0.0, 0.0, 0.25, 3.0, 0.25, 0.6, -0.4)
    u = np.array([0.5, 1.0 + 0.3j, 3.0, -2.0], dtype=np.complex128)
    assert np.max(np.abs(m.cf(u, 0.5) - h.cf(u, 0.5))) == 0.0


def test_svjj_reduces_to_factorized_bates_when_no_vol_jump() -> None:
    """mu_v=0: the co-jump collapses to a price-jump-only factor Heston * exp(lam T (phi_price-1-iu kappa))."""
    m = _model(mu_v=0.0)
    h = Heston(0.0, 0.0, 0.25, 3.0, 0.25, 0.6, -0.4)
    u = np.array([0.5, 1.0, 3.0, -2.0], dtype=np.complex128)
    fac = h.cf(u, 0.5) * np.exp(4.5 * 0.5 * (_J.transform(u) - 1.0 - 1j * u * _J.kappa_price))
    assert np.max(np.abs(m.cf(u, 0.5) - fac)) < 1e-12


def test_svjj_cf_is_valid() -> None:
    m = _model()
    assert m.cf(np.array([0.0 + 0j]), 0.5)[0] == 1.0 + 0.0j          # phi(0)=1
    ur = np.linspace(-40, 40, 161)
    phi = m.cf(ur.astype(np.complex128), 0.5)
    assert np.max(np.abs(phi)) <= 1.0 + 1e-6                          # |phi|<=1 for real u
    phi_neg = m.cf((-ur).astype(np.complex128), 0.5)
    assert np.max(np.abs(phi_neg - np.conj(phi))) < 1e-9             # conjugate symmetry
    assert np.all(np.isfinite(phi))


def test_svjj_cf_matches_mc_within_k_se() -> None:
    """The definitive gate: analytical CF vs the empirical CF of the QE+jump MC, within k*SE."""
    m = _model()
    S0, T, N = 100.0, 0.25, 200_000
    st = simulate_svjj_terminal(m, S0, T, N, n_steps=60, seed=7)
    x = np.log(st / S0)
    assert int(np.sum(~np.isfinite(st))) == 0
    for uu in (1.0, 2.0, -3.0, 4.0):
        emp = np.mean(np.exp(1j * uu * x))
        ana = m.cf(np.array([uu + 0j]), T)[0]
        assert abs(emp - ana) < 6.0 / np.sqrt(N)                     # within 6 SE


def test_svjj_terminal_reproducible() -> None:
    m = _model()
    a = simulate_svjj_terminal(m, 100.0, 0.25, 50_000, n_steps=45, seed=11)
    b = simulate_svjj_terminal(m, 100.0, 0.25, 50_000, n_steps=45, seed=11)
    assert np.array_equal(a, b)                                      # reproducibility contract


def test_double_normal_reproduces_downside_asymmetry() -> None:
    rng = np.random.default_rng(0)
    jr = _J.sample(rng, (2_000_000,))
    dn, up = jr[jr < 0], jr[jr > 0]
    eta = float(np.mean(np.abs(dn)) / np.mean(up))
    assert 1.3 < eta < 1.7                                           # eta ~ 1.4-1.5 (downside SIZE asymmetry)
    assert 0.35 < dn.size / jr.size < 0.5                            # frac downward


def test_muv_band_orders_downside_and_bounds_defined_risk() -> None:
    """Operational μ_v band: co-jump (μ_v>0) fattens the tail-exposed downside vs μ_v=0; the collar's
    capped tail is INVARIANT to μ_v (defined-risk bounded across the band)."""
    from strategy.bates_risk import STRUCTURES, structure_pnl
    S0, T, N = 63_402.0, 45.0 / 365.0, 120_000
    m0 = SVJJ(mu=0.0, v0=0.21, kappa=8.37, theta=0.21, sigma=5.5, rho=-0.403, lam=4.47, jump=_J, mu_v=0.0)
    m1 = SVJJ(mu=0.0, v0=0.21, kappa=8.37, theta=0.21, sigma=5.5, rho=-0.403, lam=4.47, jump=_J, mu_v=0.10)
    st0 = simulate_svjj_terminal(m0, S0, T, N, 45, seed=3)
    st1 = simulate_svjj_terminal(m1, S0, T, N, 45, seed=3)

    def _es975(st: np.ndarray, name: str) -> float:
        loss = -structure_pnl(STRUCTURES[name], S0, st, T)
        return float(np.mean(loss[loss >= np.percentile(loss, 97.5)]))

    assert _es975(st1, "unhedged") > _es975(st0, "unhedged")            # co-jump fattens the downside
    assert abs(_es975(st1, "collar") - _es975(st0, "collar")) < 1.0     # defined-risk invariant to mu_v


def test_fit_double_normal_recovers() -> None:
    rng = np.random.default_rng(1)
    truth = DoubleNormalJump(0.45, 0.10, 0.035, -0.085, 0.135)
    sample = truth.sample(rng, (4000,))
    fit = fit_double_normal(sample)
    # the fit reproduces the downside asymmetry of the sample (params are only weakly identified at n~40)
    e_fit = float(np.mean(np.abs(sample[sample < 0])) / np.mean(sample[sample > 0]))
    rng2 = np.random.default_rng(2)
    js = fit.sample(rng2, (2_000_000,))
    e_sim = float(np.mean(np.abs(js[js < 0])) / np.mean(js[js > 0]))
    assert abs(e_sim - e_fit) < 0.3                                  # fitted sim eta ~ sample eta
