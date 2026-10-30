"""INT8-only adapter for the frozen SCB1 benchmark wire format."""
import struct
import zlib

HEADER = struct.Struct('<8I')
REQUEST_MAGIC = int.from_bytes(b'SCB1', 'little')
RESPONSE_MAGIC = int.from_bytes(b'SCR1', 'little')
BODY_BYTES = 32 + 4608


def parse(body):
    if len(body) != BODY_BYTES:
        raise ValueError('Expected 4640 request bytes')
    magic, version, dtype, frame, iteration, image, size, crc = HEADER.unpack_from(body)
    if (magic, version, dtype, image, size) != (REQUEST_MAGIC, 1, 1, 0, 4608):
        raise ValueError('Invalid INT8 request header')
    activation = body[32:]
    if zlib.crc32(activation) != crc:
        raise ValueError('Activation CRC mismatch')
    return frame, iteration, activation


def response(frame, iteration, output, decode_us, invoke_us, post_us):
    if len(output) != 432 * 4:
        raise ValueError('Invalid suffix output size')
    return HEADER.pack(RESPONSE_MAGIC, 1, frame, iteration, 432,
                       decode_us, invoke_us, post_us) + output
