from __future__ import annotations

from cyclesmith.hooks.install_hooks import main as install_hooks_main
from tests.utils import runtime_dir


def test_install_hooks_copies_templates() -> None:
    with runtime_dir("cyclesmith-hooks") as tmp_path:
        (tmp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".githooks").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".githooks" / "pre-commit").write_text(
            "#!/usr/bin/env bash\necho pre\n", encoding="utf-8"
        )
        (tmp_path / ".githooks" / "commit-msg").write_text(
            "#!/usr/bin/env bash\necho msg\n", encoding="utf-8"
        )

        result = install_hooks_main(["--repo-root", str(tmp_path)])
        assert result == 0
        assert (tmp_path / ".git" / "hooks" / "pre-commit").exists()
        assert (tmp_path / ".git" / "hooks" / "commit-msg").exists()


def test_install_hooks_fails_without_git_directory() -> None:
    with runtime_dir("cyclesmith-hooks") as tmp_path:
        (tmp_path / ".githooks").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".githooks" / "pre-commit").write_text("pre\n", encoding="utf-8")
        (tmp_path / ".githooks" / "commit-msg").write_text("msg\n", encoding="utf-8")

        try:
            install_hooks_main(["--repo-root", str(tmp_path)])
        except ValueError as exc:
            assert ".git" in str(exc)
        else:
            raise AssertionError("Expected ValueError when .git directory is missing.")
