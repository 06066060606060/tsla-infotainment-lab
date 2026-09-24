# Native media environment

The native music card uses a dedicated ChromiumApp browser, the supplied media
web app, ChromiumAdapter and SpotifyServer. Ordinary Browser/Card rendering can
work while this separate path is unavailable.

The earlier project research identified two relevant components: the media
browser's secure-context declaration and compiled AppArmor policies. Both were
checked against the locally supplied MCU2 image, rather than assuming the older
research image has identical configuration.

The launcher now scopes the vendor secure-context declaration to
`http://firmware-media.vn.teslamotors.com:9000`, which is mapped to the lab's
loopback server. The supplied ChromiumApp policy file disables microphone and
camera capture. Ordinary browsing does not receive this origin declaration.
The native Chromium test confirmed that the declaration exposes the EME API.
Account login and actual DRM playback remain unverified.

The image contains nonempty policies in `etc/apparmor.compiled`. The tested WSL
kernel was built with AppArmor, initially disabled. After the authorized restart
with AppArmor selected, it reports `Y`; securityfs was mounted for validation.
Runtime Setup installs local compatibility profiles with the peer names used by
the firmware. The launcher attaches each local process to its matching profile,
so the center display accepts the native media connections.

Run the read-only inventory on a mounted image:

```bash
python3 scripts/check-media-environment.py /path/to/mounted/firmware
```

It reports prerequisite file sizes and kernel settings. It does not load policy,
alter profiles, change the host, access accounts or assert playback readiness.

The supplied policies were used to identify the exact peer names. Because the
firmware is mounted at a per-user read-only path instead of its vehicle root path,
Runtime Setup installs desktop compatibility profiles for QtCar, QtCarCluster,
SpotifyServer and ChromiumAdapter. A verified restart reports successful profile
matches for both media services and media health reaches `services-running`.
Linux documents `security=apparmor` for selecting it when it is not the default.
This is a prerequisite experiment, not a demonstrated Spotify fix. See the
[Linux AppArmor documentation](https://docs.kernel.org/admin-guide/LSM/apparmor.html).

Runtime Setup loads the profiles only when AppArmor already reports `Y`. If
AppArmor was enabled after Setup ran, `aa-exec` fails with `label not found`,
the processes start unconfined, and the center logs
`[PEERSEC] Incorrect security profile ... actual_profile=unconfined`. Run
Runtime Setup again, or load the installed file directly:

```bash
grep -q securityfs /etc/fstab || echo 'securityfs /sys/kernel/security securityfs defaults 0 0' | sudo tee -a /etc/fstab
sudo mount /sys/kernel/security 2>/dev/null
sudo apparmor_parser -r /etc/apparmor.d/tsla-infotainment-lab-media
sudo systemctl enable --now apparmor   # reload at every WSL start (needs systemd)
```

WSL does not mount securityfs at boot, and `apparmor.service` fails with
`Assertion failed` without it, so the profiles disappear after `wsl --shutdown`.
Runtime Setup adds the `fstab` line on WSL and enables the service. The session
log names every process that starts without its profile. An unconfined
`QtCarDvServer` or `QtCar` also keeps the Service Mode panel reloading: the page
never learns that Service Mode is on.

A successful start logs `Successful security profile match` for each service.

WSL kernel arguments are global settings in the Windows user's `.wslconfig`.
Changing them requires restarting WSL and affects every WSL 2 distribution.
Keep the previous configuration for rollback and obtain a suitable interruption
window before applying. See [Microsoft's WSL configuration documentation](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

