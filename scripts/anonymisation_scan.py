#!/usr/bin/env python3
"""Anonymisation and confidentiality scan.

Scans the entire repository for:
  - Wallet addresses (BTC, ETH patterns)
  - API keys / credentials
  - Private keys
  - Deal-identifying information (actual identifiers, not confidentiality rules)

Runs as a CI gate (exit code 1 if any pattern matches).
Phase 0 — frozen per contracts.md §"Confidentiality" and P0-8.

Usage:
    python3 scripts/anonymisation_scan.py
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]

# Directories to exclude from scanning.
# FRF-038 / AT-033: `prompts/` is NO LONGER excluded — the flagged
# confidentiality artefact lived there precisely because the scan skipped it.
EXCLUDE_DIRS: set[str] = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    ".opencode",
    "private_reference_library",
    "node_modules",
    # Git-ignored generated / non-source trees (see .git/info/exclude). These
    # are bulk research output and confidential source copies that are NOT
    # committed; the automated gate protects the version-controlled source tree.
    # The owner-run deal-identifier pass can target them separately if required.
    "results",
    "exports",
    "logs",
    ".a2_sources",
    "source_materials",
}

# RHS values that are documentation placeholders, not real secrets.
_PLACEHOLDER_VALUES: frozenset[str] = frozenset({
    "value", "'value'", '"value"', "placeholder", "xxx", "example",
    "changeme", "your_key", "your-key", "none", "null", "redacted",
})

# Common English function words that are NOT in the BIP39 wordlist; their
# presence proves a 12/24-word line is prose, not a seed phrase.
_NON_BIP39_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "of", "to", "its", "are", "with", "for", "not", "may",
    "this", "that", "from", "was", "were", "will", "can", "has", "have",
    "had", "been", "which", "would", "or", "an", "as", "at", "by", "be",
    "is", "it", "in", "on", "until", "per", "vs", "via", "into", "than",
})

# Maximum bytes read from a single file for the (opt-in) binary deal-term pass.
# Files larger than this are still scanned up to the cap and a note is printed
# (no silent truncation — FRF-029).
_MAX_BINARY_BYTES: int = 64 * 1024 * 1024

# Files to exclude (these can contain expected reference patterns)
EXCLUDE_FILES: set[str] = {
    ".DS_Store",
    ".env",  # local-only credentials, gitignored
    "anonymisation_scan.py",  # this file itself
    # Owner disposition A-2026-07-29 (FRF-038): the private deal-identifier
    # dictionary self-matches by construction and must never be committed.
    ".deal_identifiers.local",
}

# File extensions to scan
SCAN_EXTENSIONS: set[str] = {
    ".py",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".jsonc",
    ".cfg",
    ".ini",
    ".csv",
    ".tsv",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
}

# ── Confidentiality patterns ─────────────────────────────────────────────────

# BTC wallet addresses (main patterns only)
BTC_LEGACY = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
BTC_BECH32 = re.compile(r"\bbc1[a-z0-9]{39,59}\b")

# ETH/hex wallet addresses (40-hex segment)
ETH_ADDR = re.compile(r"\b0x[a-fA-F0-9]{40}\b")

# API keys — assignment-like or embedded in strings
API_KEY_RE = re.compile(
    r"(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?key|private[_-]?key)"
    r"\s*[:=]\s*[\'\"][^\'\"]{8,}[\'\"]",
    re.IGNORECASE,
)

# Private key headers (PEM)
PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH|PGP|PRIVATE)\s+KEY",
    re.IGNORECASE,
)

# Seed phrases: exactly 12 or 24 lowercase words on a single line with no punctuation
# This is much stricter than before — avoids matching prose in documents.
SEED_12 = re.compile(r"^[a-z]{2,}(?:\s+[a-z]{2,}){11}$")
SEED_24 = re.compile(r"^[a-z]{2,}(?:\s+[a-z]{2,}){23}$")

# URLs with embedded credentials
URL_CREDS = re.compile(r"https?://[^@/\s]+:[^@/\s]+@")

# .env credential patterns (KEY=value, KEY="value", KEY='value')
# Specifically does not flag blank placeholders (KEY= or KEY="" or KEY='')
ENV_CRED_RE = re.compile(
    r"^[A-Z_]*?(?:API[_-]?KEY|KEY|SECRET|TOKEN)[A-Z_]*?=\s*(?!\s*$)"
    r"(?:[^\s\"']+|\"[^\"']+\"|'[^\"']+')$",
    re.IGNORECASE,
)

# AWS access keys
AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def load_deal_terms(extra: frozenset[str] | None = None) -> frozenset[str]:
    """Confidential deal / firm-identifying terms to flag anywhere they appear.

    The real terms are confidential and MUST NOT be committed. They are supplied
    at scan time via, in priority order:
      - the ``ANONYMISATION_DEAL_TERMS`` environment variable (comma-separated),
      - a local, git-ignored file ``scripts/.deal_identifiers.local`` (one term
        per line; ``#`` comments allowed),
      - the ``extra`` argument (used by tests to inject a synthetic token).

    Matching is case-insensitive and applies to EVERY line — including comments,
    lines that mention "exclude"/"confidentiality", ``prompts/`` files and (when
    enabled) binary content. There are no exemptions; that is the FRF-038 fix.
    Default CI runs with no terms configured, so the generic credential/wallet
    scan behaviour is unchanged and no confidential value is hard-coded.
    """
    terms: set[str] = set()
    env = os.environ.get("ANONYMISATION_DEAL_TERMS", "")
    for tok in env.split(","):
        tok = tok.strip()
        if tok:
            terms.add(tok.lower())
    local = ROOT / "scripts" / ".deal_identifiers.local"
    if local.is_file():
        for raw in local.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if raw and not raw.startswith("#"):
                terms.add(raw.lower())
    if extra:
        terms.update(t.lower() for t in extra)
    return frozenset(terms)


def is_text_file(file_path: pathlib.Path) -> bool:
    suffix: str = file_path.suffix.lower()
    return not suffix or suffix in SCAN_EXTENSIONS


def should_consider(file_path: pathlib.Path) -> bool:
    """Whether a file is in scope at all (dir/file exclusions only)."""
    parts: set[str] = set(file_path.relative_to(ROOT).parts)
    if parts & EXCLUDE_DIRS:
        return False
    return file_path.name not in EXCLUDE_FILES


def scan_file(
    file_path: pathlib.Path,
    deal_terms: frozenset[str] = frozenset(),
) -> list[tuple[str, str, int, str]]:
    """Scan a single file. Returns list of (rule_id, description, lineno, match_text).

    Two passes:
      * deal-identifier pass — runs on EVERY line (no comment/keyword exemption)
        whenever `deal_terms` is non-empty; also runs on binary files.
      * generic credential/wallet/seed pass — runs on text files only, still
        skipping blank lines (only) to avoid binary false positives.
    """
    findings: list[tuple[str, str, int, str]] = []
    text_file = is_text_file(file_path)
    if not text_file and not deal_terms:
        # Nothing to do on a binary file when no deal terms are configured.
        return findings
    try:
        raw_bytes = file_path.read_bytes()
    except OSError:
        return findings
    if len(raw_bytes) > _MAX_BINARY_BYTES:
        print(f"  · note: {file_path.relative_to(ROOT)} exceeds "
              f"{_MAX_BINARY_BYTES} bytes — scanning first {_MAX_BINARY_BYTES}.")
        raw_bytes = raw_bytes[:_MAX_BINARY_BYTES]
    content = raw_bytes.decode("utf-8", errors="replace")

    lines: list[str] = content.split("\n")

    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()

        # ── deal-identifier pass (no exemptions) ─────────────────────────
        if deal_terms:
            low = line.lower()
            for term in deal_terms:
                if term and term in low:
                    findings.append((
                        "DEAL_IDENTIFIER",
                        "Deal/firm-identifying term",
                        line_no,
                        stripped[:80] or line[:80],
                    ))
                    break

        if not text_file:
            continue

        # Skip only genuinely empty lines. Comments are NO LONGER skipped
        # and confidentiality-rule keywords no longer exempt a line.
        if not stripped:
            continue

        # BTC wallets
        m = BTC_LEGACY.search(line)
        if m:
            txt = m.group(0)
            # Skip obviously false positives: all-alpha/all-digit tokens and
            # pure-hexadecimal strings (data hashes/checksums are not base58
            # addresses — base58 excludes '0' and real addresses carry a
            # mixed-case checksum).
            is_pure_hex = all(c in "0123456789abcdefABCDEF" for c in txt)
            if not txt.isalpha() and not txt.isdigit() and not is_pure_hex:
                findings.append(("BTC_WALLET", "BTC legacy wallet address", line_no, txt))
        else:
            m = BTC_BECH32.search(line)
            if m:
                findings.append(("BTC_WALLET_BECH32", "BTC Bech32 wallet address", line_no, m.group(0)))

        # ETH wallets (skip if it's part of a larger hex hash or import path)
        m = ETH_ADDR.search(line)
        if m:
            txt = m.group(0)
            # Skip if it's a test vector or file path
            if "tx_" not in stripped.lower() and "hash" not in stripped.lower():
                findings.append(("ETH_ADDR", "Ethereum wallet address", line_no, txt))

        # API keys (quoted assignment in code)
        m = API_KEY_RE.search(line)
        if m:
            findings.append(("API_KEY", "Potential API key in code", line_no, m.group(0)[:80]))

        # .env credential assignments (KEY=value, KEY="value", KEY='value')
        m = ENV_CRED_RE.search(stripped)
        if m:
            rhs = m.group(0).split("=", 1)[-1].strip().strip("'\"").lower()
            if rhs not in _PLACEHOLDER_VALUES:
                findings.append(("ENV_CRED", ".env credential assignment", line_no, m.group(0)[:80]))

        # Private key headers
        if PRIVATE_KEY_HEADER.search(line):
            findings.append(("PRIVATE_KEY", "Private key block", line_no, stripped[:80]))

        # Strict seed phrase check (12 or 24 lowercase words on one line).
        # A line containing common English function words (which are not in the
        # BIP39 wordlist) is prose, not a seed phrase.
        if SEED_12.match(stripped) or SEED_24.match(stripped):
            words = set(stripped.split())
            if not (words & _NON_BIP39_STOPWORDS):
                findings.append(("SEED_PHRASE", "Seed phrase (12 or 24 words)", line_no, stripped[:80]))

        # URLs with credentials
        if URL_CREDS.search(line):
            findings.append(("URL_CREDS", "URL with embedded credentials", line_no, stripped[:80]))

        # AWS keys
        m = AWS_KEY.search(line)
        if m:
            findings.append(("AWS_KEY", "AWS access key pattern", line_no, m.group(0)))

    return findings


def main() -> int:
    """Run the anonymisation scan.

    Exit codes:
      * 1 if any CREDENTIAL/wallet/key/seed pattern is found (always blocking).
      * DEAL_IDENTIFIER findings on approved project identifiers are ACCEPTED
        internally (owner disposition A-2026-07-29 / FRF-038): they are reported
        but do NOT block by default. Confidentiality scanning remains mandatory
        before any public/client-facing/external package — run with `--strict`
        (or ANONYMISATION_STRICT=1) to make deal-identifier findings blocking.
    """
    strict = ("--strict" in sys.argv) or os.environ.get("ANONYMISATION_STRICT") == "1"
    all_findings: dict[str, list[tuple[str, str, int, str]]] = {}

    deal_terms = load_deal_terms()
    if deal_terms:
        print(f"· deal-identifier pass enabled ({len(deal_terms)} term(s), including "
              f"binary content){' — STRICT (external)' if strict else ' — internal (accepted)'}.")

    files_to_scan: list[pathlib.Path] = []
    for file_path in ROOT.rglob("*"):
        if file_path.is_file() and should_consider(file_path):
            files_to_scan.append(file_path)
    files_to_scan.sort()

    for file_path in files_to_scan:
        findings: list[tuple[str, str, int, str]] = scan_file(file_path, deal_terms)
        if findings:
            all_findings[str(file_path.relative_to(ROOT))] = findings

    cred_count = sum(
        1 for fs in all_findings.values() for f in fs if f[0] != "DEAL_IDENTIFIER"
    )
    deal_count = sum(
        1 for fs in all_findings.values() for f in fs if f[0] == "DEAL_IDENTIFIER"
    )

    if cred_count == 0 and deal_count == 0:
        print("✓ Anonymisation scan: no confidentiality concerns detected.")
        return 0

    # Credential/wallet/key/seed findings always block.
    if cred_count:
        print(f"✗ Anonymisation scan: {cred_count} credential/wallet concern(s):")
        for rel_path, findings in sorted(all_findings.items()):
            creds = [f for f in findings if f[0] != "DEAL_IDENTIFIER"]
            if creds:
                print(f"  {rel_path}:")
                for rule_id, desc, lineno, text in creds:
                    print(f"    [{rule_id}] L{lineno}: {desc} → {text}")

    if deal_count:
        n_files = sum(1 for fs in all_findings.values() if any(f[0] == "DEAL_IDENTIFIER" for f in fs))
        verb = "BLOCKING (strict/external mode)" if strict else "ACCEPTED internally (owner disposition A-2026-07-29)"
        print(f"· deal-identifier: {deal_count} occurrence(s) of approved project "
              f"identifiers in {n_files} file(s) — {verb}.")

    if cred_count or (deal_count and strict):
        return 1
    print("✓ Anonymisation scan: no blocking concerns (deal-identifier occurrences accepted).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
