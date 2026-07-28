# Authoritative Pre-Phase-0 Corrections

This document supersedes any conflicting statement in:

- docs/reports/deepseek_initial_audit.md
- docs/reports/minimax_initial_audit.md
- docs/reports/reconciled_initial_audit.md

It must be read before contracts.md is drafted or any A1-A6 implementation begins.

## 1. Settlement modelling

Do not use a combined enum value such as:

PHYSICAL_USD = OTC/CME

Settlement must be represented through separate fields:

- venue and product
- settlement mechanism
- settlement currency
- exercise style
- contract multiplier
- delivery or settlement price convention

Minimum settlement mechanisms:

- cash
- futures_delivery_then_cash
- physical_underlying

Minimum settlement currencies:

- BTC
- USDC
- USD

Venue/product examples must remain separate:

- Deribit inverse option
- Deribit linear option
- CME option on Bitcoin futures
- OTC option

Economic payoff exposure must remain separate from actual venue settlement and
from any discretionary BTC inventory purchase after settlement.

Physical BTC delivery may be modelled only when the actual contract explicitly
requires it.

## 2. Pure pricing functions

Core numerical functions must remain pure and parameter-driven:

- price()
- greeks()
- strike_for_delta()
- implied_vol()
- premium_pct_at_delta()

They must receive spot, strike, rate, volatility, time and related inputs as
arguments.

They must not directly read config/params.yaml.

A configuration or application layer may validate params.yaml and inject those
values into the numerical functions.

Hull, Haug and QuantLib validation tests must use fixed independent test
vectors. Business-configuration changes must never change textbook golden
tests.

## 3. Existing OptionQuote interface

Do not automatically replace the tested OptionQuote dataclass with Pydantic.

Preserve existing tested public interfaces unless contracts.md explicitly
approves a migration.

Use Pydantic primarily at:

- configuration boundaries
- API and data-ingestion boundaries
- provenance schemas
- external report schemas
- persisted results

Pure numerical internals may continue using frozen typed dataclasses.

## 4. Inverse-BTC formulas

Do not directly implement the inverse-BTC formulas contained in section 10.8
of the reconciled audit.

They are not contract-ready because they do not fully specify:

- numeraire
- USD and BTC units
- option premium quotation convention
- contract multiplier
- delivery price
- settlement currency
- spot-position valuation convention
- long versus short sign convention

The complete formula must be re-derived from current official venue
documentation and independently unit-checked before contracts.md is frozen.

## 5. Source ownership

- Massive is the primary historical BTC spot source.
- Deribit is the source for DVOL, live Deribit option-chain data and Deribit
  contract information.
- Historical observed option data must come from an approved venue or vendor
  archive.
- CryptoDataDownload may be used only as an explicitly labelled fallback.
- Missing historical option values must carry model_reconstructed provenance.

## 6. Authority rule

Where an audit conflicts with this document, this document prevails.

Where this document is silent, current official venue documentation prevails
over textbooks for contract, exercise, margin and settlement behaviour.
