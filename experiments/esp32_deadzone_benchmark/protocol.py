"""Bounded, stateful SDZ1 hardware experiment. No original tensors in decoding."""
import struct
import zlib
from dataclasses import dataclass

import numpy as np

N = 4608
HEADER = struct.Struct('<20I')
REPLY = struct.Struct('<12I')
MAGIC = int.from_bytes(b'SDZ1', 'little')
REPLY_MAGIC = int.from_bytes(b'SDR1', 'little')
VERSION = 1
NONE = 0xffffffff
MAX_PAYLOAD = 8192
MAX_BODY = HEADER.size + MAX_PAYLOAD
REPLY_BYTES = REPLY.size + 432 * 4
CONFIGS = [(0, 0, 0), (1, 0, 1), (1, 0, 6)] + [
    (mode, bits, 6) for mode in (2, 3, 4) for bits in (4, 6, 8)]
NAMES = ['raw', 'zlib1', 'zlib6'] + [
    f'{name}{bits}' for name in ('independent', 'dpcm', 'deadzone') for bits in (4, 6, 8)]


def f32_bytes(values):
    return np.asarray(values, dtype='<f4').tobytes()


def crc(data):
    return zlib.crc32(data)


def float_bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def dequantize(raw, scale, zero):
    return ((np.frombuffer(raw, np.int8).astype(np.float64) - zero) * scale).astype('<f4')


def requantize(state, scale, zero):
    return np.clip(np.rint(state.astype(np.float64) / scale + zero), -128, 127).astype(np.int8).tobytes()


def quantize(values, bits, deadzone=False):
    values = np.asarray(values, dtype='<f4')
    rank = (99 * len(values) + 99) // 100 - 1
    radius = np.partition(np.abs(values), rank)[rank]
    if radius == 0:
        return np.zeros(len(values), np.int8), np.float32(0)
    step = 2 * float(radius) / (1 << bits)
    indices = np.rint(values.astype(np.float64) / step)
    if deadzone:
        indices[np.abs(values.astype(np.float64)) < .75 * step] = 0
    limit = 1 << (bits - 1)
    return np.clip(indices, -limit, limit - 1).astype(np.int8), radius


def restore(indices, radius, bits, previous=None):
    residual = (indices.astype(np.float64) * (2 * float(radius) / (1 << bits))).astype('<f4')
    return residual if previous is None else (previous.astype(np.float64) + residual.astype(np.float64)).astype('<f4')


def decompress(payload):
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(payload, N + 1)
    except zlib.error as error:
        raise ValueError('Invalid zlib stream') from error
    if len(raw) != N or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Invalid decompressed size or trailing/incomplete stream')
    return raw


def unpack(body):
    if not HEADER.size <= len(body) <= MAX_BODY:
        raise ValueError('Invalid body length')
    keys = ('magic', 'version', 'device', 'session', 'config', 'seq', 'ref', 'kind',
            'frame', 'source', 'bits', 'level', 'radius_bits', 'count', 'length',
            'original_crc', 'state_crc', 'input_crc', 'diagnostic_source', 'header_crc')
    row = dict(zip(keys, HEADER.unpack_from(body)))
    if row['magic'] != MAGIC or row['version'] != VERSION or crc(body[:76]) != row['header_crc']:
        raise ValueError('Unknown protocol or damaged header')
    if row['count'] != N or row['length'] != len(body) - HEADER.size or not 0 < row['length'] <= MAX_PAYLOAD:
        raise ValueError('Invalid payload size')
    if row['source'] not in (0, 1, 2) or row['diagnostic_source'] not in (0, 1):
        raise ValueError('Invalid source')
    if not 0 <= row['config'] < len(CONFIGS):
        raise ValueError('Unknown configuration')
    mode, bits, level = CONFIGS[row['config']]
    if row['source'] == 2:
        mode, bits, level = 0, 0, 0
    if (row['bits'], row['level']) != (bits, level) or row['kind'] not in (0, 1):
        raise ValueError('Invalid coding parameters')
    if (mode < 3 or row['source'] == 2) and (row['kind'] or row['ref'] != NONE):
        raise ValueError('Unexpected reference')
    row['radius'] = struct.unpack('<f', struct.pack('<I', row['radius_bits']))[0]
    if not np.isfinite(row['radius']) or row['radius'] < 0 or (mode < 2 and row['radius'] != 0):
        raise ValueError('Invalid radius')
    row['symbols'] = body[HEADER.size:] if mode == 0 else decompress(body[HEADER.size:])
    if len(row['symbols']) != N:
        raise ValueError('Wrong symbol count')
    row['mode'] = mode
    return row


@dataclass
class Stream:
    config: int
    seq: int
    state: np.ndarray


class Decoder:
    def __init__(self, scale, zero):
        if scale <= 0 or not np.isfinite(scale):
            raise ValueError('Invalid scale')
        self.scale, self.zero = scale, zero
        self.streams = {}

    def decode(self, body):
        row = unpack(body)
        key = row['device'], row['session']
        previous = self.streams.get(key)
        if row['source'] != 2:
            if previous is None:
                if row['seq'] != 0 or row['kind'] or row['ref'] != NONE:
                    raise ValueError('Missing initial complete frame')
                if len(self.streams) >= 4 and not any(k[0] == row['device'] for k in self.streams):
                    raise ValueError('Too many streams')
            elif row['config'] != previous.config or row['seq'] != previous.seq + 1:
                raise ValueError('Wrong sequence/configuration')
            expected_kind = int(row['mode'] >= 3 and row['seq'] % 30 != 0)
            if row['kind'] != expected_kind or row['ref'] != (row['seq'] - 1 if expected_kind else NONE):
                raise ValueError('Wrong reference/refresh')
        symbols = np.frombuffer(row['symbols'], np.int8)
        if row['mode'] < 2:
            state = dequantize(row['symbols'], self.scale, self.zero)
            activation = row['symbols']
            if crc(activation) != row['original_crc']:
                raise ValueError('Original checksum mismatch')
        else:
            limit = 1 << (row['bits'] - 1)
            if np.any(symbols < -limit) or np.any(symbols >= limit):
                raise ValueError('Out-of-range index')
            if row['radius'] == 0 and np.any(symbols):
                raise ValueError('Nonzero index with zero radius')
            state = restore(symbols, row['radius'], row['bits'], previous.state if row['kind'] else None)
            activation = requantize(state, self.scale, self.zero)
        if not np.isfinite(state).all() or crc(f32_bytes(state)) != row['state_crc']:
            raise ValueError('Reconstructed state checksum mismatch')
        row.update(state=state, activation=activation)
        if row['source'] != 2:
            # Bounded latest-session state per device. A diagnostic never changes state.
            self.streams = {k: v for k, v in self.streams.items() if k[0] != row['device'] or k == key}
            self.streams[key] = Stream(row['config'], row['seq'], state)
        return row
