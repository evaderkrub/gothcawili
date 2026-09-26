"""Create a deployable tarball without caches or local credentials."""
from pathlib import Path
import tarfile

from prepare_runtime import prepare

ROOT = Path(__file__).resolve().parents[1]
prepare(ROOT / '.upstream/pwnagotchi', ROOT / 'dist/runtime')
with tarfile.open(ROOT / 'dist/gothcwili.tar.gz', 'w:gz') as tar:
    for directory in ('config', 'plugins', 'scripts', 'systemd', 'dist/runtime'):
        for path in (ROOT / directory).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            name = path.relative_to(ROOT).as_posix().removeprefix('dist/')
            info = tar.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            info.mtime = 0
            with path.open('rb') as handle:
                tar.addfile(info, handle)
    info = tar.gettarinfo(str(ROOT / 'run.py'), arcname='run.py')
    info.mtime = 0
    with (ROOT / 'run.py').open('rb') as handle:
        tar.addfile(info, handle)
print(ROOT / 'dist/gothcwili.tar.gz')
