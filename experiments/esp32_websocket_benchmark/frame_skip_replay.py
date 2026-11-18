"""Compare selective inference policies on identical timestamped camera inputs."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import zlib

import numpy as np

from analyze import percentile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARTIFACTS = ROOT / 'experiments/esp32_representation_benchmark/artifacts'
sys.path.insert(0, str(ROOT / 'src'))
from server.multiclient.engine import Suffix
from server.multiclient.fomo import decode
from server.multiclient.protocol import HEADER, REQUEST_MAGIC


def video_frames(video, interval_ms, offset_ms=0):
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams',
        '-show_frames', '-show_entries',
        'stream=width,height:stream_side_data=rotation:frame=best_effort_timestamp_time',
        '-of', 'json', str(video)]))
    stream = probe['streams'][0]
    if any(side.get('rotation', 0) for side in stream.get('side_data_list', [])):
        raise ValueError('Rotated videos require normalization before replay')
    timestamps = np.array([round(float(row['best_effort_timestamp_time']) * 1e6)
                           for row in probe['frames']], dtype=np.int64)
    if not len(timestamps) or np.any(np.diff(timestamps) <= 0):
        raise ValueError('Expected strictly increasing video timestamps')
    timestamps -= timestamps[0]
    targets = np.arange(offset_ms * 1000, timestamps[-1] + 1, interval_ms * 1000)
    indices = np.unique(np.searchsorted(timestamps, targets))
    if not len(indices):
        raise ValueError('No frame at the requested sampling offset')
    width, height = stream['width'], stream['height']
    side = min(width, height)
    crop = f'crop={side}:{side}:{(width-side)//2}:{(height-side)//2}'
    raw = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(video), '-map', '0:v:0',
        '-vf', f'{crop},scale=96:96:flags=lanczos', '-fps_mode', 'passthrough', '-enc_time_base', '1/1000000',
        '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'])
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 96, 96, 3)
    if len(rgb) != len(timestamps):
        raise ValueError('Decoded frames do not match indexed timestamps')
    return timestamps[indices], indices, rgb[indices]


def camera_input(rgb, scale, zero):
    # Emulate the benchmark's RGB565 truncation and float32 luminance LUT.
    red = (rgb[..., 0] >> 3).astype(np.float32) / np.float32(31)
    green = (rgb[..., 1] >> 2).astype(np.float32) / np.float32(63)
    blue = (rgb[..., 2] >> 3).astype(np.float32) / np.float32(31)
    gray = red * np.float32(.299) + green * np.float32(.587) + blue * np.float32(.114)
    return np.clip(np.rint(gray.astype(np.float64) / scale + zero), -128, 127).astype(np.int8)


def baseline_inputs_and_scores(rgb):
    import tensorflow as tf

    prefix = HERE / 'artifacts/int8-prefix-nopad.tflite'
    registry = json.loads((HERE / 'artifacts/model-registry.json').read_text())
    digest = hashlib.sha256(prefix.read_bytes()).hexdigest()
    if digest not in {entry['sha256'] for entry in registry['prefixes']}:
        raise ValueError('Unexpected prefix model')
    runtime = tf.lite.Interpreter(
        model_path=str(prefix), num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    runtime.allocate_tensors()
    input_detail = runtime.get_input_details()[0]
    output_detail = runtime.get_output_details()[0]
    suffix = Suffix(ARTIFACTS)
    if (input_detail['shape'].tolist() != [1, 96, 96, 1] or input_detail['dtype'] != np.int8
            or output_detail['dtype'] != np.int8 or any(
                not np.array_equal(output_detail[key], suffix.input[key]) for key in ('shape', 'quantization'))):
        raise ValueError('Unexpected prefix tensors')
    inputs = camera_input(rgb, *input_detail['quantization'])
    scores = []
    for frame, image in enumerate(inputs):
        runtime.set_tensor(input_detail['index'], image[None, ..., None])
        runtime.invoke()
        activation = runtime.get_tensor(output_detail['index']).tobytes()
        header = HEADER.pack(REQUEST_MAGIC, 1, 1, frame, frame, 0, len(activation), zlib.crc32(activation))
        scores.append(np.frombuffer(suffix(header + activation)[HEADER.size:], dtype='<f4').reshape(12, 12, 3))
    return inputs, np.stack(scores), {'prefix_sha256': digest, 'suffix_sha256': registry['suffix_sha256']}


def visual_selection(inputs, timestamps, metric, threshold, refresh_ms):
    pixels = inputs.astype(np.int16)
    retained = 0
    selected = [0]
    for index in range(1, len(inputs)):
        diff = np.abs(pixels[index] - pixels[retained])
        if metric == 'global':
            changed = diff.sum() >= threshold * 96 * 96
        else:
            changed = diff.reshape(12, 8, 12, 8).sum(axis=(1, 3)).max() >= threshold * 64
        if changed or timestamps[index] - timestamps[retained] >= refresh_ms * 1000:
            retained = index
        selected.append(retained)
    return np.asarray(selected)


def intervals(mask):
    return np.flatnonzero(np.diff(np.r_[False, mask, False])).reshape(-1, 2)


def uniform_selection(frame_count, budget):
    sent_at = np.arange(budget) * frame_count // budget
    return sent_at[np.searchsorted(sent_at, np.arange(frame_count), side='right') - 1]


def summarize_policy(timestamps, presence, grid, retained):
    shown = presence[retained]
    events = []
    for channel in range(presence.shape[1]):
        runs = intervals(presence[:, channel])
        for (enter, leave), next_enter in zip(runs, np.r_[runs[1:, 0], len(presence)]):
            # A detection retained from an earlier event is not evidence of a new one.
            seen = np.flatnonzero(shown[enter:leave, channel] & (retained[enter:leave] >= enter))
            disappearance = np.flatnonzero(~shown[leave:next_enter, channel])
            events.append({
                'channel': channel + 1, 'first_sample': int(enter), 'last_sample': int(leave - 1),
                'missed': not len(seen),
                'onset_delay_ms': float((timestamps[enter + seen[0]] - timestamps[enter]) / 1000) if len(seen) else None,
                'disappearance_delay_ms': (float((timestamps[leave + disappearance[0]] - timestamps[leave]) / 1000)
                                           if len(seen) and len(disappearance) else None),
                'disappearance_censored': bool(len(seen) and not len(disappearance)),
            })
    ages = (timestamps - timestamps[retained]) / 1000
    sent = int(np.count_nonzero(retained == np.arange(len(retained))))
    onset = [event['onset_delay_ms'] for event in events if event['onset_delay_ms'] is not None]
    disappearance = [event['disappearance_delay_ms'] for event in events
                     if event['disappearance_delay_ms'] is not None]
    return {
        'sent': sent, 'skipped': len(retained) - sent, 'skip_fraction': 1 - sent / len(retained),
        'max_age_ms': float(max(ages)), 'p95_age_ms': percentile(ages, 95),
        'max_onset_delay_ms': max(onset, default=None),
        'max_disappearance_delay_ms': max(disappearance, default=None), 'events': events,
        'missed_events': sum(event['missed'] for event in events),
        'stale_presence_samples': int(np.count_nonzero(shown & ~presence)),
        'grid_disagreement': float(np.mean(grid != grid[retained])),
        'retained_samples': retained.tolist(),
    }


def compare(timestamps, inputs, scores):
    frame = np.arange(len(inputs))
    channels = [{box['channel'] for box in decode(score)} for score in scores]
    presence = np.array([[channel in detected for channel in (1, 2)] for detected in channels])
    grid = scores[..., 1:] >= .5
    policies = [dict(metric='baseline', **summarize_policy(timestamps, presence, grid, frame))]
    for period in (2, 3, 4):
        policies.append(dict(metric='periodic', period=period,
                             **summarize_policy(timestamps, presence, grid, frame - frame % period)))
    visual = []
    for metric, threshold, refresh in itertools.product(
            ('global', 'local'), (1, 2, 4, 8, 16, 32), (1500, 3000, 5000)):
        retained = visual_selection(inputs, timestamps, metric, threshold, refresh)
        visual.append(dict(metric=metric, threshold=threshold, refresh_ms=refresh,
                           **summarize_policy(timestamps, presence, grid, retained)))
    for budget in sorted({row['sent'] for row in visual}):
        retained = uniform_selection(len(frame), budget)
        policies.append(dict(metric='uniform_budget', budget=budget,
                             **summarize_policy(timestamps, presence, grid, retained)))

    def delay(row):
        return row['max_onset_delay_ms'] if row['max_onset_delay_ms'] is not None else float('inf')

    most_preserved = min(visual, key=lambda row: (
        row['missed_events'], -row['skipped'], delay(row), row['grid_disagreement']))
    most_saved = min(visual, key=lambda row: (
        -row['skipped'], row['missed_events'], delay(row), row['grid_disagreement']))
    options = ('metric', 'threshold', 'refresh_ms')
    return policies + visual, {
        name: {key: row[key] for key in options}
        for name, row in [('fewest_missed_events', most_preserved), ('most_skips', most_saved)]
    }


def report(summary):
    lines = ['# Replay dello skip su frame video', '',
             f"{len(summary['samples'])} frame campionati ogni {summary['interval_ms']} ms "
             f"con offset di {summary['offset_ms']} ms. "
             f"La baseline FOMO rileva {len(summary['policies'][0]['events'])} intervalli di presenza per classe.", '',
             '| Politica | Soglia | Rinnovo (ms) | Skip | Eventi persi | Ritardo max ingresso (ms) | '
             'Ritardo max uscita (ms) | Età max (ms) | Disaccordo griglia |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']

    def append(row, label):
        delays = (row['max_onset_delay_ms'], row['max_disappearance_delay_ms'])
        onset, disappearance = (f'{value:.1f}' if value is not None else '–' for value in delays)
        lines.append(f"| {label} | {row.get('threshold', '–')} | {row.get('refresh_ms', '–')} | "
                     f"{row['skipped']} ({row['skip_fraction']:.1%}) | {row['missed_events']} | "
                     f"{onset} | {disappearance} | {row['max_age_ms']:.1f} | {row['grid_disagreement']:.2%} |")
    budget_rows = {row['budget']: row for row in summary['policies'] if row['metric'] == 'uniform_budget'}
    for row in summary['policies']:
        if row['metric'] != 'uniform_budget':
            append(row, f"Ogni {row['period']} frame" if row['metric'] == 'periodic' else row['metric'])
    for config in summary['hardware_candidates'].values():
        selected = next(row for row in summary['policies'] if all(row.get(key) == value for key, value in config.items()))
        append(budget_rows[selected['sent']], f"Uniforme, {selected['sent']} invii come {config['metric']} "
               f"{config['threshold']} / {config['refresh_ms']} ms")
    lines.extend(['', 'Il JSON contiene gli intervalli, i ritardi di uscita e le uscite censurate '
                  'dal successivo ingresso o dalla fine del video. '
                  'La qualità è misurata rispetto al FOMO a soglia 0,5 sullo stesso video. '
                  'La prova sulla camera serve a misurare rumore, tempi e riuso della connessione.', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=ROOT / 'VideoWithCan.mp4')
    parser.add_argument('--interval-ms', type=int, default=710)
    parser.add_argument('--offset-ms', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.interval_ms < 1 or not 0 <= args.offset_ms < args.interval_ms or args.output.exists():
        parser.error('Provide an offset within the sampling interval and a new output directory')
    timestamps, source_indices, rgb = video_frames(args.video, args.interval_ms, args.offset_ms)
    inputs, scores, models = baseline_inputs_and_scores(rgb)
    policies, candidates = compare(timestamps, inputs, scores)
    summary = {
        'video_sha256': hashlib.sha256(args.video.read_bytes()).hexdigest(), **models,
        'interval_ms': args.interval_ms, 'offset_ms': args.offset_ms, 'fomo_threshold': .5,
        'samples': [{'pts_us': int(t), 'source_index': int(i)} for t, i in zip(timestamps, source_indices)],
        'policies': policies, 'hardware_candidates': candidates,
    }
    args.output.mkdir(parents=True)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (args.output / 'report.md').write_text(report(summary))
    print(json.dumps(candidates, indent=2))


if __name__ == '__main__':
    main()
