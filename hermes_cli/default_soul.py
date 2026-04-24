"""Default SOUL.md content seeded into JUE_HOME on first run."""

from pathlib import Path


def _load_default_soul() -> str:
    soul_path = Path(__file__).resolve().parents[1] / "jue" / "harness2" / "SOUL.md"
    try:
        return soul_path.read_text(encoding="utf-8")
    except OSError:
        return "# SOUL.md\n\nJue Agent default SOUL.md was not found in the package.\n"


DEFAULT_SOUL_MD = _load_default_soul()
