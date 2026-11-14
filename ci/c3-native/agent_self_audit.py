#!/usr/bin/env python3
"""Read-only StackOS C3 agent health audit. Never modifies source or publishes."""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "stackoslinux-dev/repo"
WORKFLOW = "c3-updates.yml"
URL = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=15"

def load_runs(fetch=None):
    if fetch is not None:
        return fetch()
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "StackOS-C3-Self-Audit/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=25) as response:
        return json.load(response)

def audit(payload):
    runs = payload.get("workflow_runs", [])
    completed = [run for run in runs if run.get("status") == "completed"]
    failures = [run for run in completed if run.get("conclusion") == "failure"]
    latest = completed[0] if completed else None
    return {
        "schema": 1,
        "checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repository": REPO,
        "workflow": WORKFLOW,
        "status": "NO_COMPLETED_RUNS" if not latest else ("FAILURE_NEEDS_REVIEW" if latest.get("conclusion") == "failure" else "LATEST_COMPLETED_" + str(latest.get("conclusion")).upper()),
        "latest_completed": None if not latest else {
            "id": latest.get("id"), "conclusion": latest.get("conclusion"), "url": latest.get("html_url"),
        },
        "recent_failures": [
            {"id": run.get("id"), "url": run.get("html_url"), "head_sha": run.get("head_sha")}
            for run in failures
        ],
        "action": "Investigate failed jobs and logs; propose reviewed PR, never edit production automatically" if failures else "No failed runs in retrieved window",
        "writes_performed": False,
    }

def main():
    try:
        report = audit(load_runs())
    except (urllib.error.URLError, ValueError, KeyError) as error:
        report = {"schema": 1, "status": "SOURCE_CHECK_FAILED", "error": str(error), "writes_performed": False}
    out = Path("cycle-out/agent-self-audit.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["status"] in ("SOURCE_CHECK_FAILED", "FAILURE_NEEDS_REVIEW", "NO_COMPLETED_RUNS") else 0

if __name__ == "__main__":
    sys.exit(main())
