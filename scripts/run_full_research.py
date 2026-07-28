#!/usr/bin/env python3
"""Full research pipeline CLI.

Usage:
  python scripts/run_full_research.py \\
    --config config/research_nightly.yaml \\
    --output results/research/<run-id> \\
    [--resume]

Massive is the primary historical BTC spot source.
Never silently substitutes another provider.
An explicitly-enabled CryptoDataDownload fallback is allowed.
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from research.runner import run_research


def main() -> int:
    parser = argparse.ArgumentParser(description="BTC 30k Engine — Full Research Pipeline")
    parser.add_argument("--config", type=str, default="config/research_nightly.yaml",
                        help="Path to research configuration YAML")
    parser.add_argument("--output", type=str, required=True,
                        help="Output directory for research results")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from checkpoint if available")
    parser.add_argument("--log-level", type=str, default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log_dir = pathlib.Path(args.output) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / "research.log")
    fh.setLevel(getattr(logging, args.log_level))
    logging.getLogger("research").addHandler(fh)

    logger = logging.getLogger("research")
    logger.info(f"Starting research run. Config: {args.config}, Output: {args.output}")

    rc = run_research(
        config_path=args.config,
        output_dir=args.output,
        resume=args.resume,
    )

    if rc == 0:
        logger.info("Research run completed successfully.")
    else:
        logger.error(f"Research run failed with exit code {rc}")

    return rc


if __name__ == "__main__":
    sys.exit(main())
