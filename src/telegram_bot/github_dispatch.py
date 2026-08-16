"""
Triggers the repo's GitHub Actions workflow from the Telegram bot side.
Configuration via env vars:
- GITHUB_TOKEN: a PAT or fine-grained token with `actions: write` on the
  target repo (kept in the bot's own hosting environment — NOT the same
  as the GITHUB_TOKEN GitHub Actions injects automatically into a
  workflow run, which cannot trigger other workflows by default).
- GITHUB_REPOSITORY: "owner/repo".
- GITHUB_WORKFLOW_FILE: filename of the workflow to dispatch, defaults to
  "run_agent.yml".
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)


class GitHubDispatchError(Exception):
    pass


class GitHubDispatcher:
    def __init__(self, timeout_seconds: int = 15):
        self.timeout_seconds = timeout_seconds
        self._token = os.environ.get("GITHUB_TOKEN", "").strip()
        self._repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        self._workflow_file = os.environ.get("GITHUB_WORKFLOW_FILE", "run_agent.yml").strip()

    def is_configured(self) -> bool:
        return bool(self._token and self._repo)

    def dispatch(self, mode: str, product_id: str = "", run_id: str = "", ref: str = "main") -> None:
        if not self.is_configured():
            raise GitHubDispatchError("GitHubDispatcher is not configured (missing GITHUB_TOKEN/GITHUB_REPOSITORY)")

        url = f"https://api.github.com/repos/{self._repo}/actions/workflows/{self._workflow_file}/dispatches"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
        }
        payload = {
            "ref": ref,
            "inputs": {"mode": mode, "product_id": product_id, "run_id": run_id},
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.warning("GitHub workflow_dispatch failed: %s", type(e).__name__)
            raise GitHubDispatchError(f"Failed to dispatch workflow: {type(e).__name__}") from e
