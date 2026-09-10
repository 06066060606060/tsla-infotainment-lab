# Contributing

Start with a small, reproducible issue: the supported image version and variant, host platform, exported diagnostics, and steps that show the behavior. Raw firmware logs can contain personal information; inspect them before sharing. Never submit firmware, maps, credentials, browser profiles, private research artifacts, or another person's data.

Use Python 3.11+ and the pinned development dependencies in `pyproject.toml`. Run `python -m pytest -q` and build on the target OS for packaging changes. Tests in CI must not require proprietary files, GPU access, root, or a running car interface.

New compatibility profiles need exact version/variant identification, executable build IDs, a clear explanation of the adaptation, and a validation record covering startup, shutdown, input, graphics and browser behavior. Filename conventions and a process staying alive are not sufficient evidence of support. Keep incomplete features visibly marked.

Keep user-facing English and Mandarin text together, write readable error messages with an actionable next step, and use structured subprocess arguments. Changes to privileged setup, filesystem ownership, exported diagnostics, or process cleanup need focused tests and a description of their boundaries.
