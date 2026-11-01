"""Frozen sidecar entry point: the API adapter only (no Qt, no dev tooling)."""

from rka_desktop.adapters.api.server import main

if __name__ == "__main__":
    raise SystemExit(main())
