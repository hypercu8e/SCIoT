import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('ws_analysis',HERE/'analyze.py');analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


def fixture(root):
    def write(name, data):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(data,dict):data=json.dumps(data).encode()
        path.write_bytes(data)
    digest=lambda data:hashlib.sha256(data).hexdigest()
    write('board/original-flash.bin',b'public synthetic flash')
    write('firmware/firmware.bin',b'public synthetic firmware')
    write('sources/example.py',b'public synthetic source')
    write('source-sha256.json',{'example.py':digest(b'public synthetic source')})
    write('board/hardware.json',dict(backup_verified=True,restored=True,backup_sha256=digest(b'public synthetic flash'),installed_sha256=digest(b'public synthetic firmware')))
    write('completion.json',dict(original_boot_confirmed=True,restore_error=None,measurements_complete=False,error='synthetic timeout'))
    rows=[dict(event='exchange',mode='w',request_id=i,frame=i%3,iteration=i,ok=i<2,request_response_us=1000,internal_min_free=45000) for i in range(3)]
    rows.append(dict(event='error',reason='synthetic timeout'))
    write('board/round-1.events.jsonl',''.join(json.dumps(dict(row=r))+'\n' for r in rows).encode())


class AuditTests(unittest.TestCase):
    def test_failed_run_is_not_promotable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture(root);result=analysis.audit(root)
            self.assertTrue(result['restored']);self.assertFalse(result['campaign_complete']);self.assertFalse(result['promotion_eligible'])
            self.assertEqual(result['boots'][0]['completed'],2)

    def test_missing_recovery_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture(root)
            data=json.loads((root/'completion.json').read_text());data['original_boot_confirmed']=False
            (root/'completion.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):analysis.audit(root)

    def test_tampered_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture(root)
            (root/'sources/example.py').write_text('tampered')
            with self.assertRaises(ValueError):analysis.audit(root)
