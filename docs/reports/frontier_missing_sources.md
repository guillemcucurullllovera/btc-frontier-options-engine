# Frontier Missing Sources (Stage 0)

Checkpoint: `92acecf`. Companion to `frontier_reference_coverage_audit.md`.
176 raw missing-source records were collected across the 23 audit passes;
deduplicated below. "Blocking" states which downstream gate the absence blocks
(S2 = deterministic repair, HR = historical research, MC = large Monte Carlo).

## 1. Missing official / primary market-data sources

| # | Missing source | Currently relying on | Needed for | Blocking |
|---|---|---|---|---|
| MS-1 | **Historical DVOL series from official Deribit** (`get_volatility_index_data` history; depth to be confirmed) | constant IV = 0.45 assumption (`research/runner.py:339`) | contracts §6.5 premium reconstruction; every historical premium; elevated-IV hypothesis tests | HR, MC |
| MS-2 | **BTC spot history 2023-01-01 → 2024-07-28** (paid Massive tier, or approved vendor archive, or explicitly-labelled CDD fallback) | silently truncated 729-bar window starting 2024-07-29 | build-plan 2023–2026 backtest window; OOS train window; 2023–24 regime coverage | HR, MC (decision **D-11**) |
| MS-3 | **Observed historical Deribit option chains** (vendor archive: Amberdata/Tardis/Kaiko per build plan §4) — or a recorded decision that v1 proceeds on reconstruction only | nothing (no option data exists in the pipeline; presentation template falsely claims "Deribit (observed)") | honest attribution; skew-aware validation of reconstruction | HR (as labelling), optional per build plan |
| MS-4 | **CF Benchmarks BRR / BRRNY methodology guide** | contracts §3.4 naming the fixings with no cached source | CME settlement modelling; BRRNY delivery-convention entry | S2 (CME path only) |
| MS-5 | **Current CME Ch. 350A** (2026 revision; cached copy is 2023-05-19) and the CME crypto **block-minimums/TAS workbook in usable text form** | 3-year-old chapter text; binary-only xlsx | CME contract terms; institutional clip-size validation vs venue minimums | S2 (CME path), execution |
| MS-6 | **ISDA Digital Asset Derivatives Definitions booklet** (v1, 2023) | a Charles Law PLLC client memo mislabelled as the Definitions | OTC leg documentation basis (contracts §5.2 OTC row) | S2 (OTC path) |
| MS-7 | **FINMA guidance** and **Binance VIP-OTC documentation** | absent; listed as required by build plan §4 | venue/regulatory context for OTC & venue selection (D-3) | none (context) |
| MS-8 | **CME public API documentation** for `get_product_info`/`get_trades`/`get_settlement` named as `origin=cme_public_api` | none cached | contracts §4.2 origin claims | none until CME work |

## 2. Missing derivation / verification anchors

| # | Missing | Currently relying on | Needed for | Blocking |
|---|---|---|---|---|
| MS-9 | **Inverse-BTC pricing golden vectors** with documented inputs (official worked settlement example + the no-arbitrage identity price_BTC × S = Black-76 USD, derivation recorded) | self-referential tests that lock the erroneous e^{−rT} convention; contracts §13.1 rows "TBD" | fixing FRF-015; any Deribit-venue pricing | S2 |
| MS-10 | **Official Deribit statement of pre-expiry mark/quote convention for BTC-denominated premiums** (spec covers settlement; pricing convention documented via mark-price semantics) | garbled contracts §7.3 sketch | adjudicating the discount/numeraire in `pricing/inverse.py` alongside MS-9 | S2 |
| MS-11 | **BTC convenience-yield / borrow-rate source (q)** with provenance | q=0 default, unlabelled | inverse forward and pricing accuracy; sensitivity labelling | S2 (labelling), research |
| MS-12 | **Kissell I-Star parameters calibrated for BTC options/RFQ** (or explicit citation of published estimates + ASSUMED label maintained) | defaults a1=100, a2=a3=0.5, b1=0.5, a4=0.2, all ASSUMED | execution-cost realism; W-UNCALIBRATED-IMPACT | Stage 4 realism (not S2) |
| MS-13 | **Delivery-price convention data** (Deribit 07:30–08:00 TWAP series or documented proxy rule) | expiry-day close used silently | settlement realism for Deribit path | S2 (documented proxy acceptable with MODEL_RECONSTRUCTED label) |

## 3. Missing text extractions (library hygiene)

| # | Item | State |
|---|---|---|
| MS-14 | Glasserman, *Monte Carlo Methods in Financial Engineering* | cache 615 B — unusable |
| MS-15 | Cartea/Jaimungal/Penalva, *Algorithmic and High-Frequency Trading* | cache 0 B — unusable |
| MS-16 | Natenberg; *Mastering Bitcoin*; *Programming Bitcoin* EPUBs | ~114 B placeholders |
| MS-17 | Bailey et al. text at the path contracts.md §1.2 cites (`_text_cache/Textbooks/`) | absent there; the SSRN paper exists elsewhere in the library — re-cite |

## 4. Missing internal/canonical artefacts

| # | Missing | Impact |
|---|---|---|
| MS-18 | `docs/venue_rules/` content (build plan §4 side-task: fetched, dated, versioned rulebooks) | venue-rules authority claim currently unbacked in-repo |
| MS-19 | `docs/data/` data dictionary + observed-data store (`data/` does not exist) | lineage documentation gap; per-run caches are the only observed-data record |
| MS-20 | `docs/model_validation/` content | model-validation evidence lives only in generated reports |
| MS-21 | `private_reference_library/notes/`, `internal_material/`, `pillar_5_internal_materials/` | all empty — "internal materials" authority category has no content |
| MS-22 | Prompts 21–23 (never existed per git history) + a dispatch manifest of which prompts went to which external model | orchestration audit-trail gap |
| MS-23 | Per-file checksums and git SHA / environment record in run manifests | current `checksums.sha256` is one opaque aggregate including a still-appending log |
| MS-24 | Loss-cap / maximum-acceptable-loss budget in any authoritative source | registered as business decision **D-10** |
| MS-25 | Approved objective function for strategy ranking | required before any "best/optimal" claim (FRONTIER_ORCHESTRATION §1); Stage 4 gate |
| MS-26 | Approved simulation-methodology specification | FRONTIER_ORCHESTRATION §8 precondition for large MC |
| MS-27 | Third-round independent review of the A3 "final fix" | last independent verdict was NOT READY (FRF-036) |

## 5. Procurement / decision routing

- **D-11 (mandate issuer)**: pre-2024-07 spot history and (optionally) vendor
  option-chain archive — purchase vs re-scope.
- **D-10 (mandate issuer)**: loss budget.
- **Stage-2 engineering**: MS-9/MS-10/MS-13 derivation records; MS-17 re-cite;
  MS-23 manifest hardening.
- **Library maintenance**: MS-14–16 re-extraction; MS-18–21 populate or
  formally retire the directories; MS-22 record the gap.
- **No historical research (Stage 3+) may claim the 2023–2026 window** until
  MS-1 and MS-2 are resolved or the window is re-scoped by D-11.
