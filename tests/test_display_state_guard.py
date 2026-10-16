"""Exercise the native startup guard without firmware, Qt or a display."""
import os
import platform
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64')
    or not shutil.which('gcc'), reason='Linux x86_64 C toolchain required')


@pytest.fixture
def guard_program(tmp_path):
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-display-state.c'
    guard = tmp_path / 'guard.so'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', str(source), '-o', str(guard), '-ldl'], check=True)
    # Synthetic framework: the same ABI and state-pointer access, with a counter
    # standing in for the initialized state's timer callback.
    assembly = tmp_path / 'framework.S'
    assembly.write_text('''
.text
.globl _ZN19DisplayStateManager12restartTimerEb
.type _ZN19DisplayStateManager12restartTimerEb, @function
_ZN19DisplayStateManager12restartTimerEb:
push %r15
push %r14
push %r13
push %r12
push %rbp
push %rbx
mov %rdi,%rbx
lea -0x38(%rsp),%rsp
mov %fs:0x28,%rbp
mov %rbp,0x28(%rsp)
mov %esi,%ebp
mov 0x58(%rdi),%rdi
mov (%rdi),%rax
incq (%rdi)
lea 0x38(%rsp),%rsp
pop %rbx
pop %rbp
pop %r12
pop %r13
pop %r14
pop %r15
ret
.section .note.GNU-stack,"",@progbits
''')
    subprocess.run(['gcc', '-shared', '-fPIC', str(assembly), '-o', str(tmp_path / 'framework.so')], check=True)
    main = tmp_path / 'main.c'
    main.write_text('''
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <sys/resource.h>
void restart(void *, bool) __asm__("_ZN19DisplayStateManager12restartTimerEb");
int main(int argc, char **argv) {
    struct rlimit limit = {0, 0};
    setrlimit(RLIMIT_CORE, &limit);
    unsigned char object[128] = {0};
    uint64_t counter = 0;
    void *state = &counter;
    if (argc > 1 && !strcmp(argv[1], "ready")) memcpy(object + 0x58, &state, sizeof(state));
    restart(object, true);
    return state && counter != (argc > 1 && !strcmp(argv[1], "ready"));
}
''')
    exe = tmp_path / 'probe'
    subprocess.run(['gcc', str(main), str(tmp_path / 'framework.so'), '-o', str(exe)], check=True)
    return exe, guard


def run_probe(program, enabled, state):
    exe, guard = program
    return subprocess.run([str(exe), state], env=dict(os.environ, LD_PRELOAD=str(guard),
        TESLA_NATIVE_DISPLAY_STATE_GUARD=enabled), capture_output=True, text=True)


def test_uninitialized_state_is_skipped_only_when_guard_is_enabled(guard_program):
    result = run_probe(guard_program, '1', 'not-ready')
    assert result.returncode == 0 and 'before display-state initialization' in result.stderr
    assert run_probe(guard_program, '0', 'not-ready').returncode == -signal.SIGSEGV


@pytest.mark.parametrize('enabled', ['0', '1'])
def test_initialized_state_keeps_its_original_timer_callback(guard_program, enabled):
    result = run_probe(guard_program, enabled, 'ready')
    assert result.returncode == 0 and not result.stderr
