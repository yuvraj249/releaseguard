#!/usr/bin/env python3
"""
ReleaseGuard Headless CLI Runner
Production-ready CI/CD tool to evaluate test failure logs and git diffs directly.
Exits with code 0 (Safe / Quarantined) or code 1 (Hard Block).
"""

import sys
import os
import argparse
import json
import subprocess

# Import the core evaluation engine from server.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import analyze_test_failure


def get_git_diff_files(base_branch="origin/main"):
    """Extract list of changed files from the current Git repository."""
    try:
        cmd = ["git", "diff", "--name-only", base_branch]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        if out:
            return [f.strip() for f in out.splitlines() if f.strip()]
    except Exception:
        pass

    try:
        cmd = ["git", "diff", "--name-only", "HEAD~1"]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        if out:
            return [f.strip() for f in out.splitlines() if f.strip()]
    except Exception:
        pass

    return []


def main():
    parser = argparse.ArgumentParser(
        description="ReleaseGuard: Headless CI/CD Test Triage & Release Decision Tool"
    )
    parser.add_argument(
        "--log-file", "-l", help="Path to the test failure log file (Cypress / Playwright)"
    )
    parser.add_argument(
        "--pr-files", "-f", nargs="*", help="List of files touched by this PR (space separated)"
    )
    parser.add_argument(
        "--auto-git", "-g", action="store_true", help="Automatically detect changed files using git diff"
    )
    parser.add_argument(
        "--pr-title", "-t", default="", help="Pull request title for semantic context"
    )
    parser.add_argument(
        "--flake-rate", "-r", type=float, default=15.0, help="Historical flake rate of this test (default: 15.0%%)"
    )
    parser.add_argument(
        "--json", "-j", action="store_true", help="Output raw JSON instead of human-readable text"
    )
    parser.add_argument(
        "--fail-on-block", action="store_true", default=True, help="Exit with code 1 if verdict is HARD_BLOCK (default: True)"
    )

    args = parser.parse_args()

    # Read log from file or stdin
    test_log = ""
    if args.log_file and os.path.exists(args.log_file):
        with open(args.log_file, "r") as f:
            test_log = f.read()
    elif not sys.stdin.isatty():
        test_log = sys.stdin.read()
    else:
        print("Error: No test log provided. Pass --log-file <path> or pipe via stdin.", file=sys.stderr)
        sys.exit(2)

    # Detect PR files
    pr_files = args.pr_files or []
    if args.auto_git or not pr_files:
        detected = get_git_diff_files()
        if detected:
            pr_files.extend(detected)

    # Run decision engine
    result = analyze_test_failure(test_log, pr_files, args.pr_title, args.flake_rate)

    # Output formatted result
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("\n" + "=" * 65)
        print("🚦 RELEASEGUARD CI/CD DECISION REPORT")
        print("=" * 65)
        
        GREEN = "\033[92m"
        RED = "\033[91m"
        YELLOW = "\033[93m"
        RESET = "\033[0m"
        BOLD = "\033[1m"

        verdict_color = GREEN if result["verdict_color"] == "green" else (RED if result["verdict_color"] == "red" else YELLOW)

        print(f"VERDICT:       {verdict_color}{BOLD}{result['verdict_badge']}{RESET}")
        print(f"RISK SCORE:    {verdict_color}{result['risk_score']}/100{RESET} (Confidence: {result['confidence']}%)")
        print(f"CATEGORY:      {result['category']}")
        print(f"DIFF OVERLAP:  {'YES - ' + ', '.join(result['correlated_domains']) if result['has_correlation'] else 'NONE (Unrelated files)'}")
        print("-" * 65)
        print(f"ROOT CAUSE:    {result['root_cause']}")
        print(f"PM TRADE-OFF:  {result['trade_off']}")
        print(f"RECOMMENDED:   {BOLD}{result['action']}{RESET}")
        print("=" * 65 + "\n")

    # CI exit code gating
    if args.fail_on_block and result["verdict"] == "HARD_BLOCK":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
