# Keep Python workers as source files: Debian's Python supplies dbus and gi.
from pathlib import Path
import sys

root = Path(SPECPATH)
datas = [(str(root / 'infotainment_lab' / '*.py'), 'infotainment_lab'),
         (str(root / 'scripts/build-virtual-guest.py'), 'scripts'),
         (str(root / 'infotainment_lab' / 'profiles.json'), 'infotainment_lab'),
         (str(root / 'LICENSE'), '.'), (str(root / 'THIRD_PARTY_NOTICES.md'), '.')]
datas += [(str(path), 'infotainment_lab/assets') for path in (root / 'infotainment_lab' / 'assets').glob('*.svg')]
datas += [(str(path), 'infotainment_lab/runtime')
          for path in sorted((root / 'infotainment_lab' / 'runtime').iterdir())
          if path.is_file() and path.suffix in ('.py', '.c', '.conf', '.html', '.profile', '.json')]
a = Analysis([str(root / 'run_app.py')], pathex=[str(root)], datas=datas, hiddenimports=[],
             excludes=['tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='InfotainmentLab',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='InfotainmentLab')
