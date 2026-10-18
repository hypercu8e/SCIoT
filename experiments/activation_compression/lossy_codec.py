"""Uniform activation quantization plus independent or temporal integer coding.

Offline experimental format, separate from ACT1 and the SCIoT transport.
The two methods reconstruct identical tensors at a given quantization step.
"""

import json
import math
import struct
import zlib
from dataclasses import asdict, dataclass

import numpy as np

from compare import HEADER, NO_REFERENCE, shuffle, unshuffle

FULL_RAW, FULL_COMPRESSED, DELTA_COMPRESSED = range(3)
METHODS = ("independent", "temporal")
# Any difference between two permitted values fits signed int32.
QUANT_LIMIT = 2**30 - 1


def quantize(values, step):
    if not math.isfinite(step) or step <= 0:
        raise ValueError("Quantization step must be finite and positive")
    values = np.asarray(values)
    if values.dtype != np.float32 or not np.isfinite(values).all():
        raise ValueError("Expected finite float32 activations")
    with np.errstate(over="ignore", invalid="ignore"):
        rounded = np.rint(values.astype(np.float64) / step)
    if not np.isfinite(rounded).all() or np.any(np.abs(rounded) > QUANT_LIMIT):
        raise ValueError("Quantized values exceed the safe int32 range; no clipping")
    return rounded.astype("<i4")


def reconstruct(integers, step):
    with np.errstate(over="ignore", invalid="ignore"):
        result = (integers.astype(np.float64) * step).astype("<f4")
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite reconstructed activations")
    return result


@dataclass(frozen=True)
class Session:
    shape: tuple
    step: float
    method: str
    refresh_frames: int
    model_sha256: str = "synthetic-test"
    split_layer: str = "synthetic-test"
    sampling_fps: float = 5.0
    version: int = 1
    integer_dtype: str = "<i4"
    reconstruction_dtype: str = "<f4"
    rounding: str = "nearest_ties_to_even"
    zlib_level: int = 1
    zlib_window_bits: int = 15
    zlib_mem_level: int = 8

    def __post_init__(self):
        if (not self.shape or any(type(n) is not int or n <= 0 for n in self.shape)
                or self.method not in METHODS or self.refresh_frames < 1
                or not math.isfinite(self.step) or self.step <= 0
                or not math.isfinite(self.sampling_fps) or self.sampling_fps <= 0
                or self.version != 1 or self.integer_dtype != "<i4"
                or self.reconstruction_dtype != "<f4"
                or self.rounding != "nearest_ties_to_even"
                or (self.zlib_level, self.zlib_window_bits, self.zlib_mem_level) != (1, 15, 8)):
            raise ValueError("Unsupported lossy session")

    @property
    def tensor_bytes(self):
        return math.prod(self.shape) * 4

    def to_packet(self):
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return struct.pack("!4sI", b"AQST", len(payload)) + payload

    @classmethod
    def from_packet(cls, packet):
        if len(packet) < 8 or packet[:4] != b"AQST":
            raise ValueError("Invalid session packet")
        if struct.unpack_from("!I", packet, 4)[0] != len(packet) - 8:
            raise ValueError("Invalid session length")
        fields = json.loads(packet[8:])
        fields["shape"] = tuple(fields["shape"])
        return cls(**fields)


class Encoder:
    def __init__(self, session):
        self.session = session
        self.reference = None
        self.sequence = 0

    def encode(self, values):
        if tuple(values.shape) != self.session.shape:
            raise ValueError("Tensor shape changed; start a new session")
        integers = quantize(values, self.session.step)
        raw = integers.tobytes()
        full = zlib.compress(shuffle(raw), self.session.zlib_level)
        kind, payload = (FULL_COMPRESSED, full) if len(full) < len(raw) else (FULL_RAW, raw)
        refresh = self.sequence % self.session.refresh_frames == 0
        candidate_bytes = None
        zero_fraction = None
        if self.session.method == "temporal" and self.reference is not None and not refresh:
            previous = np.frombuffer(self.reference, dtype="<i4").reshape(self.session.shape)
            # Bounds enforced by quantize() make signed int32 subtraction safe.
            residual = (integers - previous).astype("<i4")
            zero_fraction = float(np.mean(residual == 0))
            candidate = zlib.compress(shuffle(residual.tobytes()), self.session.zlib_level)
            candidate_bytes = len(candidate)
            if len(candidate) < len(payload):
                kind, payload = DELTA_COMPRESSED, candidate
        refseq = self.sequence - 1 if kind == DELTA_COMPRESSED else NO_REFERENCE
        packet = HEADER.pack(
            b"AQF1", 1, kind, 0, self.sequence, refseq, len(payload), zlib.crc32(raw),
        ) + payload
        # This is the same integer lattice point that the decoder reconstructs.
        self.reference = raw if self.session.method == "temporal" else None
        info = {
            "sequence": self.sequence, "kind": kind, "scheduled_refresh": refresh,
            "payload_bytes": len(payload), "packet_bytes": len(packet),
            "delta_candidate_bytes": candidate_bytes,
            "zero_delta_fraction": zero_fraction,
        }
        self.sequence += 1
        return packet, info


class Decoder:
    def __init__(self, session):
        self.session = session
        self.reference = None
        self.sequence = -1

    def decode(self, packet):
        if len(packet) < HEADER.size:
            raise ValueError("Truncated packet")
        magic, version, kind, flags, sequence, refseq, size, crc = HEADER.unpack_from(packet)
        if magic != b"AQF1" or version != 1 or flags or kind not in range(3):
            raise ValueError("Invalid frame header")
        if size != len(packet) - HEADER.size:
            raise ValueError("Invalid payload length")
        if sequence <= self.sequence:
            raise ValueError("Duplicate or out-of-order frame")
        dependent = kind == DELTA_COMPRESSED
        if dependent and (
            self.session.method != "temporal" or self.reference is None
            or refseq != self.sequence or sequence != refseq + 1
        ):
            raise ValueError("Missing reference; wait for a complete frame")
        if not dependent and refseq != NO_REFERENCE:
            raise ValueError("Unexpected reference")
        data = packet[HEADER.size:]
        if kind != FULL_RAW:
            try:
                stream = zlib.decompressobj()
                data = stream.decompress(data, self.session.tensor_bytes + 1)
                if not stream.eof or stream.unused_data or stream.unconsumed_tail:
                    raise ValueError("Invalid or oversized compressed payload")
            except zlib.error as error:
                raise ValueError("Invalid compressed payload") from error
        if len(data) != self.session.tensor_bytes:
            raise ValueError("Invalid decoded tensor size")
        if kind != FULL_RAW:
            data = unshuffle(data)
        integers = np.frombuffer(data, dtype="<i4").reshape(self.session.shape)
        if dependent:
            previous = np.frombuffer(self.reference, dtype="<i4").reshape(self.session.shape)
            summed = integers.astype(np.int64) + previous.astype(np.int64)
            if np.any(np.abs(summed) > QUANT_LIMIT):
                raise ValueError("Reconstructed integer outside safe range")
            integers = summed.astype("<i4")
        elif np.any(np.abs(integers.astype(np.int64)) > QUANT_LIMIT):
            raise ValueError("Decoded integer outside safe range")
        raw = integers.tobytes()
        if zlib.crc32(raw) != crc:
            raise ValueError("Reconstructed integer checksum mismatch")
        restored = reconstruct(integers, self.session.step)
        # Do not change state until every validation has passed.
        self.reference = raw if self.session.method == "temporal" else None
        self.sequence = sequence
        return raw, restored
