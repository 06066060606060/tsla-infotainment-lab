"""Build a native directory bundle. Run on the OS you want to distribute for."""
from pathlib import Path
import platform
import subprocess
import sys
import shutil
import importlib.metadata
import tarfile
import tomllib

root = Path(__file__).resolve().parent.parent
system = 'windows-wsl' if platform.system() == 'Windows' else 'linux'
output = root / 'dist' / system
if not output.resolve().is_relative_to(root.resolve()) or not (root / 'build' / system).resolve().is_relative_to(root.resolve()):
    raise SystemExit('Build output resolves outside this repository.')
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(output),
                '--workpath', str(root / 'build' / system), str(root / 'InfotainmentLab.spec')], cwd=root, check=True)
bundle = output / 'InfotainmentLab'
for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
             'SECURITY.md', 'CONTRIBUTING.md', 'CHANGELOG.md'):
    shutil.copy2(root / name, bundle / name)
shutil.copytree(root / 'docs', bundle / 'docs', dirs_exist_ok=True)
shutil.copytree(root / 'third-party-licenses', bundle / 'third-party-licenses', dirs_exist_ok=True)
inventory = []
for name in ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6', 'pyinstaller'):
    package = importlib.metadata.distribution(name)
    inventory.append(f'{name}=={package.version}')
    for member in package.files or []:
        if any(part.lower() in ('licenses', 'license') for part in member.parts) or member.name.lower().startswith(('license', 'copying')):
            source = Path(package.locate_file(member))
            if source.is_file():
                destination = bundle / 'third-party-licenses' / name / str(member)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
(bundle / 'dependency-versions.txt').write_text('\n'.join(inventory) + '\n')
version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
release = root / 'dist' / f'tsla-infotainment-lab-{version}-{system}-{platform.machine().lower()}'
if system == 'linux':
    shutil.copy2(root / 'scripts/install-desktop.py', bundle / 'install-desktop.py')
    shutil.copy2(root / 'scripts/install-wsl-shortcut.ps1', bundle / 'install-wsl-shortcut.ps1')
    for name in ('Launch-Linux.sh', 'Launch-WSL.cmd', 'Launch-WSL.ps1'):
        shutil.copy2(root / name, bundle / name)
    artifact = str(release) + '.tar.gz'
    def archive_metadata(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        source = output / info.name
        executable = False
        if source.is_file() and not source.is_symlink():
            with source.open('rb') as stream:
                executable = stream.read(4) == b'\x7fELF'
        info.mode = 0o755 if info.isdir() or executable else 0o644
        return info
    with tarfile.open(artifact, 'w:gz') as archive:
        archive.add(bundle, arcname='InfotainmentLab', filter=archive_metadata)
else:
    artifact = shutil.make_archive(str(release), 'zip', output, 'InfotainmentLab')
print(artifact)
