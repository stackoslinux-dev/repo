#!/usr/bin/env python3
"""Read-only, bounded failure triage. Produces reviewable evidence, never runs log text."""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com/repos/stackoslinux-dev/repo"
MAX_LOG_BYTES = 160_000
PATTERNS = [
    ("github_api_rate_limit", r"HTTP Error 403: rate limit exceeded|API rate limit exceeded", "Check authenticated API calls, token permissions and rate limits."),
    ("missing_dependency", r"Unable to locate package|ModuleNotFoundError|Depends:.*but it is not installable", "Review dependency closure and native C3 package manifests."),
    ("signature_failure", r"BAD signature|NO_PUBKEY|signature verification failed", "Block publication; inspect keyring, provenance and signed bytes."),
    ("disk_capacity", r"No space left on device", "Review runner disk usage and artifact size."),
    ("test_failure", r"AssertionError|FAILED|Process completed with exit code [1-9]", "Inspect failing step and reproduce in isolated test environment."),
]
SECRET = re.compile(r"(?i)(authorization:\s*(?:bearer|token)\s+)[^\s]+|\b(gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b")

def request(url, token, accept="application/vnd.github+json"):
    headers = {"User-Agent": "StackOS-C3-Triage/1", "Accept": accept}
    if token:
        headers["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        data = response.read(MAX_LOG_BYTES + 1)
        if len(data) > MAX_LOG_BYTES:
            raise ValueError("Response exceeds safety limit")
        return data

def classify(log):
    clean = SECRET.sub("[REDACTED]", log)
    return [
        {"category": name, "recommended_action": advice}
        for name, pattern, advice in PATTERNS if re.search(pattern, clean, re.I)
    ]

def triage():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN required")
    state_path = Path("cycle-out/agent-self-audit.json")
    state = json.loads(state_path.read_text())
    failures = state.get("recent_failures", [])[:3]
    results = []
    for run in failures:
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        jobs = json.loads(request(f"{API}/actions/runs/{run_id}/jobs?per_page=50", token))
        for job in jobs.get("jobs", []):
            if job.get("conclusion") != "failure":
                continue
            job_id = job.get("id")
            if not isinstance(job_id, int):
                continue
            try:
                log = request(f"{API}/actions/jobs/{job_id}/logs", token, "application/vnd.github+json").decode("utf-8", "replace")
                matches = classify(log)
                status = "CLASSIFIED" if matches else "UNCLASSIFIED"
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as exc:
                matches = []
                status = "LOG_UNAVAILABLE_" + type(exc).__name__
            results.append({"run_id": run_id, "job_id": job_id, "job_name": str(job.get("name", ""))[:120], "status": status, "findings": matches})
    return {"schema": 1, "mode": "read_only_diagnostic", "review_required": True, "automatic_code_changes": False, "production_publication": False, "results": results}

def main():
    try:
        report = triage()
    except (ValueError, OSError, urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        report = {"schema": 1, "status": "TRIAGE_FAILED", "error_type": type(exc).__name__, "review_required": True}
    target = Path("cycle-out/agent-triage.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 1 if report.get("status") == "TRIAGE_FAILED" else 0

if __name__ == "__main__":
    sys.exit(main())
