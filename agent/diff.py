"""Change source: produce (path, old_content, new_content) triples.

Two ways to obtain changes in Phase 1:

1. `changes_from_git`      — compare two revisions of a local git repo.
2. `changes_from_files`    — compare two explicit file versions (used by
                             the bundled fixtures so the agent runs with
                             zero setup).

A later phase adds `changes_from_github` (PyGithub) behind the same
`FileChange` interface, so nothing downstream needs to change.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileChange:
    """A single file that changed, with content before and after.

    `old_content` is None for an added file; `new_content` is None for a
    deleted file.
    """

    path: str
    old_content: str | None
    new_content: str | None

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")


def _git(repo_path: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _show(repo_path: str, rev: str, path: str) -> str | None:
    """Content of `path` at `rev`, or None if it did not exist there."""
    result = subprocess.run(
        ["git", "-C", repo_path, "show", f"{rev}:{path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def changes_from_git(
    repo_path: str, base: str = "HEAD~1", head: str = "HEAD"
) -> list[FileChange]:
    """Files changed between two revisions of a local git repo."""
    name_status = _git(
        repo_path, "diff", "--name-status", "--no-renames", base, head
    )
    changes: list[FileChange] = []
    for line in name_status.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        path = path.strip()
        old = None if status.startswith("A") else _show(repo_path, base, path)
        new = None if status.startswith("D") else _show(repo_path, head, path)
        changes.append(FileChange(path=path, old_content=old, new_content=new))
    return changes


def changes_from_files(
    before_path: str, after_path: str, logical_path: str | None = None
) -> list[FileChange]:
    """Compare two explicit file versions (fixture / demo mode)."""
    after = Path(after_path)
    old = Path(before_path).read_text() if Path(before_path).exists() else None
    new = after.read_text() if after.exists() else None
    return [
        FileChange(
            path=logical_path or after.name,
            old_content=old,
            new_content=new,
        )
    ]
