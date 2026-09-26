"""Exercise Pwnagotchi/bettercap using three mac80211_hwsim radios only.

The physical adapter is never selected. Stop gothcwili first. Requires hostapd,
wpa_supplicant and the deployed Python runtime; no production config is changed.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, '/opt/gothcwili/runtime')
from pwnagotchi.agent import Agent
from pwnagotchi.bettercap import Client
from scapy.all import AsyncSniffer, Dot11, EAPOL, PcapReader, Ether, Raw, sendp


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(' '.join(args[:3]) + ': ' + result.stderr.strip())
    return result.stdout


def until(check, seconds=25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
        except (ConnectionError, OSError):
            pass
        time.sleep(.4)
    raise RuntimeError('Timed out waiting for virtual radio state')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hostapd', default='/home/pi/gothcwili-lab/usr/sbin/hostapd')
    args = parser.parse_args()
    if Path('/sys/module/mac80211_hwsim').exists():
        raise SystemExit('Existing radio simulation must be stopped first')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'gothcwili']).returncode == 0:
        raise SystemExit('Stop gothcwili first')
    loaded = False
    try:
        command('modprobe', 'mac80211_hwsim', 'radios=3')
        loaded = True
        radios = sorted(p.name for p in Path('/sys/class/net').iterdir()
                        if 'mac80211_hwsim' in str((p / 'device').resolve()))
        if len(radios) != 3:
            raise RuntimeError('Expected three virtual radios')
        apif, staif, mon = radios
        for interface in radios:
            command('nmcli', 'device', 'set', interface, 'managed', 'no')
            command('ip', 'link', 'set', interface, 'down')
        command('iw', 'dev', mon, 'set', 'type', 'monitor')
        command('ip', 'link', 'set', mon, 'up')
        for channel in (1, 36):
            children, logs, sniffer = [], [], None
            with tempfile.TemporaryDirectory(prefix='gothcwili-radio-lab-') as directory:
                root = Path(directory)
                def spawn(argv, name):
                    handle = (root / (name + '.log')).open('w+')
                    logs.append(handle)
                    child = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT)
                    children.append(child)
                    return child
                try:
                    command('iw', 'dev', mon, 'set', 'channel', str(channel))
                    ssid = 'GOTHCWILI-HWSIM-' + str(channel)
                    (root / 'ap.conf').write_text('interface=%s\ndriver=nl80211\nssid=%s\ncountry_code=US\nhw_mode=%s\nchannel=%d\nwpa=2\nwpa_passphrase=virtual-radio-test-only\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n' % (apif, ssid, 'g' if channel == 1 else 'a', channel))
                    ap = spawn([args.hostapd, str(root / 'ap.conf')], 'ap')
                    time.sleep(2)
                    if ap.poll() is not None:
                        raise RuntimeError('Virtual AP failed to start')
                    bssid = (Path('/sys/class/net') / apif / 'address').read_text().strip()
                    station = (Path('/sys/class/net') / staif / 'address').read_text().strip()
                    password = secrets.token_hex(12)
                    captures = root / 'handshakes'
                    captures.mkdir()
                    (root / 'lab.cap').write_text('set api.rest.address 127.0.0.1\nset api.rest.port 18081\nset api.rest.username lab\nset api.rest.password %s\napi.rest on\nset wifi.handshakes.file %s\nset wifi.handshakes.aggregate false\nset wifi.deauth.acquired true\nset wifi.assoc.acquired true\nwifi.recon on\nwifi.recon.channel %d\n' % (password, captures, channel))
                    spawn(['bettercap', '-no-colors', '-iface', mon, '-caplet', str(root / 'lab.cap')], 'bettercap')
                    agent = Agent.__new__(Agent)
                    Client.__init__(agent, '127.0.0.1', 'http', 18081, 'lab', password)
                    import requests
                    def ready():
                        try:
                            return agent.session().get('wifi', {}).get('aps', [])
                        except requests.RequestException:
                            return None
                    until(ready)
                    sniffer = AsyncSniffer(iface=mon, store=True)
                    sniffer.start()
                    control = root / 'control'
                    (root / 'sta.conf').write_text('ctrl_interface=%s\nnetwork={\n ssid="%s"\n psk="virtual-radio-test-only"\n key_mgmt=WPA-PSK\n scan_freq=%d\n}\n' % (control, ssid, 2412 if channel == 1 else 5180))
                    spawn(['wpa_supplicant', '-Dnl80211', '-i', staif, '-c', str(root / 'sta.conf')], 'station')
                    until(lambda: (control / staif).exists() and 'wpa_state=COMPLETED' in command('wpa_cli', '-p', str(control), '-i', staif, 'status'))
                    sendp(Ether(dst=bssid, type=0x88b5) / Raw(b'GOTHCWILI virtual test'), iface=staif, count=3, verbose=False)
                    apdata = until(lambda: next((a for a in agent.session()['wifi']['aps'] if a['mac'].lower() == bssid and a['clients']), None))
                    stadata = next(s for s in apdata['clients'] if s['mac'].lower() == station)
                    events = []
                    agent._config = {'main': {'allowed_bssids': [bssid]}, 'personality': {'associate': True, 'deauth': True}}
                    agent.is_stale = lambda: False
                    agent._should_interact = lambda _: True
                    agent._view = SimpleNamespace(on_assoc=lambda _: None, on_deauth=lambda _: None, on_normal=lambda: None)
                    agent._epoch = SimpleNamespace(track=lambda **kw: events.append(kw))
                    def fail(_, error):
                        raise error
                    agent._on_error = fail
                    denied = dict(apdata, mac='02:ff:ff:ff:ff:fe')
                    agent.associate(denied)
                    agent.deauth(denied, stadata)
                    assert not events, 'Out-of-scope operation was issued'
                    agent.associate(apdata)
                    agent.deauth(apdata, stadata)
                    assert any(e.get('assoc') for e in events) and any(e.get('deauth') for e in events)
                    time.sleep(4)
                    packets = sniffer.stop()
                    sniffer = None
                    keys = sum(EAPOL in p for p in packets)
                    deauths = sum(Dot11 in p and p[Dot11].type == 0 and p[Dot11].subtype == 12 and p[Dot11].addr3 == bssid for p in packets)
                    files = list(captures.glob('*.pcap'))
                    saved_keys = 0
                    for path in files:
                        with PcapReader(str(path)) as reader:
                            saved_keys += sum(EAPOL in p for p in reader)
                    assert keys >= 4 and saved_keys >= 4 and deauths > 0, (keys, saved_keys, deauths)
                    print(json.dumps({'simulation': True, 'physical_rf': False, 'channel': channel, 'association_command': True, 'deauthentication_frames': deauths, 'eapol_frames': keys, 'saved_eapol_frames': saved_keys, 'capture_files': len(files), 'outside_scope_blocked': True}), flush=True)
                except Exception:
                    for handle in logs:
                        handle.flush(); handle.seek(0)
                        # Lab-only SSID/keys; omit generated HTTP API password.
                        print(handle.read().replace(password if 'password' in locals() else 'unused', '<redacted>'), flush=True)
                    raise
                finally:
                    if sniffer and sniffer.running:
                        sniffer.stop()
                    for child in reversed(children):
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill(); child.wait()
                    for handle in logs:
                        handle.close()
                    command('ip', 'link', 'set', apif, 'down')
                    command('ip', 'link', 'set', staif, 'down')
    finally:
        if loaded:
            command('modprobe', '-r', 'mac80211_hwsim')


if __name__ == '__main__':
    main()
