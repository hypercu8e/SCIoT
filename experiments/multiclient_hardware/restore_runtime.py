"""Restore the frozen public model/input assets after a Git-only handoff.

Never overwrite different local assets; validate all members before copying.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check',action='store_true')
    p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args()
    expected=json.loads((HERE/'frozen-runtime-sha256.json').read_text())
    payload={}
    with tarfile.open(HERE/'frozen-runtime.tar.gz','r:gz') as archive:
        assert set(archive.getnames())==set(expected)
        for name,digest in expected.items():
            member=archive.getmember(name)
            assert member.isfile() and member.size<2_000_000
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            data=archive.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest()==digest
            target=a.root/name
            if target.exists() and target.read_bytes()!=data:
                raise RuntimeError(f'Local asset differs; preserve and inspect before replacing: {target}')
            payload[name]=data
    if not a.check:
        for name,data in payload.items():
            target=a.root/name
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(data)
    print(f'Frozen runtime verified: {len(payload)} files; '+('check only' if a.check else 'missing files restored'))


if __name__=='__main__':
    main()
