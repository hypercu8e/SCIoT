"""Prepare the two archived models at an identical graph cut; no retraining."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
COMPRESSION = HERE.parent / 'activation_compression'
sys.path.insert(0, str(COMPRESSION))
from check_int8 import prepare_input, tensor_description
from split_tflite import split_single_boundary
from prepare_esp32_int8 import interpreter, invoke


def sha(data):
    return hashlib.sha256(data).hexdigest()


def c_array(name, data):
    rows = [f'alignas(16) static const uint8_t {name}[] = {{']
    rows += ['  ' + ','.join(str(v) for v in data[i:i+24]) + ','
             for i in range(0, len(data), 24)]
    return '\n'.join(rows + ['};'])


def main():
    archive = COMPRESSION / 'int8_2026-10-18'
    original = json.loads((archive / 'summary.json').read_text())
    source = COMPRESSION / 'results/input/input_frames.npy'
    if sha(source.read_bytes()) != original['input_sha256']['input_frames.npy']:
        raise ValueError('Canonical image hash differs')
    frames = np.load(source, allow_pickle=False)[[48, 96, 145]].copy()
    out = HERE / 'artifacts'
    out.mkdir(exist_ok=True)
    manifest = {'frames': [48, 96, 145], 'models': {}, 'source_input_sha256': sha(source.read_bytes()),
                'scope': 'Archived candidate grayscale FOMO, split at block_2_add; one experimental HTTP request per inference'}
    lines = ['#pragma once', '#include <stdint.h>',
             'static const int kFrameIds[] = {48,96,145};',
             'static const int kPixels = 96*96;', 'static const int kOutputValues = 12*12*3;']
    for i, frame in enumerate(frames):
        lines.append(c_array(f'kFrame{i}', frame.astype('<f4').tobytes()))
    lines.append('static const uint8_t* const kFrames[] = {kFrame0,kFrame1,kFrame2};')
    for mode in ('float32', 'int8'):
        full = (archive / f'fomo_{mode}.tflite').read_bytes()
        if sha(full) != original['models'][mode]['sha256']:
            raise ValueError(f'Archived model hash differs: {mode}')
        boundary = original['models'][mode]['boundary']['name']
        prefix, suffix = split_single_boundary(full, boundary)
        binaries = {'full': full, 'prefix': prefix, 'suffix': suffix}
        runtimes = {name: interpreter(binary) for name, binary in binaries.items()}
        rows = {}
        for name, data in binaries.items():
            (out / f'{mode}-{name}.tflite').write_bytes(data)
            rows[name] = {'sha256': sha(data), 'bytes': len(data),
                          'input': tensor_description(runtimes[name].get_input_details()[0]),
                          'output': tensor_description(runtimes[name].get_output_details()[0])}
        max_error = 0.0
        for frame in frames:
            values, _ = prepare_input(frame[None], runtimes['full'].get_input_details()[0])
            expected = invoke(runtimes['full'], values)
            boundary_values = invoke(runtimes['prefix'], values)
            actual = invoke(runtimes['suffix'], boundary_values)
            error = float(np.abs(expected.astype(np.float64)-actual.astype(np.float64)).max())
            max_error = max(max_error, error)
            if mode == 'int8':
                np.testing.assert_array_equal(actual, expected)
            else:
                np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=1e-5)
        rows['desktop_split_vs_full_max_error'] = max_error
        manifest['models'][mode] = rows
        tag = 'Float' if mode == 'float32' else 'Int8'
        lines += [c_array(f'k{tag}Model', prefix),
                  f'static const char k{tag}Sha[] = "{sha(prefix)}";']
        spec = rows['prefix']['input']
        if mode == 'int8':
            lines += [f'static const double kInputScale = {spec["scales"][0]:.17g};',
                      f'static const int kInputZero = {spec["zero_points"][0]};']
    np.savez_compressed(out / 'inputs.npz', frames=frames, frame_ids=np.array([48, 96, 145]))
    manifest['inputs_sha256'] = sha((out/'inputs.npz').read_bytes())
    canonical = json.dumps(manifest, sort_keys=True).encode()
    lines.append(f'static const char kExperimentSha[] = "{sha(canonical)}";')
    manifest['experiment_sha256'] = sha(canonical)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    target = HERE/'include/generated/assets.h'
    target.parent.mkdir(exist_ok=True)
    target.write_text('\n'.join(lines)+'\n')
    print('Prepared float32 and INT8 at identical cut; split/full desktop checks passed')


if __name__ == '__main__':
    main()
