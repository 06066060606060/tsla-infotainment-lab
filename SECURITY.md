# Security boundaries

Infotainment Lab is a local compatibility workbench. It runs user-supplied firmware applications with the desktop user's permissions. **A read-only firmware mount is not a sandbox.** Vendor processes can use the user's network and accessible files. Use a dedicated Linux account or disposable WSL distribution for research images.

The launcher uses argument arrays rather than shell interpolation, validates library identifiers, checks image metadata and executable build IDs, mounts through unprivileged read-only FUSE, and owns its processes through one systemd user service. Dependency setup is the only privileged operation. The two display processes share a private D-Bus session. X11 TCP listeners are disabled. Simulator telemetry is limited to named local display values; no physical vehicle transport or remote command endpoint is provided.

SHA-256 identifies the imported file; it does not authenticate its publisher. Build IDs select a compatibility profile, not a trust decision. The initial release records size and modification time to detect ordinary changes after import; it does not rehash a multi-gigabyte image at every launch. Do not replace or modify an imported image while it is in use.

Network access is intentional. The connectivity indicator checks Google's HTTP 204 endpoint over HTTPS. Chromium accesses sites selected by the user, and firmware may attempt its usual background connections (for example Google map tiles). Lookups of Tesla's domains (`tesla.com`, `teslamotors.com`, `tesla.services`, `tesla.cn`) fail for every firmware process and browser the lab starts; connections to literal IP addresses are not intercepted. The app does not collect analytics or upload diagnostics. Exported reports use an allowlist; raw logs and browser profiles stay local. Review any screenshot or report before sharing it.

The runtime does not patch authentication decisions or bypass vehicle service authorization. A service that requires unavailable platform identity remains unsupported. This repository is not a full ECU emulator, vehicle control tool, or claim of a security vulnerability.

Please report launcher security defects privately using the repository's security advisory feature if the owner enables it. Otherwise contact the maintainer through their published GitHub profile before posting sensitive details. Do not include firmware, secrets, personal data, or an exploit targeting a third-party system in public issues.
