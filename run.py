"""Supervise bettercap and the pinned Pwnagotchi port on the CM0."""
import argparse
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import tomllib

ROOT = Path(__file__).resolve().parent
STOP = threading.Event()
SUPPORTED_ADAPTERS = {
    ('0846', '9055'): 'NETGEAR A6150',
    ('2357', '012d'): 'TP-Link Archer T3U',
}


def command(*args, check=True):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=20, check=False)
    if check and result.returncode:
        raise RuntimeError('%s: %s' % (' '.join(args), result.stdout.strip()))
    return result


def find_adapter(netroot=Path('/sys/class/net')):
    matches = []
    for interface in netroot.iterdir():
        if interface.name == 'pwn0':
            continue
        device = (interface / 'device').resolve()
        for parent in [device, *device.parents]:
            vendor, product = parent / 'idVendor', parent / 'idProduct'
            if vendor.is_file() and product.is_file():
                if (vendor.read_text().strip().lower(), product.read_text().strip().lower()) in SUPPORTED_ADAPTERS:
                    matches.append(interface.name)
                break
    if len(matches) > 1:
        raise RuntimeError('Multiple supported adapter interfaces found: ' + ', '.join(matches))
    return matches[0] if matches else None


def stop_child(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def radio_generation(adapter, monitor, netroot=Path('/sys/class/net')):
    """Interface indices change when USB re-enumerates, even if names repeat."""
    try:
        return tuple(int((netroot / name / 'ifindex').read_text())
                     for name in (adapter, monitor))
    except FileNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/etc/gothcwili/config.toml'))
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.probe:
        interface = find_adapter()
        print(json.dumps({'interface': interface, 'supported_usb_ids':
                         [':'.join(identity) for identity in SUPPORTED_ADAPTERS]}))
        return 0 if interface else 1
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo or systemctl start gothcwili')
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    config = tomllib.loads(args.config.read_text())
    sys.path.insert(0, str(ROOT / 'runtime'))
    from pwnagotchi.radio_scope import allowed_bssids
    scope = allowed_bssids(config)
    if any(config['personality'].get(key) for key in ('deauth', 'associate')) and not scope:
        raise RuntimeError('Active mode requires main.allowed_bssids with authorized test targets')
    if config.get('ai', {}).get('enabled', True):
        from importlib.util import find_spec
        if find_spec('stable_baselines3') is None:
            raise RuntimeError('Install the AI dependencies into /opt/gothcwili-venv')
    monitor = config['main']['iface']
    if monitor != 'pwn0':
        raise RuntimeError('This launcher reserves main.iface = pwn0')
    adapter = None
    for _ in range(45):
        adapter = find_adapter()
        if adapter or STOP.wait(1):
            break
    if STOP.is_set():
        return 0
    if not adapter:
        raise RuntimeError('No supported Wi-Fi adapter found on the CM0 host port '
                           '(NETGEAR A6150 0846:9055 or TP-Link Archer T3U 2357:012d)')
    phy = (Path('/sys/class/net') / adapter / 'phy80211').resolve(strict=True).name
    capabilities = command('iw', 'phy', phy, 'info').stdout
    if not re.search(r'^\s*\* monitor\s*$', capabilities, re.M):
        raise RuntimeError('Driver does not advertise monitor mode')
    if Path('/sys/class/net', monitor).exists():
        raise RuntimeError('pwn0 already exists; stop its owner before starting')
    was_up = bool(int((Path('/sys/class/net') / adapter / 'flags').read_text(), 16) & 1)
    managed = command('nmcli', '-g', 'GENERAL.NM-MANAGED', 'device', 'show', adapter, check=False)
    was_managed = managed.returncode == 0 and managed.stdout.strip() == 'yes'
    child = bettercap = mesh = None
    created_monitor = False
    log = mesh_log = None
    try:
        if was_managed:
            command('nmcli', 'device', 'set', adapter, 'managed', 'no')
        command('ip', 'link', 'set', adapter, 'down')
        command('iw', 'dev', adapter, 'interface', 'add', monitor, 'type', 'monitor')
        created_monitor = True
        command('ip', 'link', 'set', monitor, 'up')
        generation = radio_generation(adapter, monitor)
        if generation is None:
            raise RuntimeError('Wi-Fi adapter disappeared during monitor setup')
        logging.info('Using %s / %s / %s in monitor mode', adapter, phy, monitor)
        log = Path('/var/log/gothcwili/bettercap.log').open('a')
        bettercap = subprocess.Popen(['bettercap', '-no-colors', '-iface', monitor,
                                     '-caplet', '/etc/gothcwili/bettercap.cap'],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        import requests
        api = config['bettercap']
        for _ in range(30):
            if bettercap.poll() is not None:
                raise RuntimeError('bettercap exited; inspect /var/log/gothcwili/bettercap.log')
            try:
                response = requests.get('http://127.0.0.1:8081/api/session',
                    auth=(api['username'], api['password']), timeout=1)
                response.raise_for_status()
                break
            except requests.RequestException:
                if STOP.wait(1):
                    return 0
        else:
            raise RuntimeError('bettercap API did not become ready')
        if config['personality'].get('advertise'):
            mesh_log = Path('/var/log/gothcwili/pwngrid.log').open('a')
            mesh = subprocess.Popen(['/usr/local/bin/pwngrid', '-keys', '/var/lib/gothcwili/identity',
                '-address', '127.0.0.1:8666', '-iface', monitor,
                '-peers', '/var/lib/gothcwili/peers',
                '-client-token', '/var/lib/gothcwili/api-enrollment.json'],
                stdin=subprocess.DEVNULL, stdout=mesh_log, stderr=subprocess.STDOUT)
            for _ in range(30):
                if mesh.poll() is not None:
                    raise RuntimeError('pwngrid exited; inspect /var/log/gothcwili/pwngrid.log')
                try:
                    requests.get('http://127.0.0.1:8666/api/v1/mesh/peers', timeout=1).raise_for_status()
                    break
                except requests.RequestException:
                    if STOP.wait(1):
                        return 0
            else:
                raise RuntimeError('Mesh API did not become ready')
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'runtime'), PYTHONUNBUFFERED='1')
        child = subprocess.Popen([sys.executable, str(ROOT / 'runtime/bin/pwnagotchi'),
            '-C', '/etc/gothcwili/default.toml', '-U', str(args.config)], env=env)
        while not STOP.wait(.5):
            if radio_generation(adapter, monitor) != generation:
                raise RuntimeError('Wi-Fi adapter disconnected or re-enumerated; restarting radio services')
            if mesh is not None and mesh.poll() is not None:
                raise RuntimeError('pwngrid exited unexpectedly')
            if bettercap.poll() is not None:
                raise RuntimeError('bettercap exited unexpectedly')
            if child.poll() is not None:
                return 0 if child.returncode in (0, -signal.SIGTERM) else child.returncode
        return 0
    finally:
        stop_child(child)
        stop_child(mesh)
        stop_child(bettercap)
        if mesh_log:
            mesh_log.close()
        if log:
            log.close()
        if created_monitor:
            command('iw', 'dev', monitor, 'del', check=False)
        if was_up:
            command('ip', 'link', 'set', adapter, 'up', check=False)
        if was_managed:
            command('nmcli', 'device', 'set', adapter, 'managed', 'yes', check=False)


if __name__ == '__main__':
    sys.exit(main())
