import hashlib
import tempfile
from pathlib import Path
import unittest
from analyze import (VARIANTS,MEMORIES,MODES,ROUNDS,FRAMES,TAGS,FIT_LIMIT,
                     summarize,check_recovery,verify_sources)

def fixture():
    rows=[]
    for v in VARIANTS:
        effective=v or 17
        rows.append(dict(event='activation_peak',variant=v,min_activation_bytes=178688 if not v else 138240+effective*2352+32,
                         effective_rows=effective,scratch_bytes=432+effective*2352+32))
        # Round arena size to 16.
        rows[-1]['min_activation_bytes']=(rows[-1]['min_activation_bytes']+15)//16*16
        peak=rows[-1]['min_activation_bytes']
        for m in MEMORIES:
            rows.append(dict(event='validation',variant=v,memory=m,inputs=35,exact=True,guards=True))
            for mode in MODES:
                for r in ROUNDS:
                    rows.append(dict(event='block',variant=v,memory=m,mode=mode,round=r,arena_bytes=peak,arena_used=peak+4000,activation_address=m,persistent_address='p'))
                    for f in FRAMES:
                        for i in range(30):
                            rows.append(dict(event='sample',variant=v,memory=m,mode=mode,round=r,frame=f,iteration=i,invoke_us=62000 if m=='internal' else 83000,exact=True,guards=True,conv_calls=6,depthwise_calls=3,operator_sum_us=10000 if mode=='profiled' else 0))
                            if mode=='profiled':
                                rows.extend(dict(event='operator',variant=v,memory=m,round=r,frame=f,iteration=i,index=n,op=t,elapsed_us=1000,esp_nn_us=500) for n,t in enumerate(TAGS))
                    rows.append(dict(event='block_done',variant=v,memory=m,mode=mode,round=r))
    rows.extend(dict(event='golden',frame=f) for f in FRAMES)
    rows.append(dict(event='done',samples=5400,operator_records=27000,warmup_invocations=900,all_activations_exact=True))
    return rows

class Audit(unittest.TestCase):
    def test_tie_prefers_memory(self):
        r=summarize(fixture());self.assertEqual(r['selected_variant'],3)
    def test_fastest_within_budget(self):
        rows=fixture()
        for r in rows:
            if r['event']=='sample' and r['variant']==7:r['invoke_us']*=.96
        self.assertEqual(summarize(rows)['selected_variant'],7)
    def test_budget_rejects_fastest(self):
        rows=fixture()
        for r in rows:
            if r['event']=='activation_peak' and r['variant']!=0:r['min_activation_bytes']=(FIT_LIMIT//16+1)*16
            if r['event']=='block' and r['variant']!=0:r['arena_bytes']=(FIT_LIMIT//16+1)*16
        self.assertIsNone(summarize(rows)['selected_variant'])
    def test_slow_round_rejected(self):
        rows=fixture()
        for r in rows:
            if r['event']=='sample' and r['variant']==3 and r['round']==2:r['invoke_us']*=1.06
        result=summarize(rows);self.assertFalse(result['decisions']['3']['timing_within_5pct_each_round'])
    def test_missing_sample(self):
        rows=fixture();rows.remove(next(r for r in rows if r['event']=='sample'))
        with self.assertRaisesRegex(ValueError,'Incomplete sample'):summarize(rows)
    def test_duplicate_sample(self):
        rows=fixture();rows.append(next(r for r in rows if r['event']=='sample').copy())
        with self.assertRaisesRegex(ValueError,'Duplicate sample'):summarize(rows)
    def test_wrong_variant(self):
        rows=fixture();next(r for r in rows if r['event']=='activation_peak')['effective_rows']=3
        with self.assertRaisesRegex(ValueError,'scratch variant'):summarize(rows)
    def test_mismatch_and_guard(self):
        for field in ('exact','guards'):
            rows=fixture();next(r for r in rows if r['event']=='sample')[field]=False
            with self.assertRaisesRegex(ValueError,'correctness'):summarize(rows)
    def test_missing_operator(self):
        rows=fixture();rows.remove(next(r for r in rows if r['event']=='operator'))
        with self.assertRaisesRegex(ValueError,'Incomplete operator'):summarize(rows)
    def test_missing_block_done(self):
        rows=fixture();rows.remove(next(r for r in rows if r['event']=='block_done'))
        with self.assertRaisesRegex(ValueError,'Incomplete block_done'):summarize(rows)
    def test_audit_uses_captured_sources_and_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            source=run/'sources/experiments/example/README.md'
            source.parent.mkdir(parents=True);source.write_bytes(b'captured source')
            firmware=run/'firmware/firmware.bin'
            firmware.parent.mkdir();firmware.write_bytes(b'installed binary')
            hashes={'experiments/example/README.md':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'experiments/example/idf/.pio/build/espnn/firmware.bin':hashlib.sha256(firmware.read_bytes()).hexdigest()}
            verify_sources(run,hashes)
            source.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'Captured source'):verify_sources(run,hashes)

    def test_recovery_failure(self):
        c=dict(board='B',measurements_complete=True,error=None,restore_error=None,original_boot_confirmed=True)
        h=dict(mac='24:ec:4a:0e:c3:14',restored=True,restored_digest_verified_before_boot=True)
        check_recovery(c,h)
        for key in ('restored','restored_digest_verified_before_boot'):
            with self.assertRaisesRegex(ValueError,'recovery incomplete'):check_recovery(c,dict(h,**{key:False}))
        with self.assertRaisesRegex(ValueError,'recovery incomplete'):check_recovery(dict(c,original_boot_confirmed=False),h)

if __name__=='__main__':unittest.main()
