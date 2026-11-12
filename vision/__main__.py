"""Allows `python -m vision ...`, which is what the LaunchAgent runs."""

from vision.core.cli import main

raise SystemExit(main())
