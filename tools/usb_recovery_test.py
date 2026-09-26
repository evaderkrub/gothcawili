"""Briefly unbind/rebind only the attached supported Wi-Fi USB device."""
from pathlib import Path
import json
import subprocess
import sys
import time

sys.path.insert(0, '/opt/gothcwili')
from run import find_adapter


def main():
    adapter = find_adapter()
    if not adapter:
        raise SystemExit('No supported adapter')
    before = int((Path('/sys/class/net') / adapter / 'ifindex').read_text())
    device = (Path('/sys/class/net') / adapter / 'device').resolve()
    usb = next(p for p in [device, *device.parents] if (p / 'idVendor').exists())
    identity = ((usb / 'idVendor').read_text().strip(), (usb / 'idProduct').read_text().strip())
    if identity != ('2357', '012d'):
        raise SystemExit('This bounded hardware test is for the FX0106 Archer T3U')
    node = usb.name
    if (usb / 'driver').resolve() != Path('/sys/bus/usb/drivers/usb'):
        raise SystemExit('Unexpected USB driver binding')
    before_restarts = subprocess.check_output(['systemctl', 'show', 'gothcwili', '-p', 'NRestarts', '--value'], text=True).strip()
    try:
        Path('/sys/bus/usb/drivers/usb/unbind').write_text(node)
        time.sleep(8)
        absent = find_adapter() is None
    finally:
        Path('/sys/bus/usb/drivers/usb/bind').write_text(node)
    if not absent:
        raise RuntimeError('USB interface did not disappear')
    end = time.monotonic() + 90
    while time.monotonic() < end:
        after_adapter = find_adapter()
        if after_adapter and Path('/sys/class/net/pwn0').exists():
            after = int((Path('/sys/class/net') / after_adapter / 'ifindex').read_text())
            state = subprocess.check_output(['systemctl', 'is-active', 'gothcwili'], text=True).strip()
            restarts = subprocess.check_output(['systemctl', 'show', 'gothcwili', '-p', 'NRestarts', '--value'], text=True).strip()
            if after != before and state == 'active' and int(restarts) > int(before_restarts):
                print(json.dumps({'usb_id': ':'.join(identity), 'old_ifindex': before,
                    'new_ifindex': after, 'disappearance_observed': absent,
                    'automatic_restart': True, 'service': state}), flush=True)
                return
        time.sleep(1)
    raise RuntimeError('Adapter/service did not recover within 90 seconds')


if __name__ == '__main__':
    main()
