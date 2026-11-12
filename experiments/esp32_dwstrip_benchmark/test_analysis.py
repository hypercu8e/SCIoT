import copy
import unittest
from analyze import FIT_LIMIT,FRAMES,MODES,ROUNDS,VARIANTS,choose,summarize

TAGS=['CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','CONV_2D','DEPTHWISE_CONV_2D',
      'CONV_2D','CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','ADD']
NODE_MAP={'nodes':[dict(index=i,op=t) for i,t in enumerate(TAGS)]}
PEAKS={'rows17':178688,'rows7':155168,'rows5':150464,'rows3':145760}
DW_US={'rows17':4700,'rows7':4800,'rows5':4900,'rows3':5200}

def fixture(peaks=PEAKS,dw=DW_US):
    rows=[dict(event='activation_peak',model='nopad',variant=v,cap=c,min_activation_bytes=peaks[v],arena_used_at_240k=peaks[v]+3000)
          for v,(c,_,_) in VARIANTS.items()]
    rows.append(dict(event='block',phase='reference',model='pad',variant='reference',memory='psram',mode='plain',round=0,
                     persistent_address='p',activation_address='x',activations_internal=False,arena_used=229836))
    rows+=[dict(event='golden',frame=f) for f in FRAMES]
    for v,(_,strip_rows,strips) in VARIANTS.items():
        cost=lambda k:dw[v] if k==4 else 6000
        for mode in MODES:
            for r in ROUNDS:
                rows.append(dict(event='block',phase='measure',model='nopad',variant=v,memory='internal',mode=mode,round=r,
                                 persistent_address='p',activation_address='i',activations_internal=True,arena_used=peaks[v]+3000))
                for f in FRAMES:
                    for i in range(30):
                        ops=[dict(event='operator',variant=v,round=r,frame=f,iteration=i,index=k,op=t,elapsed_us=cost(k),
                                  esp_nn_us=1000 if 'CONV' in t else 0,
                                  conv_calls=int(t=='CONV_2D'),depthwise_calls=int(t=='DEPTHWISE_CONV_2D'))
                             for k,t in enumerate(TAGS)] if mode=='profiled' else []
                        rows.append(dict(event='sample',variant=v,mode=mode,round=r,frame=f,iteration=i,exact=True,
                                         conv_calls=6,depthwise_calls=3,fast_pad_calls=0,strip_rows=strip_rows,strips=strips,
                                         invoke_us=sum(cost(k) for k in range(len(TAGS)))+100,
                                         operator_sum_us=sum(o['elapsed_us'] for o in ops),esp_nn_us=sum(o['esp_nn_us'] for o in ops)))
                        rows.extend(ops)
                rows.append(dict(event='block_done',variant=v,mode=mode,round=r,samples=90))
    rows.append(dict(event='done',samples=2160,operator_records=10800,warmup_invocations=360,all_activations_exact=True))
    return rows

class Integrity(unittest.TestCase):
    def test_complete_run(self):
        result,_=summarize(fixture(),NODE_MAP)
        self.assertEqual(result['plain_cost_vs_baseline_us']['rows3'],500)
        self.assertEqual(result['depthwise_cost_vs_baseline_us']['rows7'],100)
        self.assertFalse(result['fit']['fits_with_reserve']['rows17'])
        self.assertEqual(result['fit']['chosen'],'rows7')
        self.assertTrue(result['baseline_vs_nopad_benchmark']['activation_peak_equal'])
    def test_tie_prefers_smaller_peak(self):
        result,_=summarize(fixture(dw={'rows17':4700,'rows7':4800,'rows5':4840,'rows3':5200}),NODE_MAP)
        self.assertEqual(result['fit']['chosen'],'rows5')
    def test_nothing_fits(self):
        result,_=summarize(fixture(peaks={v:FIT_LIMIT+16 for v in VARIANTS}),NODE_MAP)
        self.assertIsNone(result['fit']['chosen']);self.assertEqual(result['fit']['next_step'],'free_client_internal_ram')
    def test_choose_limit_inclusive(self):
        self.assertEqual(choose({'rows17':FIT_LIMIT,'rows7':1,'rows5':1,'rows3':1},
                                {'rows17':100,'rows7':500,'rows5':600,'rows3':700}),'rows17')
    def test_wrong_strip_geometry_rejected(self):
        rows=fixture();next(r for r in rows if r['event']=='sample' and r['variant']=='rows5')['strips']=24
        with self.assertRaisesRegex(ValueError,'strip geometry'):summarize(rows,NODE_MAP)
    def test_wrong_cap_rejected(self):
        rows=fixture();rows[1]['cap']=9
        with self.assertRaisesRegex(ValueError,'Wrong cap'):summarize(rows,NODE_MAP)
    def test_pad_running_rejected(self):
        rows=fixture();next(r for r in rows if r['event']=='sample')['fast_pad_calls']=1
        with self.assertRaisesRegex(ValueError,'PAD executed'):summarize(rows,NODE_MAP)
    def test_psram_block_rejected(self):
        rows=fixture();next(r for r in rows if r['event']=='block' and r['phase']=='measure')['activations_internal']=False
        with self.assertRaisesRegex(ValueError,'internal RAM'):summarize(rows,NODE_MAP)
    def test_missing_peak_rejected(self):
        rows=fixture();rows.pop(0)
        with self.assertRaisesRegex(ValueError,'Missing activation peak'):summarize(rows,NODE_MAP)
    def test_activation_mismatch_rejected(self):
        rows=fixture();next(r for r in rows if r['event']=='sample')['exact']=False
        with self.assertRaisesRegex(ValueError,'Activation mismatch'):summarize(rows,NODE_MAP)
    def test_missing_block_rejected(self):
        rows=fixture();rows.remove(next(r for r in rows if r['event']=='block_done'))
        with self.assertRaisesRegex(ValueError,'Missing completed block'):summarize(rows,NODE_MAP)
    def test_duplicate_sample_rejected(self):
        rows=fixture();rows.append(copy.deepcopy(next(r for r in rows if r['event']=='sample')))
        with self.assertRaisesRegex(ValueError,'Duplicate sample'):summarize(rows,NODE_MAP)

if __name__=='__main__':unittest.main()
