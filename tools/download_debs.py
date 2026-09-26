"""Download apt --print-uris output on the PC for an offline CM0 install."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
import sys
import urllib.request


def main():
    source = Path(sys.argv[1]).read_text(encoding='utf-8-sig')
    output = Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    packages = re.findall(r"'(https?://[^']+)' ([^ ]+) (\d+) MD5Sum:([0-9a-f]+)", source)
    urls = re.findall(r"'(https?://[^']+)' ([^ ]+) (\d+)", source)
    if len(urls) != len(packages):
        raise SystemExit('Some packages lack an MD5Sum. Fetch their apt-cache show metadata and verify SHA256; do not silently omit them.')
    if not packages:
        raise SystemExit('No apt package URLs found')
    def download(package):
        url, filename, size, checksum = package
        path = output / filename
        if path.name != filename:
            raise ValueError('Invalid package filename')
        if not path.exists():
            with urllib.request.urlopen(url.replace('http:', 'https:', 1), timeout=60) as response:
                data = response.read()
            if len(data) != int(size) or hashlib.md5(data).hexdigest() != checksum:
                raise ValueError('Package checksum mismatch: ' + filename)
            path.write_bytes(data)
        data = path.read_bytes()
        if len(data) != int(size) or hashlib.md5(data).hexdigest() != checksum:
            raise ValueError('Cached package checksum mismatch: ' + filename)
        return filename
    with ThreadPoolExecutor(max_workers=6) as pool:
        for filename in pool.map(download, packages):
            print(filename, flush=True)


if __name__ == '__main__':
    main()
