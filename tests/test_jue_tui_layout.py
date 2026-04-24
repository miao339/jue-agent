from pathlib import Path


def test_tui_local_ink_package_matches_jue_dependency_path():
    root = Path(__file__).resolve().parents[1]

    assert (root / "ui-tui" / "packages" / "jue-ink" / "package.json").is_file()
    assert not (root / "ui-tui" / "packages" / "hermes-ink" / "package.json").exists()


def test_tui_default_banner_logo_is_jue_agent_not_hermes_agent():
    banner_ts = (Path(__file__).resolve().parents[1] / "ui-tui" / "src" / "banner.ts").read_text(
        encoding="utf-8"
    )

    assert "JUE-AGENT" in banner_ts
    assert "HERMES" not in banner_ts


def test_tui_default_branding_does_not_show_legacy_caduceus_or_symbol():
    root = Path(__file__).resolve().parents[1]
    checked_files = [
        root / "ui-tui" / "src" / "banner.ts",
        root / "ui-tui" / "src" / "bootBanner.ts",
        root / "ui-tui" / "src" / "theme.ts",
        root / "ui-tui" / "src" / "components" / "branding.tsx",
        root / "ui-tui" / "src" / "components" / "appLayout.tsx",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_files)

    assert "CADUCEUS_ART" not in combined
    assert "⚕" not in combined
    assert "HERMES" not in combined


def test_repo_ignores_local_jue_runtime_directory():
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")

    assert ".jue/" in {line.strip() for line in gitignore.splitlines()}
