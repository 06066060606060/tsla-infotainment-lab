"""Private file replacements layered above an unchanged firmware image."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
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


def mount_view(base, upper, mount, run):
    """Read-only branches: replacements win, everything else comes from SquashFS."""
    base, upper, mount = map(Path, (base, upper, mount))
    if not entries(upper):
        return base
    if not shutil.which('fuse-overlayfs'):
        raise RuntimeError('Install fuse-overlayfs with Prepare computer to use firmware replacements.')
    # Branch paths use separators even though subprocess receives structured argv.
    if any(any(char in str(path) for char in ':=,') for path in (base, upper)):
        raise ValueError('Replacement mount paths must not contain colon, equals or comma characters.')
    if mount.is_symlink():
        raise ValueError('The firmware view must not be a symbolic link.')
    mount.mkdir(parents=True, exist_ok=True)
    if os.path.ismount(mount) or any(mount.iterdir()):
        raise RuntimeError('Release the previous firmware view before starting a session.')
    run(['fuse-overlayfs', '-o', f'ro,nosuid,nodev,lowerdir={upper}:{base}', mount], timeout=30)
    if not os.path.ismount(mount):
        raise RuntimeError('The replacement filesystem did not mount.')
    return mount
