"""Restore hash-pinned public sources after a Git-only laptop handoff.

Validate the complete archive and all existing files before writing any missing
file. Never overwrite local modifications. No firmware or credentials included.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def restore(root=ROOT, check=False):
    manifest = json.loads((HERE/'frozen-components-sha256.json').read_text())
    blob = (HERE/'frozen-components.tar.gz').read_bytes()
    if hashlib.sha256(blob).hexdigest() != manifest['archive_sha256']:
        raise ValueError('Component archive hash mismatch')
    payload = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        if archive.getnames() != sorted(manifest['files']):
            raise ValueError('Component archive inventory mismatch')
        for member in archive:
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts:
                raise ValueError('Invalid archive member')
            data = archive.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != manifest['files'][member.name]:
                raise ValueError('Component source hash mismatch')
            target = root/path
            if target.exists() and (not target.is_file() or target.read_bytes() != data):
                raise ValueError(f'Local source differs; preserve before replacing: {path}')
            payload[path] = data
    if not check:
        for path, data in payload.items():
            target = root/path
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    print(f'Frozen components verified: {len(payload)} files; '+('check only' if check else 'missing files restored'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    restore(args.root, args.check)
