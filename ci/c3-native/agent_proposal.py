#!/usr/bin/env python3
"""Validate AI-generated candidate edits as DATA. Never apply or execute them."""
import json
import re
from pathlib import PurePosixPath

ALLOWLIST = frozenset({
    "ci/c3-native/agent_self_audit.py",
    "ci/c3-native/agent_triage.py",
    "ci/c3-native/agent_ai_advice.py",
    "ci/c3-native/test_agent_triage.py",
    "ci/c3-native/test_agent_self_audit.py",
})
MAX_CONTENT = 20000

def validate_proposal(payload):
    if not isinstance(payload, dict) or set(payload) != {"path", "content", "reason"}:
        raise ValueError("Expected path, content, reason")
    path, content, reason = (payload[k] for k in ("path", "content", "reason"))
    if not isinstance(path, str) or path not in ALLOWLIST:
        raise ValueError("Path not explicitly allowlisted")
    if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        raise ValueError("Unsafe path")
    if not isinstance(content, str) or not (0 < len(content) <= MAX_CONTENT):
        raise ValueError("Invalid content length")
    if not isinstance(reason, str) or not (0 < len(reason) <= 500):
        raise ValueError("Invalid reason")
    if re.search(r"(?i)gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,}", content):
        raise ValueError("Potential credential in content")
    return {"path": path, "content": content, "reason": reason, "status": "UNTRUSTED_REVIEW_ONLY"}

def main():
    import sys
    from pathlib import Path
    if len(sys.argv) != 2:
        print("usage: agent_proposal.py candidate.json")
        return 2
    try:
        payload = json.loads(Path(sys.argv[1]).read_text())
        result = validate_proposal(payload)
        Path("cycle-out").mkdir(exist_ok=True)
        # Do not write executable candidate content into the repository.
        Path("cycle-out/agent-proposal-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print("Proposal staged for manual review; no files changed")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print("Rejected proposal:", type(error).__name__)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
