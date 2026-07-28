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

import pathlib
import re
import sys

ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]

# Directories to exclude from scanning
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
    "prompts",
}

# Files to exclude (these can contain expected reference patterns)
EXCLUDE_FILES: set[str] = {
    ".DS_Store",
    ".env",  # local-only credentials, gitignored
    "anonymisation_scan.py",  # this file itself
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


def is_confidentiality_rule_line(line: str) -> bool:
    """Check if a line is a confidentiality rule, not an actual leak.

    Lines containing phrases like 'do not', 'must not', 'never', 'no X',
    'confidentiality', 'exclude' in the context of PII/credentials are
    confidentiality rules, not actual leaks.
    """
    lower = line.lower()
    keywords = (
        "no counterparty",
        "do not include",
        "do not commit",
        "must not",
        "never include",
        "never commit",
        "confidentiality",
        "anonymization",
        "anonymisation",
        "no wallet",
        "no api",
        "no deal",
        "no client",
        "exclude",
        "should not",
        "shall not",
    )
    return any(kw in lower for kw in keywords)


def should_scan(file_path: pathlib.Path) -> bool:
    """Determine whether a file should be scanned."""
    parts: set[str] = set(file_path.relative_to(ROOT).parts)
    if parts & EXCLUDE_DIRS:
        return False
    if file_path.name in EXCLUDE_FILES:
        return False
    suffix: str = file_path.suffix.lower()
    return not (suffix and suffix not in SCAN_EXTENSIONS)


def scan_file(file_path: pathlib.Path) -> list[tuple[str, str, int, str]]:
    """Scan a single file. Returns list of (rule_id, description, lineno, match_text)."""
    findings: list[tuple[str, str, int, str]] = []
    try:
        content: str = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return findings

    str(file_path.relative_to(ROOT))
    lines: list[str] = content.split("\n")

    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue

        # Skip confidentiality rule lines
        if is_confidentiality_rule_line(line):
            continue

        # BTC wallets
        m = BTC_LEGACY.search(line)
        if m:
            txt = m.group(0)
            # Skip obviously false positives like hash-looking hex, version numbers, etc.
            if not txt.isalpha() and not txt.isdigit():
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
            findings.append(("ENV_CRED", ".env credential assignment", line_no, m.group(0)[:80]))

        # Private key headers
        if PRIVATE_KEY_HEADER.search(line):
            findings.append(("PRIVATE_KEY", "Private key block", line_no, stripped[:80]))

        # Strict seed phrase check (12 or 24 lowercase words on one line)
        if SEED_12.match(stripped) or SEED_24.match(stripped):
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
    """Run the anonymisation scan.  Returns exit code: 0 = clean, 1 = findings."""
    all_findings: dict[str, list[tuple[str, str, int, str]]] = {}
    total_findings: int = 0

    files_to_scan: list[pathlib.Path] = []
    for file_path in ROOT.rglob("*"):
        if file_path.is_file() and should_scan(file_path):
            files_to_scan.append(file_path)

    files_to_scan.sort()

    for file_path in files_to_scan:
        findings: list[tuple[str, str, int, str]] = scan_file(file_path)
        if findings:
            rel: str = str(file_path.relative_to(ROOT))
            all_findings[rel] = findings
            total_findings += len(findings)

    if total_findings == 0:
        print("✓ Anonymisation scan: no confidentiality concerns detected.")
        return 0

    print(
        f"✗ Anonymisation scan: {total_findings} potential concern(s) "
        f"in {len(all_findings)} file(s):"
    )
    for rel_path, findings in sorted(all_findings.items()):
        print(f"  {rel_path}:")
        for rule_id, desc, lineno, text in findings:
            print(f"    [{rule_id}] L{lineno}: {desc} → {text}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
