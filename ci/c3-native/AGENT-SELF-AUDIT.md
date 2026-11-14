# StackOS C3 — Agent self-audit (fase 1)

This workflow checks the real status of recent C3 GitHub Actions runs every six hours and on manual dispatch. It produces a JSON report and fails its own job if the latest completed C3 run failed or the source could not be checked.

It has read-only GitHub permissions. It **does not** generate code changes, fix failures with an LLM, build an ISO, sign packages, or publish to production. The C3 testing pipeline remains separate. A future autonomous repair phase must use an isolated branch and reviewable pull requests, with narrowly scoped permissions, reproducible tests, and explicit approval for production.

The audit reads only GitHub's authenticated Actions API, does not require a notebook, and never treats a missing response as a clean run.
