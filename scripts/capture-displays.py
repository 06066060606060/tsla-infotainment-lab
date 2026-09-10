"""Save actual nested X11 displays for local documentation; requires PySide6."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('destination', type=Path)
parser.add_argument('--display', choices=('center', 'cluster'))
parser.add_argument('--only', choices=('center', 'cluster'))
args = parser.parse_args()
if args.display:
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])
    if not app.primaryScreen().grabWindow(0).save(str(args.destination)):
        raise SystemExit('Could not capture display')
else:
    data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'tsla-infotainment-lab/session'
    config = json.loads((data / 'config.json').read_text())
    args.destination.mkdir(parents=True, exist_ok=True)
    for display in ('center', 'cluster'):
        if args.only and args.only != display:
            continue
        if display == 'cluster' and not config['cluster']:
            continue
        subprocess.run([sys.executable, __file__, str(args.destination / (display + '.png')), '--display', display],
                       env=dict(os.environ, DISPLAY=config[display + '_display'], QT_QPA_PLATFORM='xcb'), check=True)
