"""Cross-check HTTP-persistent frame policy telemetry against server requests."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from analyze import percentile, verify_recovery
from frame_skip_replay import summarize_policy, uniform_selection


def timing_ms(values):
    return {f'p{q}': percentile(values, q) / 1000 for q in (50, 95)} if values else {}


def audit_boot(rows, server_rows):
    configs = [row for row in rows if row['event'] == 'frame_policy_config']
    done = [row for row in rows if row['event'] == 'done']
    if len(configs) != 1 or len(done) != 1 or any(row['event'] == 'error' for row in rows):
        raise ValueError('Incomplete policy boot')
    config, done = configs[0], done[0]
    mode = config['mode']
    frames = [row for row in rows if row['event'] == 'frame_policy']
    samples = [row for row in rows if row['event'] == 'sample']
    checks = [row for row in rows if row['event'] == 'canonical_check']
    validations = [row for row in rows if row['event'] == 'validation']
    count = done['camera_completed']
    if (count != config['camera_frames'] or not 100 <= count <= 1000 or
            [r['index'] for r in frames] != list(range(count)) or
            [r['index'] for r in samples] != list(range(count)) or
            [r['after_frames'] for r in checks] != list(range(100, count + 1, 100)) or
            not all(r['exact'] and r['guards'] and r['inputs'] == 3 for r in checks) or
            len(validations) != 1 or validations[0]['inputs'] != 35 or
            not validations[0]['exact'] or not validations[0]['guards'] or
            done['wifi_disconnections'] or not all(done[key] for key in ('all_exact', 'guards', 'heap_integrity'))):
        raise ValueError('Camera frames or integrity checks missing')

    exchanges = [row for row in rows if row['event'] == 'exchange']
    camera = [row for row in exchanges if row['frame'] >= 1000]
    sent_at = [row['index'] for row in frames if row['sent']]
    if ([row['request_id'] for row in exchanges] != list(range(1100 + len(sent_at))) or
            any(not row['ok'] or row['mode'] != 'h' for row in exchanges) or
            [(r['iteration'], r['frame']) for r in exchanges[:1100]] != [(i, i % 3) for i in range(1100)] or
            [(r['iteration'], r['frame']) for r in camera] != [(i, 1000 + i) for i in sent_at]):
        raise ValueError('Exchange sequence differs from camera policy')

    server = [row for row in server_rows if row.get('session_id') == config['session_id']]
    terminal = [row for row in server if row['event'] == 'terminal']
    admitted = [row for row in server if row['event'] == 'admitted']
    request_ids = list(range(len(exchanges)))
    if (sorted(row['request_id'] for row in terminal) != request_ids or
            sorted(row['request_id'] for row in admitted) != request_ids or
            any(row['status'] != 200 or row['response_body_bytes'] != 1760 for row in terminal) or
            any(row['request_body_bytes'] != 4640 for row in admitted)):
        raise ValueError('Server request records differ from firmware exchanges')

    reference = -1
    retained = []
    timestamps = np.array([row['capture_us'] for row in frames])
    if np.any(np.diff(timestamps) <= 0) or mode not in ('baseline', 'shadow', 'active'):
        raise ValueError('Invalid capture order or policy mode')
    for row, sample in zip(frames, samples):
        index = row['index']
        age = -1 if reference < 0 else timestamps[index] - timestamps[reference]
        if mode == 'baseline':
            reason = 'baseline'
        elif reference < 0:
            reason = 'first'
        elif row['difference'] >= config['threshold']:
            reason = 'change'
        elif age >= config['refresh_ms'] * 1000:
            reason = 'refresh'
        else:
            reason = 'similar'
        send = mode != 'active' or reason != 'similar'
        if (row['reference_index'] != reference or row['age_us'] != age or row['reason'] != reason or
                row['sent'] != send or not sample['guards'] or not sample['wifi_connected'] or
                (sample['conv_calls'], sample['depthwise_calls']) != ((6, 3) if send else (0, 0)) or
                (sample['invoke_us'] <= 0 if send else sample['invoke_us'] != 0) or
                len(row['grid']) != (144 if send else 0) or set(row['grid']) - set('0123')):
            raise ValueError(f'Inconsistent policy telemetry at frame {index}')
        if mode != 'baseline' and reason != 'similar':
            reference = index
        retained.append(index if mode == 'baseline' else reference)

    connections = [row['http_connections'] for row in frames]
    if connections[0] < 2 or any(new < old or (new != old and not row['sent'])
                                for old, new, row in zip(connections, connections[1:], frames[1:])):
        raise ValueError('Inconsistent HTTP connection telemetry')
    followups = [(before, after) for before, after in zip(sent_at, sent_at[1:]) if after > before + 1]
    reused = sum(connections[before] == connections[after] for before, after in followups)
    ages = timestamps - timestamps[retained]
    result = {
        'configuration': config,
        'captured': count, 'sent': len(sent_at), 'skipped': count - len(sent_at),
        'skip_fraction': (count - len(sent_at)) / count,
        'capture_fps': float((count - 1) * 1e6 / (timestamps[-1] - timestamps[0])),
        'hypothetical_skips': sum(row['reason'] == 'similar' for row in frames),
        'decisions': dict(Counter(row['reason'] for row in frames)),
        'retained_age_ms': {**timing_ms(ages.tolist()), 'max': float(max(ages) / 1000)},
        'max_inter_request_capture_gap_ms': float(max(np.diff(timestamps[sent_at]), default=0) / 1000),
        'http_connections_opened_during_camera': connections[-1] - connections[0],
        'after_skip_resumed_requests': len(followups), 'after_skip_same_connection': reused,
        'camera_request_body_bytes': len(sent_at) * 4640,
        'camera_response_body_bytes': len(sent_at) * 1760,
        'minimum_internal_free': min(row['internal_min_free'] for row in rows if 'internal_min_free' in row),
        'decision_ms': timing_ms([row['decision_us'] for row in frames]),
        'capture_ms': timing_ms([row['acquisition_us'] for row in samples]),
        'cycle_ms': timing_ms([row['local_cycle_us'] for row in samples]),
        'skip_cycle_ms': timing_ms([s['local_cycle_us'] for s, row in zip(samples, frames) if not row['sent']]),
        'invoke_ms': timing_ms([samples[i]['invoke_us'] for i in sent_at]),
        'request_response_ms': timing_ms([row['request_response_us'] for row in camera]),
    }
    if mode == 'shadow':
        cells = np.array([[int(value) for value in row['grid']] for row in frames])
        grid = (cells[..., None] & [1, 2]) != 0
        presence = grid.any(axis=1)
        result['shadow_quality'] = summarize_policy(timestamps, presence, grid, np.array(retained))
        result['same_budget_uniform_quality'] = summarize_policy(
            timestamps, presence, grid, uniform_selection(count, result['shadow_quality']['sent']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--server-events', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    completion = verify_recovery(args.run)
    config = json.loads((args.run / 'configuration.json').read_text())
    if not completion['measurements_complete'] or not config.get('frame_skip'):
        raise ValueError('Expected a complete frame-skip campaign')
    paths = sorted((args.run / 'board').glob('round-*.events.jsonl'))
    if len(paths) != len(config['commands']) or len(paths) != completion['rounds_completed']:
        raise ValueError('Round counts differ')
    server_rows = [json.loads(line) for line in args.server_events.read_text().splitlines()]
    boots = [audit_boot([json.loads(line)['row'] for line in path.read_text().splitlines()], server_rows)
             for path in paths]
    for boot, command in zip(boots, config['commands']):
        expected = boot['configuration']
        if command.strip() != (f"F{expected['mode'][0]} {expected['metric'][0]} "
                               f"{expected['threshold']} {expected['refresh_ms']} {expected['camera_frames']}"):
            raise ValueError('Recorded frame policy differs from requested policy')
    with args.output.open('x') as stream:
        json.dump({'restored': True, 'boots': boots}, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
