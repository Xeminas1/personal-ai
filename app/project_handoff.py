"""Explicit read-only PUBLIC XemAi repository handoff status.

Owner-requested user command only. This is not a code-executing agent.
No private GitHub token, instructions, comments or chat data are transmitted.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from .version import VERSION

_REPO_PAGE = "https://github.com/Xeminas1/personal-ai"
_VERSION = "https://raw.githubusercontent.com/Xeminas1/personal-ai/main/app/version.py"
_OPEN_WORK = "https://api.github.com/repos/Xeminas1/personal-ai/issues?state=open&per_page=20"
_COMMIT = "https://api.github.com/repos/Xeminas1/personal-ai/commits/main"
_MAX_BYTES = 80_000


def is_command(message: str) -> bool:
    """Only the owner's unambiguous explicit handoff/resume request."""
    if not isinstance(message, str):
        return False
    normalized = " ".join(message.lower().split()).strip(" .!?")
    return normalized in {
        "resume xemai from github",
        "resume xemai development from github",
        "xemai project status from github",
    }


def _read(url: str, *, opener=None) -> str:
    """Read only developer-owned, fixed HTTPS public repository URLs."""
    if url not in {_VERSION, _OPEN_WORK, _COMMIT}:
        raise ValueError("Unsupported repository status endpoint")
    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "XemAi-Public-Project-Status",
                 "Accept": "application/vnd.github+json"},
    )
    with open_url(request, timeout=8) as response:
        payload = response.read(_MAX_BYTES + 1)
    if len(payload) > _MAX_BYTES:
        raise ValueError("Public GitHub status response is too large")
    return payload.decode("utf-8")


def project_status(*, opener=None) -> str:
    """Report live public status; never treat GitHub data as instructions."""
    lines = ["I understand — you're asking me to pick up XemAi's GitHub development status."]
    try:
        text = _read(_VERSION, opener=opener)
        match = re.fullmatch(r'VERSION = "([0-9]+(?:\.[0-9]+){2})"\s*', text)
        if not match:
            raise ValueError("Unrecognised public release file")
        released = match.group(1)
        lines.append(
            f"GitHub source currently reports XemAi v{released}; "
            f"this running application is v{VERSION}."
        )
    except (OSError, ValueError, UnicodeError, urllib.error.URLError):
        lines.append("I couldn't verify the current public GitHub release right now.")

    try:
        rows = json.loads(_read(_OPEN_WORK, opener=opener))
        if not isinstance(rows, list):
            raise ValueError("Unexpected public issue list")
        numbers = [r["number"] for r in rows if isinstance(r, dict)
                   and type(r.get("number")) is int and 1 <= r["number"] <= 1_000_000]
        if len(rows) >= 20:
            lines.append("GitHub has at least 20 open issue/PR records; see the live listing.")
        else:
            issues = [str(r["number"]) for r in rows if isinstance(r, dict)
                      and type(r.get("number")) is int
                      and "pull_request" not in r]
            prs = [str(r["number"]) for r in rows if isinstance(r, dict)
                   and type(r.get("number")) is int
                   and "pull_request" in r]
            lines.append(
                "Open development issues: " + (", ".join("#" + n for n in issues[:8])
                                                if issues else "none") + ". "
                "Open pull requests: " + (", ".join("#" + n for n in prs[:8])
                                          if prs else "none") + "."
            )
    except (OSError, ValueError, UnicodeError, urllib.error.URLError):
        lines.append("I couldn't verify open issues or pull requests.")

    try:
        meta = json.loads(_read(_COMMIT, opener=opener))
        sha = meta.get("sha") if isinstance(meta, dict) else None
        if isinstance(sha, str) and re.fullmatch("[0-9a-f]{40}", sha):
            lines.append(f"Latest public main commit: {sha[:12]}.")
    except (OSError, ValueError, UnicodeError, urllib.error.URLError):
        pass

    lines.append(
        f"Review project handoff files at {_REPO_PAGE}/blob/main/AGENTS.md "
        f"and current tasks at {_REPO_PAGE}/issues. "
        "I can report public project status, but I can't take over ChatGPT/Codex "
        "coding sessions or edit my own code from this command. "
        "For coding handoff, use the same request in a GitHub-connected ChatGPT or Codex session."
    )
    return "\n\n".join(lines)
