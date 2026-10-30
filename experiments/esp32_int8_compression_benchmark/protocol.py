"""SCB compression protocol v2: independently compressed, bounded INT8 tensors."""
import struct
import zlib

REQUEST=struct.Struct('<8I')
RESPONSE=struct.Struct('<8I')
REQUEST_MAGIC=int.from_bytes(b'SCC2','little')
RESPONSE_MAGIC=int.from_bytes(b'SCR1','little')
VERSION=2
RAW_BYTES=4608
MAX_WIRE_BYTES=8192
MAX_BODY=REQUEST.size+MAX_WIRE_BYTES
CODECS={0:'raw',1:'zlib'}


def encode(raw,codec,frame=48,iteration=0):
    if len(raw)!=RAW_BYTES or codec not in CODECS:raise ValueError('Invalid tensor/codec')
    payload=raw if codec==0 else zlib.compress(raw,1)
    return REQUEST.pack(REQUEST_MAGIC,VERSION,codec,frame,iteration,RAW_BYTES,len(payload),zlib.crc32(raw))+payload


def parse_request(body):
    if not REQUEST.size<=len(body)<=MAX_BODY:raise ValueError('Invalid request size')
    magic,version,codec,frame,iteration,raw_bytes,wire_bytes,crc=REQUEST.unpack_from(body)
    if magic!=REQUEST_MAGIC or version!=VERSION or codec not in CODECS:raise ValueError('Unknown version/codec')
    if raw_bytes!=RAW_BYTES or not 0<wire_bytes<=MAX_WIRE_BYTES or len(body)!=REQUEST.size+wire_bytes:
        raise ValueError('Wrong tensor/packet length')
    payload=body[REQUEST.size:]
    if codec==0:
        raw=payload
    else:
        decoder=zlib.decompressobj()
        try:raw=decoder.decompress(payload,RAW_BYTES+1)
        except zlib.error as error:raise ValueError('Invalid zlib stream') from error
        if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
            raise ValueError('Incomplete/overlong zlib stream')
    if len(raw)!=RAW_BYTES or zlib.crc32(raw)!=crc:raise ValueError('Wrong decoded size/checksum')
    return {'mode':CODECS[codec],'codec':codec,'frame':frame,'iteration':iteration,
            'activation':raw,'wire_bytes':wire_bytes}
