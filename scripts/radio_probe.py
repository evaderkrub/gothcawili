"""Bounded passive reception check. Stop gothcwili before running as root."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import find_adapter, command


def main():
    from scapy.all import PcapReader, RadioTap
    adapter = find_adapter()
    if not adapter:
        raise SystemExit('Supported adapter not found')
    monitor = 'gothprobe'
    if Path('/sys/class/net/pwn0').exists() or Path('/sys/class/net', monitor).exists():
        raise SystemExit('Stop the radio owner before probing')
    managed = command('nmcli', '-g', 'GENERAL.NM-MANAGED', 'device', 'show', adapter, check=False).stdout.strip() == 'yes'
    was_up = bool(int((Path('/sys/class/net') / adapter / 'flags').read_text(), 16) & 1)
    created = False
    try:
        if managed:
            command('nmcli', 'device', 'set', adapter, 'managed', 'no')
        command('ip', 'link', 'set', adapter, 'down')
        command('iw', 'dev', adapter, 'interface', 'add', monitor, 'type', 'monitor')
        created = True
        command('ip', 'link', 'set', monitor, 'up')
        for channel in (1, 6, 11, 36, 44, 149, 157):
            command('iw', 'dev', monitor, 'set', 'channel', str(channel))
            with tempfile.TemporaryDirectory() as folder:
                pcap = Path(folder) / 'probe.pcap'
                result = subprocess.run(['timeout', '-s', 'INT', '6', 'tcpdump', '-i', monitor,
                    '-s', '256', '-c', '100', '-w', str(pcap), 'type mgt subtype beacon'],
                    capture_output=True, text=True, timeout=10)
                if result.returncode not in (0, 124):
                    raise RuntimeError(result.stderr)
                count = 0
                frequencies = set()
                with PcapReader(str(pcap)) as packets:
                    for packet in packets:
                        count += 1
                        if RadioTap in packet and packet[RadioTap].ChannelFrequency:
                            frequencies.add(int(packet[RadioTap].ChannelFrequency))
                print(json.dumps({'channel': channel, 'beacons': count,
                                  'frequencies_mhz': sorted(frequencies)}), flush=True)
    finally:
        if created:
            command('iw', 'dev', monitor, 'del', check=False)
        if was_up:
            command('ip', 'link', 'set', adapter, 'up', check=False)
        if managed:
            command('nmcli', 'device', 'set', adapter, 'managed', 'yes', check=False)


if __name__ == '__main__':
    main()
