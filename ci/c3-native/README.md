# Native C3 update lane in the existing hourly workflow

This extends `.github/workflows/c3-updates.yml`; it does not add another agent, local timer or publisher. The existing production signature verification and Pages jobs are preserved.

## First real application

The allowlisted application is StackOS BugReport 1.1.1 from the newest official Genesis app commit, with its version read from the real `DEBIAN/control`. The reviewed `tracking-policy.json` restricts paths, major version and unchanged maintainer scripts. Its update fixes credential exposure in HTTP URLs. The previous native build ran successfully in GitHub Actions (run42226744835); cloud signing now works with the persistent testing secret; the real Updater client must pass before activation.

The target Python3.13, glibc2.42, dpkg, APT, GTK and libraries are C3 bytes from the versioned cloud seed and pinned native baseline. Ubuntu is the hosted orchestration/display runner, not the target runtime. No `/run/media`, personal PC, SSD, Ollama or Codex session is used in periodic execution.

1. Detect compares the official version with **signed `validated.json`**, not an untested candidate. A failed Updater test never advances that version and is retried later.
2. Build compiles native Python bytecode, builds the real DEB twice, checks reproducibility, privacy behavior, installation/removal and incompatible-dependency refusal in C3.
3. Sign uses only `C3_TEST_SIGNING_KEY`, whose public fingerprint is488A5AF104A521116722A74CF6820043D52F5680. No production key is accepted.
4. Publish writes only `c3-testing`, retaining older package files. Native clients verify signed InRelease, archive hashes and the isolated key. The CI client uses the exact immutable published commit over HTTPS to avoid mutable-branch cache races.
5. The real StackOS Updater checks, offers and installs the update in the native C3 client. Its JSON results, log and offered-update screenshot are retained in Actions artifacts.
6. Only after that success, another isolated signing job signs the validated marker and publishes it atomically.

No-new-version runs skip native builds. Previously validated metadata is refreshed after24hours without recompiling the package; Release expires after7days. The same real Updater client checks the renewed publication.

## Components

`monitor_components.py` checks official kernel, Mesa, glibc, firmware, GLib, GTK, GNOME Shell, Mutter, LLVM, NetworkManager, PipeWire, ALSA and Python indexes. Unknown installed baselines are reported explicitly. Critical components are **monitoring only** until a native recipe, ABI group and boot/graphics/service tests have been qualified. Merely finding a higher upstream version never authorizes publishing it.

This is not full automatic kernel/Mesa/GNOME coverage. The initial native build allowlist remains BugReport; extend it with component-specific recipes and tests, not by disabling policy.

## Administration and activation

The configured credential is repository Actions secret `C3_TEST_SIGNING_KEY` containing the isolated testing private key. Never put that value in Git, logs or chat. Public `testing-keyring.gpg` and `testing-key.fpr` are intentional.

The cron remains `23 * * * *`. GitHub runs scheduled events from the default branch, so this PR must be merged only after the complete cloud cycle passes. GitHub scheduling can be delayed or skipped under load; run timestamps and detection artifacts are the evidence, not a strict hourly availability guarantee.

Testing APT URL: `https://raw.githubusercontent.com/stackoslinux-dev/repo/c3-testing/`. Normal StackOS clients keep the production URL `https://stackoslinux-dev.github.io/repo/c3/` until a separate qualified production promotion is authorized and signed with the official key. Do not silently add a testing key/channel to production ISOs.
