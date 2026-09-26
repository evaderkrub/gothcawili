"""Install the CM0 clock settings paired with dist/firmware/FW2Main.uf2.

Use only with the 20 MHz FPGA recovery build. Original files are retained for
rollback; apply them together with the original MAIN firmware when reverting.
"""
import os
from pathlib import Path
import re
import shutil


def update(text, key, value):
    pattern = r'(?m)^' + re.escape(key) + r'=.*$'
    if re.search(pattern, text):
        return re.sub(pattern, key + '=' + str(value), text)
    return text.rstrip() + '\n' + key + '=' + str(value) + '\n'


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root on CM0')
    if 'Compute Module 0' not in Path('/proc/device-tree/model').read_text():
        raise SystemExit('Expected FreeWili CM0')
    config = Path('/boot/firmware/config.txt')
    environment = Path('/etc/environment')
    for path in (config, environment):
        backup = path.with_name(path.name + '.before-gothcwili-clock')
        if not backup.exists():
            shutil.copy2(path, backup)
    config.write_text(update(config.read_text(), 'init_uart_clock', 80000000))
    text = update(environment.read_text(), 'FWCM0_BAUD', 5000000)
    environment.write_text(update(text, 'FWCM0_SPI_HZ', 4000000))
    os.sync()
    print('CM0 configured for 20 MHz MAIN/FPGA build: UART 5 Mbaud, SPI 4 MHz. Reboot required.')


if __name__ == '__main__':
    main()
