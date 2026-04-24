from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "setup-jue.sh"


def test_setup_jue_script_is_valid_shell():
    result = subprocess.run(["bash", "-n", str(SETUP_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_setup_jue_script_has_termux_path():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "is_termux()" in content
    assert ".[termux]" in content
    assert "constraints-termux.txt" in content
    assert "$PREFIX/bin" in content
    assert "Skipping tinker-atropos on Termux" in content


def test_setup_jue_script_enables_tui_by_default():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "export JUE_TUI=1" in content
    assert "jue --no-tui" in content
    assert "$HOME/.zshrc" in content
    assert "$HOME/.bashrc" in content
