# Infotainment Lab

[English](README.md) · [下载](https://github.com/derrickyau9/tsla-infotainment-lab/releases/latest) · [更新日志](CHANGELOG.md)

在自己的电脑上运行车机软件，把中控和仪表盘作为独立桌面窗口打开。原生 Qt 应用负责固件管理、驾驶控制、浏览器、摄像头和行驶记录回放。

支持 Linux，以及安装了 Debian WSL2 的 Windows。**0.5.0** 带来 Material 3 界面和 QEMU 桌面模式。

![设备管理器](docs/screenshots/material-devices-en.png)

## 先准备固件

**你需要自行准备兼容的 Firmware Dump。** 仓库和发行包均不包含固件或地图。请使用你有权使用的固件；项目不提供提取工具或导出教程。

字体和车辆资源直接从所选固件读取。Model S/X MCU2 固件使用中控与仪表双屏，ICE 固件使用横向中控屏。内置 MCU2 配置对应 **2026.26.6.1**，其他版本按平台选择适配配置。

## 开始使用

需要 x86_64 电脑和 Linux 图形桌面。Windows 用户先安装 **WSL2 Debian**，并开启 [WSLg 图形应用支持](https://learn.microsoft.com/zh-cn/windows/wsl/tutorials/gui-apps)。

1. 下载发行包并完整解压，保留可执行文件旁边的 `_internal` 文件夹。
2. Linux 应用通过 `bash Launch-Linux.sh` 启动；Windows 下可双击 **Launch-WSL.cmd**。下载 Windows 控制面板包后，使用 **InfotainmentLab.exe**。
3. 点击“准备电脑”，安装 Linux 运行组件。
4. 把固件拖入“设备”页，选中后点击“启动设备”。
5. 使用顶部“中控”和“仪表”按钮打开对应窗口。“截图”会保存两块屏幕的 PNG 图片。

请以普通桌面用户运行。安装系统组件时，应用会请求管理员权限。Linux 二进制包需要 glibc 2.41 或更高版本。

关闭控制面板后，车机会继续运行。“停止”结束会话；“重启”会重新启动并回到 P 挡。设备选项和所选地图会自动保存。

### 从源码运行

安装 Python 3.11+ 和 `python3-venv`，然后运行：

```bash
git clone https://github.com/derrickyau9/tsla-infotainment-lab.git
cd tsla-infotainment-lab
bash Launch-Linux.sh
```

首次启动会创建 Python 环境并安装 Qt。Windows 下可使用项目中的 **Launch-WSL.cmd**。需要指定其他发行版时，在 PowerShell 中运行 `Launch-WSL.ps1 -Distribution <名称>`。

运行 `scripts/install-wsl-shortcut.ps1` 可以添加开始菜单快捷方式。如果窗口没有出现，从终端启动可查看错误，启动日志位于 `~/.local/state/tsla-infotainment-lab/launcher.log`。

### QEMU 模式

在“设备”中选择 **QEMU**，即可在 Debian 客体内运行车机桌面。控制面板提供启动、关机、双屏预览、浏览器卡片、驾驶输入和摄像头回放。MCU2 桌面使用 VirGL，仪表独立窗口通过 VirtualGL 共用 GPU。

QEMU 使用替代 Linux 内核，固件镜像保持只读。客体磁盘需按 [QEMU 桌面指南](docs/virtual-desktop.md)在本机构建。

## 调整外观

可以选择跟随系统、浅色或深色主题，以及鸢尾紫、晴空蓝、叶绿强调色。窗口缩小时会切换为紧凑导航。控制面板支持简体中文和英文。

![深色主题下的驾驶控制](docs/screenshots/material-controls-zh.png)

## 驾驶与仪表

在“控制”页选择 P、R、N、D 挡，调整车速、加速踏板、制动、方向盘和转向灯。中控和仪表使用同一份本地输入。切回 P 挡会将车速和加速踏板归零。

方向盘按钮可调节音量、静音、播放和切歌，按住音量加减键可连续调整。右侧按钮用于打开仪表面板。Santa 模式、支持的显示偏好，以及音乐标题和播放信息会在两块屏幕之间同步。

![Santa 模式与仪表音量弹窗](docs/screenshots/cluster-santa.png)

“车辆服务”集中管理空调、车门、灯光、电量和声音。打开车门、修改电量或切换车灯后，面板会显示固件响应。在原生车机内调节空调和音量，也会更新控制面板。具体操作见[车辆服务指南](docs/vehicle-services.md)。

这些控制只作用于本地桌面会话，不连接真实车辆。

## 浏览器

打开“浏览器”页，输入网址后选择“浏览器”或“卡片模式”。“影院”打开固件自带的应用目录。浏览器与卡片共用配置，支持在嵌入视图中输入文字、滚动、选中文字和拖动。

网址留空时会打开本地示例页，其中包含声音、文字输入、拖动和 WebGL 示例。音乐应用从中控打开，使用各自的账号登录。

<img src="docs/screenshots/embedded-browser.png" width="350" alt="中控内的 Chromium" /> <img src="docs/screenshots/theater.png" width="350" alt="原生影院目录" />

## 摄像头与行驶回放

在“摄像头与回放”中选择测试画面、打开视频，或连接现有 RGB 管线。在中控打开摄像头，也可以挂 R 挡进入倒车画面。

点击“打开行车记录仪 MP4…”选择带内嵌行驶数据的录像。挡位、车速、踏板、转向和转向灯会跟随视频；暂停、跳转、倍速和循环播放同时作用于画面与数据。“接管”切回手动控制，再次播放可恢复录像输入。

![摄像头与回放](docs/screenshots/replay-en.png)

没有录像时，可运行 `python3 scripts/make-replay-demo.py`，然后打开生成的 `build/replay-demo.mp4`。

现有摄像头管线可通过原子替换文件输出 **1280 × 720 RGB24** 帧，例如 `/tmp/tesla-sim/v4l2-back.rgb`。在面板填入该路径即可连接。格式细节见[摄像头与回放说明](docs/replay.md)。

## 开发

这是一个独立的兼容性与网络安全工程项目，涉及原生图形、输入事件、进程管理和本地模拟，所提供的固件保持不变。

参阅[架构](docs/ARCHITECTURE.md)、[兼容性说明](docs/compatibility.md)和[贡献指南](CONTRIBUTING.md)。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python scripts/build.py
```

Windows 使用 `.venv\Scripts\Activate.ps1` 激活环境。请在目标操作系统上构建，产物位于 `dist/`。

固件、地图、录像、浏览器配置、日志和凭据不会加入仓库。公开回放截图使用生成的演示画面。

本项目与 Tesla 无隶属或背书关系。项目源码采用 MIT 许可证；固件、商标、第三方界面截图和依赖保留各自权利。详见[第三方声明](THIRD_PARTY_NOTICES.md)。
