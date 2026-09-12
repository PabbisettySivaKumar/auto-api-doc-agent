"""Unit test for pr.commit_to_branch: single commit per run + idempotency.

Uses a fake PyGithub-like repo so no network/GitHub is needed."""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import pr  # noqa: E402
from agent.draft import DocEdit  # noqa: E402


# --- Fakes mimicking the small slice of PyGithub that commit_to_branch uses ---
class _Content:
    def __init__(self, text: str):
        self.decoded_content = text.encode()


class _Obj:
    def __init__(self, sha):
        self.sha = sha


class _Ref:
    def __init__(self, sha):
        self.object = _Obj(sha)
        self.edited_to = None

    def edit(self, sha):
        self.edited_to = sha


class _Commit:
    def __init__(self, sha):
        self.sha = sha
        self.tree = _Obj(f"tree-of-{sha}")


class FakeRepo:
    def __init__(self, existing: dict[str, str]):
        self.existing = existing
        self.ref = _Ref("base-sha")
        self.trees_created = 0
        self.commits_created = 0
        self.last_tree_paths: list[str] = []

    def get_contents(self, path, ref=None):
        if path in self.existing:
            return _Content(self.existing[path])
        raise Exception("404")

    def get_git_ref(self, name):
        return self.ref

    def get_git_commit(self, sha):
        return _Commit(sha)

    def create_git_tree(self, elements, base_tree):
        self.trees_created += 1
        self.last_tree_paths = [e._identity["path"] if hasattr(e, "_identity") else e.path for e in elements]
        return _Obj("new-tree")

    def create_git_commit(self, message, tree, parents):
        self.commits_created += 1
        self.last_message = message
        return _Commit("new-commit-sha")


# Patch InputGitTreeElement so we don't need the real github package.
import agent.pr as prmod  # noqa: E402


def _install_fake_github():
    fake = types.ModuleType("github")

    class InputGitTreeElement:
        def __init__(self, path, mode, type, content):
            self.path = path
            self.mode = mode
            self.type = type
            self.content = content

    fake.InputGitTreeElement = InputGitTreeElement
    sys.modules["github"] = fake


def test_single_commit_for_multiple_files() -> None:
    _install_fake_github()
    repo = FakeRepo(existing={"docs/API.md": "old index"})
    edits = [
        DocEdit("docs/features/app.md", "markdown", "new feature doc", "r"),
        DocEdit("docs/API.md", "markdown", "new index", "r"),
    ]
    sha = pr.commit_to_branch(repo, "feature-x", edits, "docs: update")
    assert sha == "new-commit-sha"
    assert repo.commits_created == 1, "must be exactly ONE commit for all files"
    assert set(repo.last_tree_paths) == {"docs/features/app.md", "docs/API.md"}
    assert pr.SKIP_MARKER in repo.last_message
    assert repo.ref.edited_to == "new-commit-sha"
    print("PASS test_single_commit_for_multiple_files ->", repo.last_tree_paths)


def test_idempotent_noop_when_unchanged() -> None:
    _install_fake_github()
    repo = FakeRepo(existing={
        "docs/API.md": "same",
        "docs/features/app.md": "same2",
    })
    edits = [
        DocEdit("docs/API.md", "markdown", "same", "r"),
        DocEdit("docs/features/app.md", "markdown", "same2", "r"),
    ]
    sha = pr.commit_to_branch(repo, "feature-x", edits, "docs: update")
    assert sha is None, "no change -> no commit"
    assert repo.commits_created == 0
    print("PASS test_idempotent_noop_when_unchanged")


def test_only_changed_files_in_tree() -> None:
    _install_fake_github()
    repo = FakeRepo(existing={
        "docs/API.md": "same",
        "docs/features/app.md": "OLD",
    })
    edits = [
        DocEdit("docs/API.md", "markdown", "same", "r"),          # unchanged
        DocEdit("docs/features/app.md", "markdown", "NEW", "r"),  # changed
    ]
    sha = pr.commit_to_branch(repo, "feature-x", edits, "docs: update")
    assert sha == "new-commit-sha"
    assert repo.commits_created == 1
    assert repo.last_tree_paths == ["docs/features/app.md"], repo.last_tree_paths
    print("PASS test_only_changed_files_in_tree")


if __name__ == "__main__":
    test_single_commit_for_multiple_files()
    test_idempotent_noop_when_unchanged()
    test_only_changed_files_in_tree()
    print("\nAll commit_to_branch tests passed.")
