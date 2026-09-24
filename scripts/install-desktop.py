"""Register an extracted Linux bundle in the current user's application menu."""
from pathlib import Path
import os

root = Path(__file__).resolve().parent
if not (root / 'Launch-Linux.sh').is_file():
    root = root.parent
launcher = root / 'Launch-Linux.sh'
if not launcher.is_file():
    raise SystemExit('The application launcher Launch-Linux.sh is missing.')
target = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications/infotainment-lab.desktop'
target.parent.mkdir(parents=True, exist_ok=True)
quoted = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
target.write_text('[Desktop Entry]\nType=Application\nName=Infotainment Lab\n'
                  f'Exec=/usr/bin/bash "{quoted}" %F\nTerminal=false\nStartupWMClass=Infotainment Lab\nCategories=Development;Science;\n', encoding='utf-8')
print(f'Added Infotainment Lab to your application menu: {target}')
