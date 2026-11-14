# StackOS C3 — Agent self-audit (fase 1)

This workflow checks the real status of recent C3 GitHub Actions runs every six hours and on manual dispatch. It produces a JSON report and fails its own job if the latest completed C3 run failed or the source could not be checked.

It has read-only GitHub permissions. It **does not** generate code changes, fix failures with an LLM, build an ISO, sign packages, or publish to production. The C3 testing pipeline remains separate. A future autonomous repair phase must use an isolated branch and reviewable pull requests, with narrowly scoped permissions, reproducible tests, and explicit approval for production.

The audit reads only GitHub's authenticated Actions API, does not require a notebook, and never treats a missing response as a clean run.

## Phase 2: bounded failure triage

The separate `agent_triage.py` reads up to three recent failed runs and classifies failed job logs into known categories (rate limits, dependencies, signatures, disk capacity, and test failures). It never executes log text or writes patches. It produces `cycle-out/agent-triage.json`, containing job IDs and diagnostic categories rather than raw logs. The workflow also runs classification unit tests.

This is not yet a model-driven code-writing agent. Adding autonomous patch proposals requires a configured model, explicit allowlisted write scopes, isolation, tests, and PR-only permissions. Never give an untrusted model a production publishing token.
