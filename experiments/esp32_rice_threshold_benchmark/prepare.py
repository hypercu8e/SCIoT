"""Freeze original 146 video inputs and already validated INT8 models."""
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / 'esp32_representation_benchmark'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    source = BASE / 'artifacts'
    manifest = json.loads((source / 'manifest.json').read_text())
    original = HERE.parent / 'activation_compression/results/input'
    input_bytes = (original / 'input_frames.npy').read_bytes()
    if sha(input_bytes) != manifest['source_input_sha256']:
        raise ValueError('Video input hash differs from hardware baseline')
    inputs = np.load(original / 'input_frames.npy', allow_pickle=False)
    if inputs.shape != (146, 96, 96, 1) or not np.isfinite(inputs).all():
        raise ValueError('Unexpected video inputs')
    out = HERE / 'artifacts'
    include = HERE / 'include/generated'
    out.mkdir(exist_ok=True)
    include.mkdir(parents=True, exist_ok=True)
    previous_build=json.loads((HERE.parent/'esp32_deadzone_benchmark/2026-10-29/build-verification.json').read_text())
    for part in ('prefix', 'suffix'):
        name = f'int8-{part}.tflite'
        binary = (source / name).read_bytes()
        if sha(binary) != manifest['models']['int8'][part]['sha256']:
            raise ValueError('Wrong frozen model')
        if sha(binary)!=previous_build[f'{part}_model_sha256']:
            raise ValueError('Model differs from previous physical benchmark')
        (out / name).write_bytes(binary)
    video = inputs.astype('<f4').tobytes()
    (out / 'video-inputs.bin').write_bytes(video)
    np.save(out / 'video-inputs.npy', inputs)
    meta = json.loads((original / 'result.json').read_text())
    manifest.update(video=meta, video_input_binary_sha256=sha(video), video_frames=146,
                    experiment='SLC2 FOMO INT8 raw versus temporal Rice threshold sweep')
    manifest['experiment_sha256'] = sha(json.dumps(manifest, sort_keys=True).encode())
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    data = (out / 'int8-prefix.tflite').read_bytes()
    lines = ['#pragma once', '#include <stdint.h>', 'alignas(16) static const uint8_t kInt8Model[] = {']
    lines += [','.join(map(str, data[i:i+24])) + ',' for i in range(0, len(data), 24)]
    lines += ['};']
    model = manifest['models']['int8']['prefix']
    for name, value in [('InputScale', model['input']['scales'][0]),
                        ('BoundaryScale', model['output']['scales'][0])]:
        lines.append(f'static const double k{name} = {value:.17g};')
    for name, value in [('InputZero', model['input']['zero_points'][0]),
                        ('BoundaryZero', model['output']['zero_points'][0])]:
        lines.append(f'static const int k{name} = {value};')
    lines += [f'static const char kInt8Sha[] = "{model["sha256"]}";',
              f'static const char kExperimentSha[] = "{manifest["experiment_sha256"]}";',
              'constexpr int kPixels=96*96, kVideoFrames=146;']
    (include / 'assets.h').write_text('\n'.join(lines) + '\n')
    # Network configuration is optional for offline preparation and codec build.
    print(json.dumps({'frames': 146, 'video_flash_bytes': len(video),
                      'experiment_sha256': manifest['experiment_sha256']}))


if __name__ == '__main__':
    main()
