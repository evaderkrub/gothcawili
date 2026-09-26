"""Install the staged runtime on CM0; preserve existing user configuration."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run: sudo python3 /opt/gothcwili/scripts/install.py')
    # Windows-created archives can carry broad mode bits. Runtime source is
    # root-owned; live state and credentials are kept outside the source tree.
    for path in ROOT.rglob('*'):
        if not path.is_symlink():
            os.chown(path, 0, 0)
            path.chmod(0o755 if path.is_dir() else 0o644)
    for name in ('/etc/gothcwili', '/var/log/gothcwili', '/var/lib/gothcwili/handshakes',
                 '/var/lib/gothcwili/identity'):
        Path(name).mkdir(parents=True, exist_ok=True)
    config_path = Path('/etc/gothcwili/config.toml')
    if not config_path.exists():
        text = (ROOT / 'config/config.toml').read_text()
        config_path.write_text(text.replace('GENERATE_ON_INSTALL', secrets.token_hex(24)))
        config_path.chmod(0o600)
    config = tomllib.loads(config_path.read_text())
    if not Path('/opt/gothcwili-venv/bin/python').exists():
        raise RuntimeError('Install dependencies first: /opt/gothcwili-venv is missing')
    if config.get('personality', {}).get('advertise') and not Path('/usr/local/bin/pwngrid').exists():
        raise RuntimeError('Install the pinned ARM64 pwngrid binary first')
    api = config['bettercap']
    if not all(c.isalnum() or c in '_-' for c in api['username'] + api['password']):
        raise RuntimeError('Use letters, digits, underscore, or hyphen in bettercap credentials')
    caplet = Path('/etc/gothcwili/bettercap.cap')
    caplet.write_text('set api.rest.address 127.0.0.1\nset api.rest.port 8081\n'
        'set api.rest.username %s\nset api.rest.password %s\napi.rest on\n' %
        (api['username'], api['password']))
    caplet.chmod(0o600)
    # Generate the upstream identity locally: no pwngrid daemon needed for non-mesh use.
    from Cryptodome.PublicKey import RSA
    keydir = Path('/var/lib/gothcwili/identity')
    private = keydir / 'id_rsa'
    public = keydir / 'id_rsa.pub'
    if not private.exists():
        private.write_bytes(RSA.generate(2048).export_key())
        private.chmod(0o600)
    if not public.exists():
        public.write_bytes(RSA.import_key(private.read_bytes()).public_key().export_key())
    shutil.copyfile(ROOT / 'systemd/gothcwili.service', '/etc/systemd/system/gothcwili.service')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    print('Installed. Start with sudo systemctl start gothcwili')


if __name__ == '__main__':
    main()
