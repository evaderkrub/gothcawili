"""Bounded association test against this project's host-owned GOTHCWILI-LAB AP.

Run on CM0 with gothcwili stopped. Does not change production configuration.
The target is fixed to the locally created AP; --client performs one bounded
deauthentication call against an explicitly identified client of that AP.
"""
import argparse
import json
from pathlib import Path
import secrets
import re
import os
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path[:0] = ['/opt/gothcwili', '/opt/gothcwili/runtime']
from run import command, find_adapter, stop_child
from pwnagotchi.agent import Agent
from pwnagotchi.bettercap import Client
from scapy.all import Dot11, Dot11Auth, Dot11AssoResp, EAPOL, PcapReader, wrpcap
import requests

BSSID = '02:47:43:57:4c:01'
SSID = 'GOTHCWILI-LAB'


def handshake_summary(packets, station):
    messages = {str(i): set() for i in range(1, 5)}
    for p in packets:
        if EAPOL not in p or Dot11 not in p or p[EAPOL].type != 3:
            continue
        src, dst = p[Dot11].addr2, p[Dot11].addr1
        if {src, dst} != {BSSID, station}:
            continue
        data = bytes(p[EAPOL].payload)
        if len(data) < 13:
            continue
        info = int.from_bytes(data[1:3], 'big')
        if not info & 8:  # Pairwise key, not group rekeying.
            continue
        ack, mic, secure = bool(info & 128), bool(info & 256), bool(info & 512)
        message = 1 if ack and not mic else 3 if ack and mic else 4 if mic and secure else 2 if mic else None
        if not message or (message in (1, 3)) != (src == BSSID):
            continue
        messages[str(message)].add(int.from_bytes(data[5:13], 'big'))
    first = messages['1'] & messages['2']
    second = messages['3'] & messages['4']
    return {'messages': {k: sorted(v) for k, v in messages.items()},
            'complete_exchange': any(b == a + 1 for a in first for b in second)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', type=int, choices=(6, 36), default=6)
    parser.add_argument('--client', type=str.lower, help='Exact MAC of the owned phone connected to the fixed host AP')
    parser.add_argument('--observe-reconnect', action='store_true', help='Capture a host-controlled AP restart without sending deauthentication')
    args = parser.parse_args()
    if args.observe_reconnect and not args.client:
        raise SystemExit('--observe-reconnect requires --client')
    if args.client and (not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', args.client) or int(args.client[:2], 16) & 1 or args.client == BSSID):
        raise SystemExit('Expected an exact unicast client MAC')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'gothcwili']).returncode == 0:
        raise SystemExit('Stop gothcwili first')
    adapter = find_adapter()
    if not adapter or Path('/sys/class/net/gothlab').exists():
        raise SystemExit('Expected one available supported adapter')
    managed = command('nmcli', '-g', 'GENERAL.NM-MANAGED', 'device', 'show', adapter).stdout.strip() == 'yes'
    was_up = bool(int((Path('/sys/class/net') / adapter / 'flags').read_text(), 16) & 1)
    created = False
    child = sniffer = None
    try:
        command('nmcli', 'device', 'set', adapter, 'managed', 'no')
        command('ip', 'link', 'set', adapter, 'down')
        command('iw', 'dev', adapter, 'interface', 'add', 'gothlab', 'type', 'monitor')
        created = True
        command('ip', 'link', 'set', 'gothlab', 'up')
        command('iw', 'dev', 'gothlab', 'set', 'channel', str(args.channel))
        with tempfile.TemporaryDirectory(prefix='gothcwili-physical-lab-') as directory:
            root = Path(directory)
            password = secrets.token_hex(12)
            caplet = root / 'lab.cap'
            caplet.write_text('set api.rest.address 127.0.0.1\nset api.rest.port 18081\nset api.rest.username lab\nset api.rest.password %s\napi.rest on\nset wifi.handshakes.file %s\nset wifi.deauth.acquired true\nset wifi.txpower 15\nwifi.recon on\nwifi.recon.channel %d\n' % (password, root / 'handshakes.pcap', args.channel))
            with (root / 'bettercap.log').open('w+') as log:
                child = subprocess.Popen(['bettercap', '-no-colors', '-iface', 'gothlab', '-caplet', str(caplet)], stdout=log, stderr=subprocess.STDOUT)
                agent = Agent.__new__(Agent)
                Client.__init__(agent, '127.0.0.1', 'http', 18081, 'lab', password)
                ap = None
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try:
                        ap = next((a for a in agent.session()['wifi']['aps'] if a['mac'].lower() == BSSID and a['hostname'] == SSID and a['channel'] == args.channel), None)
                        if ap:
                            break
                    except (requests.RequestException, KeyError):
                        pass
                    time.sleep(.5)
                if not ap:
                    log.flush(); log.seek(0)
                    print(log.read().replace(password, '<redacted>'), flush=True)
                    raise RuntimeError('Host-owned AP not observed; no active command sent')
                agent._config = {'main': {'allowed_bssids': [BSSID]}, 'personality': {'associate': True, 'deauth': bool(args.client)}}
                agent.is_stale = lambda: False
                agent._should_interact = lambda _: True
                agent._view = SimpleNamespace(on_assoc=lambda _: None, on_deauth=lambda _: None, on_normal=lambda: None)
                events = []
                agent._epoch = SimpleNamespace(track=lambda **kw: events.append(kw))
                def fail(_, error):
                    raise error
                agent._on_error = fail
                radio_path = root / 'radio-input.pcap'
                sniffer = subprocess.Popen(['tcpdump', '-U', '-s', '0', '-B', '4096',
                    '-i', 'gothlab', '-w', str(radio_path), 'wlan', 'addr3', BSSID],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 10
                while not radio_path.exists() or radio_path.stat().st_size < 24:
                    if sniffer.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Radio capture did not become ready')
                    time.sleep(.1)
                if args.client:
                    station = None
                    deadline = time.monotonic() + 20
                    while not args.observe_reconnect and time.monotonic() < deadline:
                        current = next((a for a in agent.session()['wifi']['aps'] if a['mac'].lower() == BSSID), None)
                        station = next((c for c in (current or {}).get('clients', []) if c['mac'].lower() == args.client), None)
                        if station:
                            break
                        time.sleep(.5)
                    if not args.observe_reconnect and not station:
                        raise RuntimeError('Specified phone was not observed on our AP; no deauthentication sent')
                    if args.observe_reconnect:
                        Path('/run/gothcwili-lab-ready').write_text(json.dumps({'pid': os.getpid(), 'client': args.client, 'capture_started': time.time()}))
                        time.sleep(120)
                    else:
                        agent.deauth(current, station)
                        time.sleep(20)
                else:
                    agent.associate(ap)
                    time.sleep(8)
                stop_child(sniffer)
                sniffer = None
                with PcapReader(str(radio_path)) as reader:
                    packets = list(reader)
                recipient = args.client or Path('/sys/class/net/gothlab/address').read_text().strip()
                from_ap = [p for p in packets if Dot11 in p and p[Dot11].addr2 == BSSID and p[Dot11].addr1 == recipient]
                auth = sum(Dot11Auth in p and p[Dot11Auth].seqnum == 2 and p[Dot11Auth].status == 0 for p in from_ap)
                assoc = sum(Dot11AssoResp in p and p[Dot11AssoResp].status == 0 for p in from_ap)
                eapol = sum(EAPOL in p for p in from_ap)
                result = {'physical_rf': True, 'ssid': SSID, 'bssid': BSSID, 'channel': args.channel,
                    'ap_detected': True, 'association_command': any(e.get('assoc') for e in events),
                    'ap_authentication_responses': auth, 'ap_association_responses': assoc,
                    'eapol_from_ap': eapol, 'injection_response_verified': bool(events) and bool(auth or assoc or eapol),
                    'deauthentication_tested': False, 'full_handshake_tested': False}
                if args.client:
                    selected = [p for p in packets if args.client in (p[Dot11].addr1, p[Dot11].addr2)]
                    saved = []
                    for path in root.rglob('*.pcap'):
                        if path == radio_path:
                            continue
                        with PcapReader(str(path)) as reader:
                            saved.extend(p for p in reader if Dot11 in p and
                                         {p[Dot11].addr1, p[Dot11].addr2} == {BSSID, args.client})
                    capture_dir = Path('/var/lib/gothcwili/lab') / ('host-ap-%d-%d' % (args.channel, time.time_ns()))
                    capture_dir.mkdir(parents=True, mode=0o700)
                    os.chmod(capture_dir.parent, 0o700)
                    wrpcap(str(capture_dir / 'radio.pcap'), selected)
                    if saved:
                        wrpcap(str(capture_dir / 'bettercap.pcap'), saved)
                    radio_handshake = handshake_summary(selected, args.client)
                    saved_handshake = handshake_summary(saved, args.client)
                    result.update({'client': args.client,
                        'deauthentication_tested': any(e.get('deauth') for e in events),
                        'deauthentication_frames': sum(p[Dot11].type == 0 and p[Dot11].subtype == 12 for p in selected),
                        'radio_handshake': radio_handshake, 'saved_handshake': saved_handshake,
                        'full_handshake_tested': True, 'host_controlled_reconnect': args.observe_reconnect,
                        'full_handshake_verified': radio_handshake['complete_exchange'] and saved_handshake['complete_exchange'],
                        'capture_directory': str(capture_dir)})
                print(json.dumps(result), flush=True)
                if args.client and not result['full_handshake_verified']:
                    raise RuntimeError('Full reconnect handshake was not observed and saved')
                if not args.observe_reconnect and not result['injection_response_verified']:
                    raise RuntimeError('Command accepted but no AP response observed; injection remains unverified')
    finally:
        if args.observe_reconnect:
            Path('/run/gothcwili-lab-ready').unlink(missing_ok=True)
        stop_child(sniffer)
        stop_child(child)
        if created:
            command('iw', 'dev', 'gothlab', 'del', check=False)
        if was_up:
            command('ip', 'link', 'set', adapter, 'up', check=False)
        if managed:
            command('nmcli', 'device', 'set', adapter, 'managed', 'yes', check=False)


if __name__ == '__main__':
    main()
