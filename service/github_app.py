"""GitHub App authentication.

A GitHub App authenticates in two steps:

1. Sign a short-lived JWT with the App's private key (proves "I am this
   App").
2. Exchange it for an *installation access token* scoped to one
   installation (proves "acting on behalf of this install on these
   repos").

PyGithub's `GithubIntegration` handles both. This module wraps it so the
rest of the service just asks for an authenticated `repo` object.
"""

from __future__ import annotations

import time
from functools import lru_cache


class GitHubAppError(RuntimeError):
    pass


def _integration(app_id: str, private_key: str):
    from github import GithubIntegration, Auth

    auth = Auth.AppAuth(int(app_id), private_key)
    return GithubIntegration(auth=auth)


def installation_token(app_id: str, private_key: str, installation_id: int) -> str:
    """Mint a fresh installation access token (valid ~1 hour)."""
    integ = _integration(app_id, private_key)
    try:
        return integ.get_access_token(installation_id).token
    except Exception as e:  # pragma: no cover - network dependent
        raise GitHubAppError(f"could not mint installation token: {e}") from e


def client_for_installation(app_id: str, private_key: str, installation_id: int):
    """Return a PyGithub `Github` client authenticated for one installation."""
    from github import Github, Auth

    token = installation_token(app_id, private_key, installation_id)
    return Github(auth=Auth.Token(token)), token


def repo_for_installation(
    app_id: str, private_key: str, installation_id: int, full_name: str
):
    """Return (authenticated repo, token) for `owner/name`."""
    gh, token = client_for_installation(app_id, private_key, installation_id)
    return gh.get_repo(full_name), token
