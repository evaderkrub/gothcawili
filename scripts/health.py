"""Print a credential-free snapshot of this CM0 installation (run with sudo)."""
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
import tomllib
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import find_adapter


def main():
    config = tomllib.loads(Path('/etc/gothcwili/config.toml').read_text())
    result = {'adapter': find_adapter(), 'ai_enabled': config['ai']['enabled'],
        'mesh_enabled': config['personality']['advertise'],
        'associate': config['personality']['associate'], 'deauth': config['personality']['deauth'],
        'authorized_target_count': len(config['main'].get('allowed_bssids', [])), 'versions': {}}
    for package in ('torch', 'stable-baselines3', 'gymnasium'):
        try:
            result['versions'][package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            result['versions'][package] = 'not installed'
    result['service'] = subprocess.check_output(['systemctl', 'show', 'gothcwili',
        '-p', 'ActiveState', '-p', 'SubState', '-p', 'UnitFileState', '-p', 'NRestarts',
        '-p', 'MemoryCurrent', '-p', 'MemoryPeak'], text=True).strip().splitlines()
    path = Path(config['ai']['path'])
    result['checkpoint_exists'] = path.is_file()
    if path.is_file():
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read('data'))
        result['checkpoint'] = {key: data.get(key) for key in ('num_timesteps', '_n_updates')}
    result['usb'] = subprocess.check_output(['lsusb'], text=True).strip().splitlines()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
