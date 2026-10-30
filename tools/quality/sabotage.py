#!/usr/bin/env python3
# Sabotage: prove that a guard can go red. Substitute a line → run the test command → always restore the file.
# A green guard without sabotage proves nothing; the red must be EXACTLY in your tests.
from __future__ import annotations

import os
import sys
import argparse
import subprocess
from pathlib import Path

# A same-length substitution within the same second changes neither size nor mtime — Python takes the old .pyc; the file cache is wiped, no bytecode is written
def drop_bytecode(path:Path) -> None:
    for pyc in (path.parent / '__pycache__').glob(f'{path.stem}.*.pyc'): pyc.unlink(missing_ok = True)

def run(cmd:list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output = True, text = True, timeout = 1800, env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1'})

def main() -> int:
    ap = argparse.ArgumentParser(description = 'sabotage.py FILE --find "old" --replace "broken" -- <test command>')
    ap.add_argument('file')
    ap.add_argument('--find', required = True, help = 'exact fragment, occurs in the file exactly once')
    ap.add_argument('--replace', required = True)
    ap.add_argument('--expect', nargs = '*', default = [], help = 'names of the tests that must go red')
    argv = sys.argv[1:]
    cut = argv.index('--') if '--' in argv else len(argv)
    args, cmd = ap.parse_args(argv[:cut]), argv[cut + 1:]
    if not cmd: sys.exit('a test command is required after --')
    path = Path(args.file)
    original = path.read_bytes()
    text = original.decode('utf-8')
    if text.count(args.find) != 1: sys.exit(f'the fragment occurs {text.count(args.find)} times, exactly one is required')
    # First green without sabotage: otherwise a red from an outside cause (no module, broken stand) is taken for a catch
    drop_bytecode(path)
    clean = run(cmd)
    if clean.returncode != 0: sys.exit('the command is already red without sabotage, fix the setup first:\n' + (clean.stdout + clean.stderr)[-1500:])
    try:
        path.write_text(text.replace(args.find, args.replace), encoding = 'utf-8')
        drop_bytecode(path)
        broken = run(cmd)
    finally:
        path.write_bytes(original)
        drop_bytecode(path)
    output = broken.stdout + broken.stderr
    failed = [line for line in output.splitlines() if 'FAILED' in line or line.startswith('ERROR')]
    missing = [name for name in args.expect if not any(name in line for line in failed)]
    print('\n'.join(failed[:40]) or output[-2000:])
    if broken.returncode == 0: print('BLIND GUARD: everything is green under sabotage'); return 1
    if missing: print('the wrong tests went red, these did not fail: ' + ', '.join(missing)); return 1
    print('the guard sees: sabotage caught, file restored')
    return 0

if __name__ == '__main__': sys.exit(main())
