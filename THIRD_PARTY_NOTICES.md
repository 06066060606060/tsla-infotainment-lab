# Third-party notices

The MIT license covers the original source in this repository. It does not grant rights to firmware, map data, vendor applications, trademarks, or their interface artwork. No Tesla firmware or map payload is distributed here. Screenshots document a local compatibility experiment; the depicted third-party interfaces retain their respective rights.

The desktop application uses **PySide6 / Qt for Python 6.9.3** and **Shiboken6**, available under LGPLv3, GPLv3, or commercial terms. This project uses the LGPL distribution. Qt and its multimedia components include further notices. Binary bundles keep Qt libraries separate under `_internal` so recipients can replace compatible libraries. Do not remove their license files. Consult the [Qt for Python licensing overview](https://doc.qt.io/qtforpython-6/licenses.html) and the [corresponding Qt for Python source release](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.9.3-src/). Qt base sources are available from [Qt's source archives](https://download.qt.io/archive/qt/6.9/6.9.3/single/).

The packaging script copies installed package license notices into the bundle. When distributing binaries, retain them and provide the corresponding source and applicable notices required by the dependency licenses. Local release packaging is not a substitute for checking the final dependency inventory.

**PyInstaller 6.16.0** uses the GPL with a bootloader exception that permits packaging applications under their own license; see its [license documentation](https://pyinstaller.org/en/stable/license.html). Python and bundled runtime libraries retain their own licenses.

Runtime packages such as Mesa, Xephyr, X11 libraries, FUSE, D-Bus, ALSA, PulseAudio, Pillow and FFmpeg are installed through the user's distribution. They are not firmware artifacts and are not copied from the firmware into this repository. Their distribution packages include their own notices.

The optional QEMU guest builder downloads **VirtualGL 3.1.5** from its [upstream release](https://github.com/VirtualGL/virtualgl/releases/tag/3.1.5), verifies a pinned SHA-256 digest, and installs it only in the generated guest. VirtualGL uses the wxWindows Library Licence; the upstream package includes its notices and third-party license files. VirtualGL binaries are not included in this repository or in the Qt application bundle.

The camera V4L2 adapter is adapted from Derrick Yao's `tesla-subsystem-for-windows-dot-8/tesla-v4l2-camera-shim.c`, supplied in the original project workspace. The RGB24 file interface remains compatible with that project's camera writer. Only the camera device adapter is reused here; its gateway and browser-server launch stack is not required.
