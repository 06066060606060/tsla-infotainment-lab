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

WSL kernel arguments are global settings in the Windows user's `.wslconfig`.
Changing them requires restarting WSL and affects every WSL 2 distribution.
Keep the previous configuration for rollback and obtain a suitable interruption
window before applying. See [Microsoft's WSL configuration documentation](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

## 中文记录

原生音乐卡片使用独立的 ChromiumApp、媒体网页、ChromiumAdapter 和 SpotifyServer。
已根据旧项目研究，在当前 MCU2 固件中重新确认媒体来源的安全上下文声明和编译后的
AppArmor 配置。普通浏览器能打开网页，不代表原生音乐链路已就绪。

启动器已补上仅针对本机媒体来源的安全上下文声明，并加载原厂 ChromiumApp 策略。
实际固件 Chromium 测试中，EME 接口从不可用变为可用；这还不能证明账户登录、CDM
初始化或付费内容播放成功。

之前从空的 sandbox.d 目录推断配置缺失不准确：真正的编译策略位于
etc/apparmor.compiled。经用户确认重启后，当前 WSL 的 AppArmor 已启用。原厂策略用于
确认固件要求的准确 peer 名称。“运行环境安装”会为只读用户挂载路径安装桌面兼容
profile，启动器随后把 QtCar、QtCarCluster、SpotifyServer 和 ChromiumAdapter 附加到
对应标签。实测重启后两个媒体服务均匹配成功，健康状态进入 `services-running`。
修改 WSL 内核启动参数会影响所有 WSL 2 发行版，需要先安排重启时间。
