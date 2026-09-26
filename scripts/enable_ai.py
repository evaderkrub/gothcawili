"""Migrate an existing configuration to the CPU AI/mesh port; preserve credentials."""
import os
from pathlib import Path
import shutil
import toml


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo')
    path = Path('/etc/gothcwili/config.toml')
    config = toml.loads(path.read_text())
    backup = path.with_name('config.before-ai.toml')
    if not backup.exists():
        shutil.copy2(path, backup)
        backup.chmod(0o600)
    config.setdefault('main', {}).setdefault('allowed_bssids', [])
    config.setdefault('ai', {}).update(enabled=True, path='/var/lib/gothcwili/brain-a2c.zip',
        channels=[1, 6, 11, 36, 40, 44, 48, 149, 153, 157, 161, 165],
        epochs_per_episode=5, laziness=.1)
    config['personality'].update(advertise=True, associate=False, deauth=False,
        channels=[1, 6, 11, 36, 44, 149, 157])
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(toml.dumps(config))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    print('AI and local mesh enabled. Association and deauthentication remain disabled.')


if __name__ == '__main__':
    main()
