import copy
import unittest
from analyze import FRAMES,MODES,ROUNDS,VARIANTS,PAD_OUTPUT_BYTES,summarize

TAGS=['CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','CONV_2D','PAD','DEPTHWISE_CONV_2D',
      'CONV_2D','CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','ADD']

def fixture(fast_pad_us=4000,fast_invoke_us=None):
    model={'nodes':[dict(index=i,op=tag,outputs=[dict(name=str(i),shape=[1],bytes=1)],macs=None) for i,tag in enumerate(TAGS)]}
    rows=[dict(event='block',phase='verify',variant=v,mode='plain',round=0,arena_address='same',arena_used=229820,arena_capacity=1048576)
          for v in VARIANTS]
    rows+=[dict(event='golden',frame=f) for f in FRAMES]
    for i in range(32):
        rows.append(dict(event='verify',input=i,frame=FRAMES[i] if i<3 else -1,pad_checks=1,pad_compared_bytes=PAD_OUTPUT_BYTES,
                         pad_mismatch_bytes=0,activation_bytes=4608,activation_mismatch_bytes=0,reference_fnv32=i,fast_fnv32=i))
    rows.append(dict(event='verify_done',inputs=32,pad_bytes_compared=32*PAD_OUTPUT_BYTES,all_exact=True))
    for location in ('psram','internal'):
        for kernel,us in (('memcpy',900),('fast_pad',1000),('reference_pad',14000)):
            rows+=[dict(event='calibration',location=location,kernel=kernel,iteration=i,bytes_in=110592,elapsed_us=us) for i in range(30)]
        rows.append(dict(event='calibration_check',location=location,fast_equals_reference=True))
    pad_us={'original':14600,'fast':fast_pad_us}
    for v in VARIANTS:
        for m in MODES:
            for r in ROUNDS:
                rows.append(dict(event='block',phase='measure',variant=v,mode=m,round=r,arena_address='same',arena_used=229820,arena_capacity=1048576))
                rows.append(dict(event='memory',phase='measure',variant=v,mode=m,round=r,internal_free=300000,psram_free=6000000,internal_min=290000))
                for f in FRAMES:
                    for i in range(30):
                        ops=[dict(event='operator',variant=v,round=r,frame=f,iteration=i,index=k,op=tag,
                                  elapsed_us=pad_us[v] if tag=='PAD' else 7000,esp_nn_us=5000 if 'CONV' in tag else 0,
                                  conv_calls=int(tag=='CONV_2D'),depthwise_calls=int(tag=='DEPTHWISE_CONV_2D'))
                             for k,tag in enumerate(TAGS)] if m=='profiled' else []
                        base=sum(7000 for t in TAGS if t!='PAD')+pad_us[v]+100
                        invoke=fast_invoke_us if (v=='fast' and m=='plain' and fast_invoke_us) else base
                        rows.append(dict(event='sample',variant=v,mode=m,round=r,frame=f,iteration=i,exact=True,conv_calls=6,
                                         depthwise_calls=3,fast_pad_calls=int(v=='fast'),invoke_us=invoke,
                                         operator_sum_us=sum(o['elapsed_us'] for o in ops),esp_nn_us=sum(o['esp_nn_us'] for o in ops)))
                        rows.extend(ops)
                rows.append(dict(event='block_done',variant=v,mode=m,round=r,samples=90))
    rows.append(dict(event='done',verify_inputs=32,samples=1080,operator_records=5940,warmup_invocations=180,all_activations_exact=True))
    return rows,model

class Integrity(unittest.TestCase):
    def test_complete_run_is_beneficial(self):
        rows,model=fixture();result,_=summarize(rows,model)
        self.assertEqual(result['verdict'],'beneficial')
        self.assertEqual(result['pad_node']['reduction_us'],10600)
        self.assertEqual(result['verification']['pad_bytes_compared'],32*PAD_OUTPUT_BYTES)
    def test_small_gain_is_not_beneficial(self):
        rows,model=fixture(fast_pad_us=13600);result,_=summarize(rows,model)
        self.assertEqual(result['verdict'],'not_beneficial')
        self.assertFalse(result['criteria']['invoke_plain_reduction_at_least_2ms'])
    def test_inconsistent_invoke_reduction_flagged(self):
        rows,model=fixture(fast_invoke_us=60000);result,_=summarize(rows,model)
        self.assertFalse(result['criteria']['invoke_reduction_consistent_with_pad'])
    def test_pad_mismatch_rejected(self):
        rows,model=fixture();next(r for r in rows if r['event']=='verify')['pad_mismatch_bytes']=1
        with self.assertRaisesRegex(ValueError,'PAD tensor mismatch'):summarize(rows,model)
    def test_missing_verification_rejected(self):
        rows,model=fixture();rows.remove(next(r for r in rows if r['event']=='verify' and r['input']==31))
        with self.assertRaisesRegex(ValueError,'Incomplete verification'):summarize(rows,model)
    def test_wrong_kernel_rejected(self):
        rows,model=fixture();next(r for r in rows if r['event']=='sample' and r['variant']=='fast')['fast_pad_calls']=0
        with self.assertRaisesRegex(ValueError,'Wrong PAD kernel'):summarize(rows,model)
    def test_missing_block_rejected(self):
        rows,model=fixture();rows.remove(next(r for r in rows if r['event']=='block_done'))
        with self.assertRaisesRegex(ValueError,'Missing completed block'):summarize(rows,model)
    def test_duplicate_sample_rejected(self):
        rows,model=fixture();rows.append(copy.deepcopy(next(r for r in rows if r['event']=='sample')))
        with self.assertRaisesRegex(ValueError,'Duplicate sample'):summarize(rows,model)
    def test_activation_mismatch_rejected(self):
        rows,model=fixture();next(r for r in rows if r['event']=='sample')['exact']=False
        with self.assertRaisesRegex(ValueError,'Activation mismatch'):summarize(rows,model)
    def test_calibration_difference_rejected(self):
        rows,model=fixture();next(r for r in rows if r['event']=='calibration_check')['fast_equals_reference']=False
        with self.assertRaisesRegex(ValueError,'Calibration outputs differ'):summarize(rows,model)

if __name__=='__main__':unittest.main()
