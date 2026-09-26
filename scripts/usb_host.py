"""Configure CM0 USB host mode, retaining the original boot files for rollback."""
import argparse
import os
from pathlib import Path
import shutil
import re


def host_config(text):
    text = text.replace('dtoverlay=dwc2,dr_mode=peripheral', 'dtoverlay=dwc2,dr_mode=host')
    text = text.replace('gpio=2=op,dl', 'gpio=2=op,dh')
    if 'dtoverlay=dwc2,dr_mode=host' not in text or 'gpio=2=op,dh' not in text or 'gpio=3=op,dh' not in text:
        raise ValueError('Unrecognized USB mux configuration; review boot config before changing it')
    return text


def gadget_config(text):
    # Validate the known mux before editing; retain later UART/firmware changes.
    return host_config(text).replace('dr_mode=host', 'dr_mode=peripheral').replace(
        'gpio=2=op,dh', 'gpio=2=op,dl')


def usb_cmdline(text, gadget=False):
    pattern = r'(?<!\S)modules-load=dwc2(?:,g_serial)?(?=\s|$)'
    replacement = 'modules-load=dwc2' + (',g_serial' if gadget else '')
    result, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise ValueError('Unrecognized USB module boot setting')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo')
    if 'Compute Module 0' not in Path('/proc/device-tree/model').read_text():
        raise SystemExit('This configuration is for FreeWili 2 with Raspberry Pi CM0')
    root = Path('/boot/firmware')
    backup = root / 'gothcwili-backup'
    names = ('config.txt', 'cmdline.txt')
    convert = gadget_config if args.restore else host_config
    config = convert((root / 'config.txt').read_text())
    cmdline = usb_cmdline((root / 'cmdline.txt').read_text(), args.restore)
    backup.mkdir(exist_ok=True)
    for name in names:
        if not (backup / name).exists():
            shutil.copy2(root / name, backup / name)
    (root / 'config.txt').write_text(config)
    (root / 'cmdline.txt').write_text(cmdline)
    os.sync()
    if args.restore:
        print('USB gadget configured; other boot settings retained. Reboot CM0 to apply.')
        return
    print('USB host configured: dwc2 host, GPIO2=1, GPIO3=1. Reboot CM0 to apply.')
    print('Access CM0 through fwcom Main connection after reboot.')


if __name__ == '__main__':
    main()
