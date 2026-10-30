"""Bounded experimental request protocol; not the original SCIoT wire format."""
import struct
import zlib

REQUEST = struct.Struct('<8I')
RESPONSE = struct.Struct('<8I')
REQUEST_MAGIC = int.from_bytes(b'SCB1', 'little')
RESPONSE_MAGIC = int.from_bytes(b'SCR1', 'little')
MODES = {0: 'float32', 1: 'int8'}
MAX_BODY = REQUEST.size + 96*96*2 + 24*24*8*4


def parse_request(body):
    if not REQUEST.size <= len(body) <= MAX_BODY:
        raise ValueError('Invalid request size')
    magic, version, dtype, frame, iteration, image_bytes, activation_bytes, crc = REQUEST.unpack_from(body)
    if magic != REQUEST_MAGIC or version != 1 or dtype not in MODES:
        raise ValueError('Invalid protocol version/dtype')
    expected = 4608 * (4 if dtype == 0 else 1)
    if image_bytes not in (0, 96*96*2) or activation_bytes != expected:
        raise ValueError('Invalid tensor/image dimensions')
    if len(body) != REQUEST.size + image_bytes + activation_bytes:
        raise ValueError('Truncated/overlong request')
    image = body[REQUEST.size:REQUEST.size+image_bytes]
    activation = body[REQUEST.size+image_bytes:]
    if zlib.crc32(image+activation) != crc:
        raise ValueError('Payload CRC mismatch')
    return {'mode': MODES[dtype], 'frame': frame, 'iteration': iteration,
            'image': image, 'activation': activation}
