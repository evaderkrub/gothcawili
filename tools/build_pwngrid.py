"""Build the pinned mesh daemon with FreeWili radiotap compatibility fixes.

Requires Go >=1.25, a C compiler and libpcap development headers. For cross
compilation set GOOS, GOARCH, CC, CGO_CFLAGS and CGO_LDFLAGS as usual.
"""
import argparse
from pathlib import Path
import shutil
import subprocess

UPSTREAM = '913a03fe53d9ae69e70ff070c9d35c6ada071e9c'
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / '.upstream/pwngrid')
    parser.add_argument('--go', default='go')
    args = parser.parse_args()
    revision = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != UPSTREAM:
        raise RuntimeError('Review mesh patch for upstream ' + revision)
    target = ROOT / 'dist/pwngrid-build'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive = subprocess.Popen(['git', '-C', str(args.source), 'archive', UPSTREAM], stdout=subprocess.PIPE)
    subprocess.run(['tar', '-x', '-C', str(target)], stdin=archive.stdout, check=True)
    archive.stdout.close()
    if archive.wait():
        raise RuntimeError('Source export failed')
    subprocess.run(['patch', '-p1', '-i', str(ROOT / 'compat/pwngrid.patch')], cwd=target, check=True)
    output = ROOT / 'dist/pwngrid-fixed/pwngrid'
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.go, 'build', '-buildvcs=false', '-trimpath', '-ldflags=-s -w', '-o', str(output), './cmd/pwngrid'], cwd=target, check=True)
    print(output)


if __name__ == '__main__':
    main()
