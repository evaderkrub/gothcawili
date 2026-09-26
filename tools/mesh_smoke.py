"""Two-peer protocol check using mac80211_hwsim only; no physical RF traffic."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import time

import requests
from Cryptodome.PublicKey import RSA

sys.path.insert(0, '/opt/gothcwili/runtime')
from pwnagotchi.mesh.peer import Peer


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError('%s: %s' % (' '.join(args), result.stderr.strip()))
    return result.stdout


def main():
    if Path('/sys/module/mac80211_hwsim').exists():
        raise SystemExit('Refusing to disturb an existing radio simulation')
    children, handles = [], []
    loaded = False
    with tempfile.TemporaryDirectory(prefix='gothcwili-mesh-') as temporary:
        root = Path(temporary)
        try:
            command('modprobe', 'mac80211_hwsim', 'radios=2')
            loaded = True
            interfaces = []
            for interface in Path('/sys/class/net').iterdir():
                device = (interface / 'device').resolve()
                if 'mac80211_hwsim' in str(device):
                    interfaces.append(interface.name)
            if len(interfaces) != 2:
                raise RuntimeError('Expected exactly two simulated interfaces: ' + repr(interfaces))
            monitors = []
            for index, interface in enumerate(sorted(interfaces)):
                command('nmcli', 'device', 'set', interface, 'managed', 'no')
                command('ip', 'link', 'set', interface, 'down')
                command('iw', 'dev', interface, 'set', 'type', 'monitor')
                command('ip', 'link', 'set', interface, 'up')
                command('iw', 'dev', interface, 'set', 'freq', '2412')
                monitor = interface
                monitors.append(monitor)
                folder = root / str(index)
                folder.mkdir()
                key = RSA.generate(2048)
                (folder / 'id_rsa').write_bytes(key.export_key())
                handle = (folder / 'daemon.log').open('w+')
                handles.append(handle)
                child = subprocess.Popen(['/usr/local/bin/pwngrid', '-keys', str(folder),
                    '-iface', monitor, '-address', '127.0.0.1:%d' % (18666 + index),
                    '-peers', str(folder / 'peers'), '-client-token', str(folder / 'token')],
                    stdout=handle, stderr=subprocess.STDOUT)
                children.append(child)
                url = 'http://127.0.0.1:%d/api/v1/mesh' % (18666 + index)
                for _ in range(30):
                    if child.poll() is not None:
                        handle.seek(0)
                        raise RuntimeError(handle.read())
                    try:
                        response = requests.get(url + '/data', timeout=1)
                        response.raise_for_status()
                        break
                    except requests.RequestException:
                        time.sleep(.5)
                else:
                    raise RuntimeError('Mesh API did not start')
                data = response.json()
                data.update(name='SIMULATION-%d' % index, version='1.5.5', face='(o_o)',
                            pwnd_run=0, pwnd_tot=0, uptime=1, epoch=0,
                            policy={'advertise': True, 'deauth': False, 'associate': False})
                requests.post(url + '/data', json=data, timeout=3).raise_for_status()
                requests.get(url + '/true', timeout=3).raise_for_status()
            for channel in (1, 36):
                if channel != 1:
                    for interface in interfaces:
                        command('iw', 'dev', interface, 'set', 'freq', str(5000 + channel * 5))
                seen = [False, False]
                for _ in range(30):
                    for index in range(2):
                        peers = requests.get('http://127.0.0.1:%d/api/v1/mesh/peers' %
                                             (18666 + index), timeout=2).json()
                        seen[index] = any(Peer(peer).name() == 'SIMULATION-%d' % (1-index)
                                          and Peer(peer).last_channel == channel for peer in peers)
                    if all(seen):
                        break
                    time.sleep(1)
                if not all(seen):
                    print(command('iw', 'dev'), flush=True)
                    for index in range(2):
                        peers = requests.get('http://127.0.0.1:%d/api/v1/mesh/peers' % (18666 + index), timeout=2).json()
                        print(json.dumps({'daemon': index, 'peers': peers}), flush=True)
                    from scapy.all import sniff, RadioTap, Dot11
                    packets = sniff(iface=monitors[0], timeout=3, count=10,
                                    lfilter=lambda packet: Dot11 in packet and packet[Dot11].addr2 == 'de:ad:be:ef:de:ad')
                    print('SIGNALING SAMPLES', [packet.summary() + ' flags=' + str(packet[RadioTap].Flags)
                                                 for packet in packets], flush=True)
                    raise RuntimeError('Simulated peer exchange failed: channel=%s seen=%s' % (channel, seen))
                print(json.dumps({'simulation': True, 'channel': channel, 'bidirectional_peer_discovery': True}), flush=True)
        except Exception:
            for handle in handles:
                handle.flush()
                handle.seek(0)
                print(handle.read(), flush=True)
            raise
        finally:
            for child in children:
                child.terminate()
            for child in children:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            for handle in handles:
                handle.close()
            if loaded:
                command('modprobe', '-r', 'mac80211_hwsim')


if __name__ == '__main__':
    main()
