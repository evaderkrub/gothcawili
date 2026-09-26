"""Fetch the original ARM64 release for comparison; use build_pwngrid.py for deployment."""
import hashlib
import io
from pathlib import Path
import urllib.request
import zipfile

URL = 'https://github.com/jayofelony/pwngrid/releases/download/v1.11.6/pwngrid-1.11.6-aarch64.zip'
SHA256 = '6795afedc3e7ea49c04b5e9f12b778db165db00a29d93606b77dd1f8124dff17'


def main():
    data = urllib.request.urlopen(URL, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('pwngrid release checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        candidates = [name for name in archive.namelist() if Path(name).name == 'pwngrid']
        if len(candidates) != 1:
            raise RuntimeError('Unexpected release layout')
        output = Path('dist/pwngrid/pwngrid')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(archive.read(candidates[0]))
        output.chmod(0o755)
        print(output)


if __name__ == '__main__':
    main()
