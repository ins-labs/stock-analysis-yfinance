"""Synthetic-only public dispatcher while real-market permissions remain on hold."""
import os
import shlex
import subprocess
import sys


def parse_command(value):
    args = shlex.split(value)
    if args != ['python', 'fixture_demo.py']:
        raise ValueError('Only python fixture_demo.py is enabled; real-market analysis is on hold')
    return [sys.executable, 'fixture_demo.py']


def main():
    command = os.environ.get('ANALYSIS_COMMAND', '')
    args = parse_command(command)
    print('SYNTHETIC_FIXTURE_ONLY public command: ' + shlex.join(args[1:]), flush=True)
    result = subprocess.run(args, check=False)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
