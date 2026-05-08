"""
CLI entrypoint for the AGC scraper.

Usage:
    python run.py --step 1                          # listing pages only
    python run.py --step 2                          # detail pages only (needs step 1 first)
    python run.py --step all                        # both steps

    python run.py --step 1 --types updated revised  # only fetch updated + revised lists
    python run.py --step 2 --detail-types updated   # only scrape updated acts in detail

    python run.py --step 1 --dry-run                # print what would run, no requests

    python run.py --list-stubs                      # show acts that failed and need manual re-scrape
    python run.py --act 807                         # manually re-scrape one act (5 min timeout)
"""
import argparse
import logging
import sys
from scraper.config import LOG_FILE


def _setup_logging() -> None:
    fmt = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="lom.agc.gov.my scraper — Phase 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step",
        choices=["1", "2", "all"],
        default="all",
        help="Which step to run (default: all)",
    )
    parser.add_argument(
        "--types",
        nargs="+",
        choices=["updated", "revised", "repealed", "amendment", "translated"],
        default=["updated", "revised", "repealed", "amendment", "translated"],
        help="Act types for step 1 (default: all)",
    )
    parser.add_argument(
        "--detail-types",
        nargs="+",
        choices=["updated", "revised"],
        default=["updated", "revised"],
        help="Act types to scrape detail pages for in step 2 (default: updated revised)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without making any requests",
    )
    parser.add_argument(
        "--list-stubs",
        action="store_true",
        help="List all acts that failed step 2 and need manual re-scraping",
    )
    parser.add_argument(
        "--act",
        metavar="ACT_NUMBER",
        help="Manually re-scrape a single act with a 5-minute timeout (for slow pages)",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        help="Path to a saved page source HTML file — use with --act to skip the HTTP request",
    )

    args = parser.parse_args()
    _setup_logging()

    if args.list_stubs:
        from scraper.step2_detail import list_stubs
        list_stubs()
        return

    if args.act:
        from scraper.step2_detail import run_single_act
        run_single_act(args.act, html_path=args.html)
        return

    if args.dry_run:
        print(f"DRY RUN — step={args.step}")
        if args.step in ("1", "all"):
            print(f"  Step 1: would fetch types: {args.types}")
        if args.step in ("2", "all"):
            print(f"  Step 2: would scrape detail-types: {args.detail_types}")
        return

    if args.step in ("1", "all"):
        from scraper.step1_index import run_step1
        run_step1(types=args.types)

    if args.step in ("2", "all"):
        from scraper.step2_detail import run_step2
        run_step2(detail_types=args.detail_types)


if __name__ == "__main__":
    main()
