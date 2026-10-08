"""A bounded, read-only GitHub API adapter using existing gh authentication."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class GitHubError(RuntimeError):
    """GitHub could not return usable evidence."""


class NotFound(GitHubError):
    """The requested resource was not accessible (HTTP 404)."""


class GitHub:
    def __init__(self, timeout: float = 30) -> None:
        self.executable = shutil.which("gh")
        if self.executable is None:
            raise GitHubError("Install GitHub CLI (gh), then run gh auth login.")
        self.timeout = timeout

    def get(self, endpoint: str) -> Any:
        """GET one JSON response, with a deadline and no shell invocation."""
        if not endpoint.startswith(("repos/", "search/", "user")):
            raise GitHubError("Unsupported GitHub API endpoint.")
        try:
            process = subprocess.run(
                [self.executable, "api", "--hostname", "github.com", "--method", "GET", endpoint],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError("GitHub request failed or exceeded its deadline.") from exc
        if process.returncode:
            if "HTTP 404" in process.stderr:
                raise NotFound("Resource not found or inaccessible.")
            if "HTTP 403" in process.stderr or "rate limit" in process.stderr.lower():
                raise GitHubError("GitHub denied the request; check access and API rate limits.")
            raise GitHubError("GitHub request failed; check gh auth status and your connection.")
        try:
            return json.loads(process.stdout)
        except (ValueError, UnicodeError) as exc:
            raise GitHubError("GitHub returned an invalid JSON response.") from exc
