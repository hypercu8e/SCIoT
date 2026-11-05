"""Run with python -m server.multiclient.run (PYTHONPATH=src)."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http-v2', action='store_true')
    parser.add_argument('--artifacts', type=Path, default=Path('experiments/esp32_representation_benchmark/artifacts'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--max-clients', type=int, default=32)
    parser.add_argument('--queue-size', type=int, default=8)
    parser.add_argument('--max-receiving', type=int, default=8)
    parser.add_argument('--timeout', type=float, default=10.)
    parser.add_argument('--idle', type=float, default=60.)
    parser.add_argument('--inference-workers', type=int, default=1)
    parser.add_argument('--inference-threads', type=int, default=1)
    args = parser.parse_args()
    if min(args.inference_workers, args.inference_threads) < 1:
        parser.error('Inference workers and threads must be positive')
    for key, value in {'CUDA_VISIBLE_DEVICES': '-1', 'TF_CPP_MIN_LOG_LEVEL': '3',
                       'TF_NUM_INTRAOP_THREADS': '1', 'TF_NUM_INTEROP_THREADS': '1'}.items():
        os.environ.setdefault(key, value)
    from .engine import Suffix
    from .http import create_app
    import uvicorn
    manifest = json.loads((args.artifacts/'manifest.json').read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'manifest.json').write_text(json.dumps({'configuration': vars(args),
        'model_manifest': manifest}, default=str, indent=2)+'\n')
    with (args.output/'server.jsonl').open('x') as metrics:
        app = create_app(lambda: Suffix(args.artifacts, args.inference_threads), manifest['models']['int8']['prefix']['sha256'],
                         max_clients=args.max_clients, queue_size=args.queue_size,
                         max_receiving=args.max_receiving, timeout=args.timeout, idle=args.idle,
                         metrics=metrics, inference_workers=args.inference_workers)
        uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == '__main__':
    main()
