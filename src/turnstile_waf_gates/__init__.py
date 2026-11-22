"""turnstile_waf_gates — solve Turnstile / AWS WAF / hCaptcha tokens.

Fingerprint-first, stdlib-only, CDP-native. Zero runtime dependencies.

The real implementations live in scripts/ as standalone executables.
This package makes them pip-installable: entry points re-execute the
script files with the current interpreter, so there is exactly ONE
implementation (no drift between `scripts/` and the installed package).

Direct module execution also works:
    python -m turnstile_waf_gates solve --url https://target/login
"""
import os
import runpy
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if not SCRIPTS_DIR.is_dir():
    # editable install from the repo root: src/turnstile_waf_gates -> ../scripts
    SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if not SCRIPTS_DIR.is_dir():
    # wheel install: scripts/ shipped inside the package
    SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


def _run(script_name: str, argv_tail: list[str]) -> None:
    script = SCRIPTS_DIR / script_name
    if not script.is_file():
        # editable install from the repo root
        script = Path(__file__).resolve().parent.parent / "scripts" / script_name
    if not script.is_file():
        print(f"error: cannot locate {script_name} (looked in {SCRIPTS_DIR})",
              file=sys.stderr)
        sys.exit(5)
    sys.argv = [script_name] + list(argv_tail)
    runpy.run_path(str(script), run_name="__main__")


def main_turnstile_solve() -> None:
    _run("turnstile-solve", sys.argv[1:])


def main_hcaptcha_solve() -> None:
    _run("hcaptcha-solve", sys.argv[1:])


def main_awswaf_solve() -> None:
    _run("awswaf-solve", sys.argv[1:])


def main_batch_solve() -> None:
    _run("batch-solve", sys.argv[1:])


def main_parallel_solve() -> None:
    _run("parallel-solve", sys.argv[1:])


def main_solver_api() -> None:
    _run("solver-api.py", sys.argv[1:])


def main_tile_click() -> None:
    _run("tile-click", sys.argv[1:])


def main_clean_fp_chrome() -> None:
    _run("clean-fp-chrome", sys.argv[1:])


def main_fp_audit() -> None:
    _run("fp-audit", sys.argv[1:])


COMMANDS = {
    "solve": main_turnstile_solve,
    "hcaptcha": main_hcaptcha_solve,
    "awswaf": main_awswaf_solve,
    "batch": main_batch_solve,
    "parallel": main_parallel_solve,
    "api": main_solver_api,
    "tile-click": main_tile_click,
    "browser": main_clean_fp_chrome,
    "audit": main_fp_audit,
}


def main() -> None:
    """python -m turnstile_waf_gates <command> [flags...]"""
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("usage: python -m turnstile_waf_gates <command> [flags...]\n")
        print("commands:")
        for name, fn in COMMANDS.items():
            print(f"  {name:12s} -> {fn.__name__}")
        print("\nflags are passed through to the underlying script (--help for each)")
        sys.exit(0)
    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"unknown command: {cmd} (see --help)", file=sys.stderr)
        sys.exit(5)
    # Dispatch: drop the command word, pass the rest to the script's argv
    sys.argv = [cmd] + args[1:]
    COMMANDS[cmd]()


if __name__ == "__main__":
    main()
