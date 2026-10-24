"""Z2.1: a worktree finds the lake, pilot, and benchmark."""
from cryptobot.research.data_root import resolve_data_roots


def test_local_files_win_and_missing_pilot_uses_external(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYPTOBOT_DATA_ROOT", raising=False)
    monkeypatch.delenv("CRYPTOBOT_LAKE", raising=False)
    monkeypatch.delenv("CRYPTOBOT_PILOT", raising=False)
    monkeypatch.delenv("CRYPTOBOT_BENCHMARK", raising=False)
    monkeypatch.delenv("CRYPTOBOT_DATA_CONFIG", raising=False)
    monkeypatch.delenv("CRYPTOBOT_EXTERNAL_ROOT", raising=False)
    repo = tmp_path / "repo"
    (repo / "data" / "lake").mkdir(parents=True)
    (repo / "datasets").mkdir()
    (repo / "datasets" / "benchmark_30d.toml").write_text("name='x'\n")
    external = tmp_path / "external"
    (external / "data" / "pilot").mkdir(parents=True)
    roots = resolve_data_roots(repo)
    assert roots.lake == repo / "data" / "lake"
    assert roots.lake_source == "local"
    assert roots.benchmark == repo / "datasets" / "benchmark_30d.toml"
    assert roots.pilot_source == "missing"
    monkeypatch.setenv("CRYPTOBOT_EXTERNAL_ROOT", str(external))
    roots = resolve_data_roots(repo)
    assert roots.pilot == external / "data" / "pilot"
    assert roots.pilot_source == "external"


def test_env_override_beats_a_present_local_path(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYPTOBOT_EXTERNAL_ROOT", raising=False)
    monkeypatch.delenv("CRYPTOBOT_DATA_CONFIG", raising=False)
    repo = tmp_path / "repo"
    (repo / "data" / "lake").mkdir(parents=True)
    other = tmp_path / "other-lake"
    other.mkdir()
    monkeypatch.setenv("CRYPTOBOT_LAKE", str(other))
    roots = resolve_data_roots(repo)
    assert roots.lake == other
    assert roots.lake_source == "env:CRYPTOBOT_LAKE"


def test_config_file_sets_the_base(tmp_path, monkeypatch):
    for key in ("CRYPTOBOT_DATA_ROOT", "CRYPTOBOT_LAKE", "CRYPTOBOT_PILOT",
                "CRYPTOBOT_BENCHMARK", "CRYPTOBOT_EXTERNAL_ROOT"):
        monkeypatch.delenv(key, raising=False)
    repo = tmp_path / "repo"
    base = tmp_path / "base"
    (base / "data" / "lake").mkdir(parents=True)
    (base / "data" / "pilot").mkdir()
    (base / "datasets").mkdir()
    (base / "datasets" / "benchmark_30d.toml").write_text("ok\n")
    cfg = repo / "research"
    cfg.mkdir(parents=True)
    (cfg / "data_root.toml").write_text(f'root = "{base}"\n')
    monkeypatch.delenv("CRYPTOBOT_DATA_CONFIG", raising=False)
    roots = resolve_data_roots(repo)
    assert roots.lake == base / "data" / "lake"
    assert roots.pilot_source == "local"
    assert roots.benchmark.name == "benchmark_30d.toml"
