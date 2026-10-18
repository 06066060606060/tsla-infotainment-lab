"""Private file replacements layered above an unchanged firmware image."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

try:
    from .core import safe_id
except ImportError:
    from core import safe_id


def member_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Enter a path inside the firmware, such as /usr/tesla/UI/file.qml.')
    value = value.removeprefix('/')
    parts = value.split('/')
    if any(part in ('', '.', '..') or part.startswith(('.wh.', '.pending-')) for part in parts):
        raise ValueError('The firmware path must not contain empty, dot or parent components.')
    return PurePosixPath(value)


def private_directory(path):
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('The replacement directory must not contain symbolic links.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Use a private replacement directory owned by the desktop user.')
    return path


def tree(data, identifier):
    base = private_directory(Path(data) / 'replacements')
    return private_directory(base / safe_id(identifier))


@contextmanager
def lock(data):
    import fcntl
    base = private_directory(Path(data) / 'replacements')
    path = base / '.lock'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def entries(root):
    root = Path(root)
    if not root.exists():
        return []
    result = []
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(parent) / name
            if path.is_symlink():
                raise ValueError('Symbolic links are not allowed in replacement storage.')
        for name in files:
            path = Path(parent) / name
            if not path.is_file():
                raise ValueError('Replacement storage must contain only regular files.')
            member = member_path(path.relative_to(root).as_posix())
            result.append({'target': '/' + str(member), 'bytes': path.stat().st_size})
    return sorted(result, key=lambda item: item['target'])


def original(root, member):
    root = Path(root).resolve(strict=True)
    path = root.joinpath(*member.parts)
    # Refuse symlinks instead of letting absolute links reach the host filesystem.
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Choose the real firmware path instead of a symbolic link.')
    if not path.is_file():
        raise ValueError('Choose an existing regular file inside the firmware.')
    return path


def put(data, identifier, root, target, filename):
    member = member_path(target)
    source = Path(filename).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError('Select a regular replacement file.')
    mode = stat.S_IMODE(original(root, member).stat().st_mode) & 0o777
    upper = tree(data, identifier)
    entries(upper)  # reject tampered storage before creating parent directories
    destination = upper.joinpath(*member.parts)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    before = source.stat()
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output, 1024 * 1024)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RuntimeError('The replacement file changed while being copied. Retry when its writer has finished.')
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return entries(upper)


def remove(data, identifier, target):
    member = member_path(target)
    upper = tree(data, identifier)
    entries(upper)
    path = upper.joinpath(*member.parts)
    path.unlink(missing_ok=True)
    parent = path.parent
    while parent != upper:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return entries(upper)


STYLES = PurePosixPath('usr/tesla/UI/assets/styles-M3.conf')
# The firmware bottom-aligns these panels on the 1200 px screen, so their last 100 px sit behind
# the bottom bar and a strip is left above them. 100 px taller moves each top edge up by that much.
# The HVAC panel is placed by fixed Y offsets instead, which move up by the same 100 px.
PANEL_HEIGHTS = (
    (re.compile(r'^ControlPanelHeight = "Height:1040;"[ \t]*$', re.M), 'ControlPanelHeight = "Height:1140;"'),
    (re.compile(r'^(ClimateControlPanel = "HVACPanelSize; X:0; Y:)360(; BackgroundColor:transparent;")[ \t]*$', re.M), r'\g<1>260\2'),
    (re.compile(r'^(BackgroundView = "CenterDisplayWidth; X:0; Y:)360(; Height:680;")[ \t]*$', re.M), r'\g<1>260\2'),
    (re.compile(r'^(ViewSwitchStyle = "AlignItems:center; JustifyContent:center; HVAC/HVACViewWidth; X:0; Y:)380(; PositionType:absolute;")[ \t]*$', re.M), r'\g<1>280\2'),
    (re.compile(r'^(KeepClimatePopupStyleCommon = "BackgroundColor:transparent; X:608; Y:)230(; PositionType:absolute; Height:100; Width:708;")[ \t]*$', re.M), r'\g<1>130\2'),
)


COMMON = PurePosixPath('usr/tesla/UI/assets/styles-common.conf')
# Neither window padding nor margin moves these panels, but their scrolling areas fill the window's
# height, so the lists ended under the bottom bar. Leave 100 px at the bottom of each.
SCROLL_AREAS = (
    (STYLES, re.compile(r'^(PageLayout = "ControlsPanel/ControlsPanelWidth; FlexDirection:column; JustifyContent:FlexStart; Padding:0,40,0,)0(; Margin:20,0,20,0;)', re.M), r'\g<1>100\2'),
    (STYLES, re.compile(r'^(TabLayout \+= "Padding:0,25;)( TabWidth:420; TabHeight:71;")[ \t]*$', re.M), r'\g<1> Margin:0,0,0,100;\2'),
    (COMMON, re.compile(r'^ScrollableSettingsPanel = "Flex:1; MaxHeight:800; Margin:0,20,20,20;"[ \t]*$', re.M),
     'ScrollableSettingsPanel = "Flex:1; MaxHeight:800; Margin:0,20,20,120;"'),
)


def layout_layer(base, directory):
    """A layer for single-display sessions that lifts the Controls and HVAC panels to the screen's usable height.

    Each value is changed only when this build's file has exactly the expected line. Returns the
    layer directory, or None when no value matched.
    """
    texts, changed = {}, 0
    for member, pattern, line in (*((STYLES, *entry) for entry in PANEL_HEIGHTS), *SCROLL_AREAS):
        if member not in texts:
            try:
                texts[member] = (Path(base) / member).read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                texts[member] = None
        if texts[member] is not None:
            texts[member], count = pattern.subn(line, texts[member])
            changed += count == 1
    if not changed:
        return None
    directory = private_directory(directory)
    for member, text in texts.items():
        if text is None:
            continue
        target = directory / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)  # the previous copy is read-only
        target.write_text(text, encoding='utf-8')
        target.chmod(0o444)
    return directory


def mount_view(base, upper, mount, run, layers=()):
    """Read-only branches: replacements win, then the lab's layers, then the SquashFS."""
    base, upper, mount = map(Path, (base, upper, mount))
    layers = [Path(layer) for layer in layers if layer]
    if not entries(upper) and not layers:
        return base
    if not shutil.which('fuse-overlayfs'):
        raise RuntimeError('Install fuse-overlayfs with Prepare computer to use firmware replacements.')
    # Branch paths use separators even though subprocess receives structured argv.
    if any(any(char in str(path) for char in ':=,') for path in (base, upper, *layers)):
        raise ValueError('Replacement mount paths must not contain colon, equals or comma characters.')
    if mount.is_symlink():
        raise ValueError('The firmware view must not be a symbolic link.')
    mount.mkdir(parents=True, exist_ok=True)
    if os.path.ismount(mount) or any(mount.iterdir()):
        raise RuntimeError('Release the previous firmware view before starting a session.')
    run(['fuse-overlayfs', '-o', f'ro,nosuid,nodev,lowerdir={":".join(map(str, (upper, *layers, base)))}', mount], timeout=30)
    if not os.path.ismount(mount):
        raise RuntimeError('The replacement filesystem did not mount.')
    return mount
