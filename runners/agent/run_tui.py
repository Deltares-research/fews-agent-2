"""Entrypoint: `python -m runners.agent.run_tui`.

Thin wrapper so the TUI can be launched without `pip install -e .`
(which registers the `fews-agent` console script).
"""
from fews_agent.chatter.tui import main

if __name__ == "__main__":
    raise SystemExit(main())
