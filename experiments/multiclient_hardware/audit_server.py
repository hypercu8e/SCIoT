"""Run the unchanged HTTP v2 service with an archived copy of each inference.

Archiving adds measured server overhead. Raw activations stay in ignored results.
"""
import argparse
import json
import os
from pathlib import Path
import struct


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--port', type=int, default=8000)
    a = p.parse_args()
    for k, v in dict(CUDA_VISIBLE_DEVICES='-1', TF_CPP_MIN_LOG_LEVEL='3',
                     TF_NUM_INTRAOP_THREADS='1', TF_NUM_INTEROP_THREADS='1').items():
        os.environ.setdefault(k, v)
    from server.multiclient.engine import Suffix
    from server.multiclient.http import create_app
    import uvicorn
    artifacts = Path('experiments/esp32_representation_benchmark/artifacts')
    manifest = json.loads((artifacts/'manifest.json').read_text())
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output/'manifest.json').write_text(json.dumps(dict(model=manifest, workers=1,
        threads=1, audit_archive=True, port=a.port), indent=2)+'\n')
    with (a.output/'server.jsonl').open('x') as metrics, (a.output/'inference.bin').open('xb') as archive:
        class ArchivedSuffix:
            def __init__(self):
                self.engine = Suffix(artifacts, 1)

            def __call__(self, body):
                reply = self.engine(body)
                archive.write(struct.pack('<II', len(body), len(reply)))
                archive.write(body)
                archive.write(reply)
                archive.flush()
                return reply

        app = create_app(ArchivedSuffix, manifest['models']['int8']['prefix']['sha256'],
                         metrics=metrics, inference_workers=1)
        uvicorn.run(app, host='0.0.0.0', port=a.port, workers=1, access_log=False)


if __name__ == '__main__':
    main()
