#!/usr/bin/env python3
"""Read-only gate: never claim an ISO build is possible without its native inputs."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

root = Path(os.environ.get("STACKOS_BUILD_ROOT", "")).expanduser()
required = [
    "release-root/etc/os-release",
    "package-candidate.py",
    "sign-repo.py",
    "seal.py",
]
issues = []
if not os.environ.get("STACKOS_BUILD_ROOT"):
    issues.append("STACKOS_BUILD_ROOT is not provisioned in this runner")
else:
    if not root.is_dir():
        issues.append("C3 build root is missing")
    else:
        for name in required:
            if not (root / name).is_file():
                issues.append("Missing required build input: " + name)
        os_release = root / required[0]
        if os_release.is_file() and "StackOS C3" not in os_release.read_text(errors="replace"):
            issues.append("Build root is not identified as StackOS C3")
# ISO construction needs an independently reviewed bootable-image recipe and test harness.
# These are not supplied by the current public CI checkout.
if not os.environ.get("STACKOS_ISO_RECIPE"):
    issues.append("No reviewed ISO assembly recipe configured")
elif not Path(os.environ["STACKOS_ISO_RECIPE"]).is_file():
    issues.append("Configured ISO assembly recipe is missing")
if not os.environ.get("STACKOS_QEMU_TEST"):
    issues.append("No reviewed QEMU ISO boot test configured")
elif not Path(os.environ["STACKOS_QEMU_TEST"]).is_file():
    issues.append("Configured QEMU ISO boot test is missing")
report = {
    "checked_utc": datetime.now(timezone.utc).isoformat(),
    "status": "BLOCKED_MISSING_NATIVE_INPUTS" if issues else "INPUTS_PRESENT_NOT_YET_BUILT_OR_TESTED",
    "candidate_iso_built": False,
    "production_published": False,
    "issues": issues,
    "next_step": "Provision pinned native build inputs and reviewed ISO/QEMU recipes; run isolated build and tests before any release.",
}
out = Path("cycle-out")
out.mkdir(exist_ok=True)
(out / "iso-build-readiness.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
