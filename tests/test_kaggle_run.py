import base64
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "kaggle_run.py"
_spec = importlib.util.spec_from_file_location("kaggle_run", _PATH)
kaggle_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kaggle_run)

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_kernel_embeds_the_archive_commit_and_command():
    archive = bytes(range(256)) * 3
    script, metadata = kaggle_run.build_kernel(archive, SHA, ["pytest", "-q"], "ow-suite")
    namespace = {"__name__": "not_main"}
    exec(compile(script, "kernel.py", "exec"), namespace)  # defines, does not run
    assert namespace["COMMIT"] == SHA
    assert namespace["COMMAND"] == ["pytest", "-q"]
    assert base64.b64decode(namespace["ARCHIVE_B64"]) == archive
    assert metadata["id"].endswith("/ow-suite")
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
    ],
)
def test_bad_inputs_are_rejected(sha, command, slug):
    with pytest.raises(ValueError):
        kaggle_run.build_kernel(b"x", sha, command, slug)
