import os
from pathlib import Path
from unittest.mock import patch


def test_harness3_default_paths_follow_jue_home(tmp_path, monkeypatch):
    jue_home = tmp_path / "jue-home"
    fake_os_home = tmp_path / "os-home"
    fake_os_home.mkdir()

    monkeypatch.setenv("JUE_HOME", str(jue_home))

    with patch("jue.harness3.store.Path.home", return_value=fake_os_home):
        from jue.harness3.store import HarnessStore, TripletStore

        triplets = TripletStore()
        harnesses = HarnessStore()

    assert triplets.store_dir == jue_home / "harness3"
    assert harnesses.store_dir == jue_home / "harness3"
    assert not (fake_os_home / ".jue").exists()


def test_harness3_config_path_follows_jue_home(tmp_path, monkeypatch):
    jue_home = tmp_path / "jue-home"
    fake_os_home = tmp_path / "os-home"
    fake_os_home.mkdir()

    monkeypatch.setenv("JUE_HOME", str(jue_home))

    with patch("jue.harness3.harness_config.Path.home", return_value=fake_os_home):
        from jue.harness3 import harness_config

        harness_config.save_config({"global": {"provider": "local"}, "configs": {}})

    assert (jue_home / "harness3" / "config.json").is_file()
    assert not (fake_os_home / ".jue").exists()
