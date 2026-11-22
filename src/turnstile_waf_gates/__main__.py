"""python -m turnstile_waf_gates — dispatch to the script implementations.

The real implementations live in scripts/ as standalone executables. Both the
console entry points and this __main__ re-execute those files with the current
interpreter: exactly ONE implementation, no drift between scripts/ and the
installed package.
"""
from . import COMMANDS, main  # noqa: F401  (main re-exported for entry points)

if __name__ == "__main__":
    main()
