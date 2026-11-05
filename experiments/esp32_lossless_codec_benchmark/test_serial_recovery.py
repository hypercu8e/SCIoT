import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from host_encoder import packet
from protocol import HEADER,REPLY,REPLY_MAGIC,VERSION,N
from serial_recovery import read_serial,sha,TIMERS

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.run=Path(self.temp.name)
        (self.run/'server').mkdir();body=packet(np.full(N,-20,np.int8),0);h=HEADER.unpack_from(body)
        reply=REPLY.pack(REPLY_MAGIC,VERSION,h[2],h[3],h[4],0,0,11,12,13,h[16],h[15])+bytes(1728)
        (self.run/'server/test.request.bin').write_bytes(body);(self.run/'server/test.response.bin').write_bytes(reply)
        self.suffix={k:0 for k in TIMERS};self.suffix.update(source=0,config=0,original_crc=h[15],state_crc=h[16],input_crc=h[17],activation_crc=h[15],wire_bytes=N,kind=0,server_decode_us=11,server_invoke_us=12,server_post_us=13)
        self.body=body;self.reply=reply;self.write()
    def write(self):
        # Preserve the source field as the first surviving suffix, as on USB.
        suffix=dict(source=self.suffix['source'],**{k:v for k,v in self.suffix.items() if k!='source'})
        fragment=json.dumps(suffix,separators=(',',':')).encode()[len(b'{"source"'):]
        before=dict(event='sequence_start',session=1,config=0,source=0)
        after=dict(event='sample',session=1,seq=1)
        raw=json.dumps(before).encode()+b'\n'+fragment+b'\n'+json.dumps(after).encode()+b'\n'
        (self.run/'device.log').write_bytes(raw)
        manifest=dict(device_log_sha256=sha(raw),records=[dict(line=2,fragment_sha256=sha(fragment),server_name='test',request_sha256=sha(self.body),response_sha256=sha(self.reply))])
        (self.run/'serial-recovery.json').write_text(json.dumps(manifest))
    def test_only_identity_is_recovered(self):
        rows,info=read_serial(self.run);self.assertEqual(info['recovered_records'],1)
        row=rows[1];self.assertEqual((row['event'],row['session'],row['seq'],row['frame']),('sample',1,0,0))
        for k,v in self.suffix.items():self.assertEqual(row[k],v)
    def test_missing_timing_is_not_recoverable(self):
        del self.suffix['network_us'];self.write()
        with self.assertRaises(ValueError):read_serial(self.run)
    def test_changed_log_is_rejected(self):
        p=self.run/'device.log';p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaises(ValueError):read_serial(self.run)
    def test_packet_mismatch_is_rejected(self):
        self.suffix['original_crc']^=1;self.write()
        with self.assertRaises(ValueError):read_serial(self.run)
if __name__=='__main__':unittest.main()
