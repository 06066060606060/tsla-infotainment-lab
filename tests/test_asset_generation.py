import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from infotainment_lab.asset_generation import Renderer, decode_identifier, ready


IDENTIFIER = '0775698a-1-3a1000000000301002---'


def complete(cache, identifier=IDENTIFIER):
    for name in ('success_sentinel', 'day/TrackMode.png', 'night/TrackMode.png'):
        path = cache / 'AssetGen' / identifier / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'owned test asset')


class Process:
    def __init__(self):
        self.result = None
        self.terminated = self.killed = False

    def poll(self):
        return self.result

    def terminate(self):
        self.terminated = True
        self.result = -15

    def kill(self):
        self.killed = True
        self.result = -9

    def wait(self, timeout):
        return self.result


def renderer(tmp_path):
    calls = []

    def spawn(*args, **kwargs):
        process = Process()
        calls.append((process, args, kwargs))
        return process

    return Renderer(tmp_path / 'firmware', tmp_path / 'cache',
                    {'TESLA_HOME': str(tmp_path)}, tmp_path / 'render.log', spawn=spawn), calls


@pytest.mark.parametrize('value', ('../../elsewhere', '/tmp/cache', '..', '', 'x/y', '<invalid>', None))
def test_unusable_identifiers_do_not_start_a_renderer(tmp_path, value):
    worker, calls = renderer(tmp_path)
    assert worker.tick(value, 10) == 'waiting-config'
    assert not ready(worker.cache, value)
    assert calls == []


def test_native_unquoted_and_json_identifiers_are_accepted():
    assert decode_identifier(IDENTIFIER) == IDENTIFIER
    assert decode_identifier('"' + IDENTIFIER + '"') == IDENTIFIER
    for raw in ('null', '[]', 'true', '"../../path"', '<invalid>'):
        assert decode_identifier(raw) == ''


def test_validated_cache_skips_rendering_and_partial_cache_does_not(tmp_path):
    worker, calls = renderer(tmp_path)
    complete(worker.cache)
    assert worker.tick(IDENTIFIER, 10) == 'ready'
    assert calls == []
    (worker.cache / 'AssetGen' / IDENTIFIER / 'night/TrackMode.png').unlink()
    assert worker.tick(IDENTIFIER, 12) == 'generating'
    assert worker.tick(IDENTIFIER, 14) == 'generating'
    assert len(calls) == 1
    process, args, kwargs = calls[0]
    assert '--apviz-assetgen' in args[0]
    assert kwargs['cwd'] == str(tmp_path)
    complete(worker.cache)
    process.result = 0
    assert worker.tick(IDENTIFIER, 16) == 'ready'
    assert worker.stream is None


def test_failed_or_stalled_rendering_is_bounded_and_owned(tmp_path):
    worker, calls = renderer(tmp_path)
    assert worker.tick(IDENTIFIER, 10) == 'generating'
    first = calls[0][0]
    assert worker.tick(IDENTIFIER, 100) == 'waiting-retry'
    assert first.terminated
    assert worker.tick(IDENTIFIER, 129) == 'waiting-retry'
    assert worker.tick(IDENTIFIER, 130) == 'generating'
    calls[1][0].result = 1
    assert worker.tick(IDENTIFIER, 132) == 'failed'
    assert worker.tick(IDENTIFIER, 1000) == 'failed'
    assert len(calls) == 2
    assert worker.tick('new-car', 1002) == 'generating'
    worker.stop()
    assert calls[-1][0].terminated
    assert worker.stream is None


def test_shutdown_kills_an_unresponsive_owned_renderer(tmp_path):
    worker, calls = renderer(tmp_path)
    worker.tick(IDENTIFIER, 10)
    process = calls[0][0]
    process.terminate = lambda: None
    waits = []

    def wait(timeout):
        waits.append(timeout)
        if process.result is None:
            raise subprocess.TimeoutExpired('owned renderer', timeout)
        return process.result

    process.wait = wait
    worker.stop()
    assert process.killed
    assert waits == [5, 5]
    assert worker.process is None and worker.stream is None


def test_spawn_failure_does_not_loop_or_leave_an_open_log(tmp_path):
    worker, _ = renderer(tmp_path)

    def fail(*args, **kwargs):
        raise OSError('renderer unavailable')

    worker.spawn = fail
    assert worker.tick(IDENTIFIER, 10) == 'failed'
    assert worker.tick(IDENTIFIER, 12) == 'waiting-retry'
    assert worker.tick(IDENTIFIER, 40) == 'failed'
    assert worker.tick(IDENTIFIER, 100) == 'failed'
    assert worker.attempts == 2
    assert worker.stream is None


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc') or not shutil.which('g++'),
                    reason='Linux C/C++ toolchain required')
def test_native_asset_path_uses_qt_return_abi_in_global_and_godot_local_loads(tmp_path):
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-assetgen.c'
    adapter = tmp_path / 'adapter.so'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', str(source),
                    '-o', str(adapter), '-ldl'], check=True)
    framework = tmp_path / 'framework.cpp'
    framework.write_text('''
#include <string>
#include <cstdio>
class QString {
public:
    std::string text;
    QString(const char *s): text(s) {}
    ~QString() {}
    static QString fromUtf8(const char *,int);
};
QString QString::fromUtf8(const char *s,int) { return QString(s); }
class StorageUtils { public: static QString godotDataFolder(); };
QString StorageUtils::godotDataFolder() { return QString("/vehicle/default"); }
extern "C" void probe() { std::puts(StorageUtils::godotDataFolder().text.c_str()); }
''')
    library = tmp_path / 'libQtCore.so.4'
    subprocess.run(['g++', '-shared', '-fPIC', str(framework), '-o', str(library)], check=True)
    main = tmp_path / 'main.cpp'
    main.write_text('''
#include <dlfcn.h>
int main(int argc,char **argv) {
    void *h=dlopen(argv[1],RTLD_NOW | (argc>2 ? RTLD_GLOBAL : RTLD_LOCAL));
    if (!h) return 2;
    auto probe=(void(*)())dlsym(h,"probe");
    probe();
    dlclose(h);
}
''')
    executable = tmp_path / 'probe'
    subprocess.run(['g++', str(main), '-o', str(executable), '-ldl'], check=True)
    for visibility in ('local', 'global'):
        for override, expected in (('/owned/cache', '/owned/cache'), ('', '/vehicle/default'),
                                   ('relative/path', '/vehicle/default')):
            # No opt-in adapter is loaded in the local Godot case without the
            # cache setting; ordinary processes do not receive this preload.
            if visibility == 'local' and not override.startswith('/'):
                continue
            args = [str(executable), str(library)] + (['global'] if visibility == 'global' else [])
            env = dict(os.environ, LD_PRELOAD=str(adapter), LD_LIBRARY_PATH=str(tmp_path),
                       TESLA_NATIVE_ASSET_DATA=override)
            result = subprocess.run(args, capture_output=True, text=True, env=env, check=True)
            assert result.stdout.strip() == expected
