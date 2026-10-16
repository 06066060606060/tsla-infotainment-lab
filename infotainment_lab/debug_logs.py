"""Bounded local log snapshots, kept separate from public diagnostic exports."""
from pathlib import Path
import os
import stat
import subprocess
import time

MAX_BYTES = 32000
MAX_FILES = 24


def tail(path):
    try:
        path = Path(path)
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return '[This log is not a regular file.]'
            size = source.seek(0, 2)
            offset = max(0, size - MAX_BYTES)
            source.seek(offset)
            data = source.read(MAX_BYTES)
        text = data.decode('utf-8', errors='replace')
        return ('[Earlier output omitted.]\n' if offset else '') + text
    except OSError as exc:
        return f'[Log unavailable: {exc}]'


def journal(arguments):
    try:
        result = subprocess.run(['journalctl', '--no-pager', '-o', 'short-iso', '-n', '200', *arguments],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=3)
        if result.returncode:
            return '[Journal unavailable: ' + (result.stderr.strip() or 'access denied')[-1000:] + ']'
        return (result.stdout[-MAX_BYTES:] or '[No journal entries available.]')
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f'[Journal unavailable: {exc}]'


def snapshot(session, unit, *, guest=False):
    session = Path(session)
    logs = {path.name: tail(path) for path in sorted(session.glob('*.log'))[:MAX_FILES]}
    logs['Session journal'] = journal(['-b', '-u', unit] if guest else ['--user', '-b', '-u', unit])
    logs['Guest kernel' if guest else 'Host kernel (native runtime)'] = journal(['-k', '-b'])
    if guest:
        logs['Guest OS journal'] = journal(['-b'])
    return {'logs': logs, 'captured_at': time.time(),
            'context': 'QEMU guest OS' if guest else 'Native compatibility session on the host OS'}
