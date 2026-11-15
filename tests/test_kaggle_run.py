import base64
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "kaggle_run.py"
_spec = importlib.util.spec_from_file_location("kaggle_run", _PATH)
kaggle_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kaggle_run)

SHA = "0123456789abcdef0123456789abcdef01234567"
OWNER = "someone"


def test_kernel_embeds_the_archive_commit_and_command():
    archive = bytes(range(256)) * 3
    script, metadata = kaggle_run.build_kernel(archive, SHA, ["pytest", "-q"], "ow-suite", owner=OWNER)
    namespace = {"__name__": "not_main"}
    exec(compile(script, "kernel.py", "exec"), namespace)
    assert namespace["COMMIT"] == SHA
    assert namespace["COMMAND"] == ["pytest", "-q"]
    assert base64.b64decode(namespace["ARCHIVE_B64"]) == archive
    assert metadata["id"] == "someone/ow-suite"
    assert metadata["code_file"] == "ow-suite.py"
    assert metadata["kernel_type"] == "script"
    assert metadata["is_private"] is True
    assert metadata["enable_gpu"] is False and metadata["enable_tpu"] is False
    assert metadata["enable_internet"] is True


@pytest.mark.parametrize(
    "sha, command, slug",
    [
        (SHA, ["pytest"], "Bad Slug"),
        (SHA, ["pytest"], "ow"),
        ("abc123", ["pytest"], "ow-suite"),
        (SHA, [], "ow-suite"),
        (SHA, ["python", "job.py", "--out", "C:/Program Files/Git/kaggle/working/out"], "ow-suite"),
    ],
)
def test_bad_inputs_are_rejected(sha, command, slug):
    with pytest.raises(ValueError):
        kaggle_run.build_kernel(b"x", sha, command, slug, owner=OWNER)


def test_attached_files_are_written_with_their_sha256(tmp_path):

    data = b"1 25544U ...\n"
    script, _ = kaggle_run.build_kernel(
        b"x", SHA, ["pytest"], "ow-suite", {"data/archive/25544.tle": data}, owner=OWNER)
    ns = {"__name__": "not_main"}
    exec(compile(script, "kernel.py", "exec"), ns)
    assert {k: base64.b64decode(v) for k, v in ns["ATTACH_B64"].items()} == {"data/archive/25544.tle": data}
    assert "hashlib.sha256(data).hexdigest()" in script


@pytest.mark.parametrize("rel", ["../secret", "/etc/passwd", "C:/x", "a//b", "a\\b"])
def test_attach_paths_must_stay_inside_the_repo(rel):
    with pytest.raises(ValueError):
        kaggle_run.build_kernel(b"x", SHA, ["pytest"], "ow-suite", {rel: b"x"}, owner=OWNER)


def test_datasets_are_mounted_and_checked():
    ref = "vaibhavpandey12382/historical-tle-datasets"
    _, metadata = kaggle_run.build_kernel(b"x", SHA, ["pytest"], "ow-suite", datasets=[ref], owner=OWNER)
    assert metadata["dataset_sources"] == [ref]
    with pytest.raises(ValueError):
        kaggle_run.build_kernel(b"x", SHA, ["pytest"], "ow-suite", datasets=["no-slash"], owner=OWNER)


def test_bad_owner_is_rejected():
    with pytest.raises(ValueError):
        kaggle_run.build_kernel(b"x", SHA, ["pytest"], "ow-suite", owner="a/b")


def test_username_comes_from_the_environment_first(tmp_path, monkeypatch):
    (tmp_path / "kaggle.json").write_text('{"username": "from-config", "key": "x"}', encoding="utf-8")
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KAGGLE_USERNAME", "from-env")
    assert kaggle_run.kaggle_username() == "from-env"


def test_username_falls_back_to_the_cli_config(tmp_path, monkeypatch):
    (tmp_path / "kaggle.json").write_text('{"username": "from-config", "key": "x"}', encoding="utf-8")
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    assert kaggle_run.kaggle_username() == "from-config"


def test_no_username_exits_naming_what_to_set(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    with pytest.raises(SystemExit) as exc:
        kaggle_run.kaggle_username()
    assert "KAGGLE_USERNAME" in str(exc.value) and "kaggle.json" in str(exc.value)
