import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import requests


ROOT = Path(__file__).resolve().parents[2]
HOST = 'http://127.0.0.1:8001'


def stop_tree(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
    except psutil.Error:
        children = []
    for child in children:
        try:
            child.terminate()
        except psutil.Error:
            pass
    try:
        process.terminate()
        process.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        try:
            process.kill()
        except OSError:
            pass


def wait_until_ready(process, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Django encerrou antes do smoke test (codigo {process.returncode}).')
        try:
            live = requests.get(f'{HOST}/health/live/', timeout=2)
            ready = requests.get(f'{HOST}/health/ready/', timeout=2)
            if live.status_code == 200 and ready.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError('Django nao ficou pronto em 20 segundos.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--users', type=int, default=10)
    parser.add_argument('--spawn-rate', type=float, default=5)
    parser.add_argument('--run-time', default='20s')
    parser.add_argument('--csv-prefix')
    args = parser.parse_args()

    server = subprocess.Popen(
        [sys.executable, '-u', 'manage.py', 'runserver', '127.0.0.1:8001', '--noreload'],
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_until_ready(server)
        checks = {
            'live': requests.get(f'{HOST}/health/live/', timeout=3).status_code,
            'ready': requests.get(f'{HOST}/health/ready/', timeout=3).status_code,
            'login': requests.get(f'{HOST}/login/', timeout=3).status_code,
        }
        print('smoke=' + ','.join(f'{name}:{status}' for name, status in checks.items()), flush=True)
        if args.smoke:
            return 0

        command = [
            sys.executable,
            '-m',
            'locust',
            '-f',
            str(ROOT / 'tests' / 'load' / 'locustfile.py'),
            '--headless',
            '--host',
            HOST,
            '--users',
            str(args.users),
            '--spawn-rate',
            str(args.spawn_rate),
            '--run-time',
            args.run_time,
            '--only-summary',
        ]
        if args.csv_prefix:
            command.extend(['--csv', args.csv_prefix])
        return subprocess.run(command, cwd=ROOT, env=os.environ.copy(), check=False).returncode
    finally:
        stop_tree(server)


if __name__ == '__main__':
    raise SystemExit(main())
