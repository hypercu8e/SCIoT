import copy
import unittest
from analyze import FIT_LIMIT,FRAMES,MODES,ROUNDS,VARIANTS,summarize

PAD_TAGS=['CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','CONV_2D','PAD','DEPTHWISE_CONV_2D',
          'CONV_2D','CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','ADD']
NOPAD_TAGS=[t for t in PAD_TAGS if t!='PAD']

def node_map(tags):
    return {'nodes':[dict(index=i,op=t,outputs=[dict(name=str(i),shape=[1],bytes=1)],macs=None) for i,t in enumerate(tags)]}

def fixture(nopad_peak=150000,nopad_dw_us=6000):
    maps={'pad':node_map(PAD_TAGS),'nopad':node_map(NOPAD_TAGS)}
    rows=[dict(event='activation_peak',model='pad',min_activation_bytes=226000,arena_used_at_240k=229836),
          dict(event='activation_peak',model='nopad',min_activation_bytes=nopad_peak,arena_used_at_240k=nopad_peak+4000)]
    rows.append(dict(event='block',phase='reference',model='pad',memory='psram',mode='plain',round=0,persistent_address='p',
                     activation_address='psram',activations_internal=False,arena_used=229836))
    rows+=[dict(event='golden',frame=f) for f in FRAMES]
    for m,mem in VARIANTS:
        tags=PAD_TAGS if m=='pad' else NOPAD_TAGS
        def cost(k,tag):
            if tag=='PAD':return 5000
            if m=='pad' and k==5:return 9000
            if m=='nopad' and k==4:return nopad_dw_us
            return 7000
        for mode in MODES:
            for r in ROUNDS:
                rows.append(dict(event='block',phase='measure',model=m,memory=mem,mode=mode,round=r,persistent_address='p',
                                 activation_address=mem,activations_internal=mem=='internal',arena_used=229836 if m=='pad' else 160000))
                for f in FRAMES:
                    for i in range(30):
                        ops=[dict(event='operator',model=m,memory=mem,round=r,frame=f,iteration=i,index=k,op=t,
                                  elapsed_us=cost(k,t),esp_nn_us=1000 if 'CONV' in t else 0,
                                  conv_calls=int(t=='CONV_2D'),depthwise_calls=int(t=='DEPTHWISE_CONV_2D'))
                             for k,t in enumerate(tags)] if mode=='profiled' else []
                        rows.append(dict(event='sample',model=m,memory=mem,mode=mode,round=r,frame=f,iteration=i,exact=True,
                                         conv_calls=6,depthwise_calls=3,fast_pad_calls=int(m=='pad'),
                                         invoke_us=sum(cost(k,t) for k,t in enumerate(tags))+100,
                                         operator_sum_us=sum(o['elapsed_us'] for o in ops),esp_nn_us=sum(o['esp_nn_us'] for o in ops)))
                        rows.extend(ops)
                rows.append(dict(event='block_done',model=m,memory=mem,mode=mode,round=r,samples=90))
    rows.append(dict(event='done',samples=2160,operator_records=11340,warmup_invocations=360,all_activations_exact=True))
    return rows,maps

class Integrity(unittest.TestCase):
    def test_complete_run(self):
        rows,maps=fixture();result,_=summarize(rows,maps)
        self.assertEqual(result['nopad_plain_gain_us']['psram'],8000)
        self.assertEqual(result['pad_pair_vs_merged_depthwise']['internal']['gain_us'],8000)
        self.assertTrue(result['fit']['fits_with_reserve'])
        self.assertEqual(result['fit']['next_step'],'client_fit_test')
    def test_large_peak_needs_client_ram(self):
        rows,maps=fixture(nopad_peak=FIT_LIMIT+16);result,_=summarize(rows,maps)
        self.assertEqual(result['fit']['next_step'],'free_client_internal_ram')
    def test_slower_merged_depthwise_reported(self):
        rows,maps=fixture(nopad_dw_us=20000);result,_=summarize(rows,maps)
        self.assertFalse(result['nopad_faster_every_round_and_frame']['psram'])
    def test_pad_running_in_nopad_rejected(self):
        rows,maps=fixture();next(r for r in rows if r['event']=='sample' and r['model']=='nopad')['fast_pad_calls']=1
        with self.assertRaisesRegex(ValueError,'Wrong PAD execution'):summarize(rows,maps)
    def test_missing_peak_rejected(self):
        rows,maps=fixture();rows.pop(1)
        with self.assertRaisesRegex(ValueError,'Missing activation peak'):summarize(rows,maps)
    def test_wrong_memory_rejected(self):
        rows,maps=fixture();next(r for r in rows if r['event']=='block' and r['memory']=='internal')['activations_internal']=False
        with self.assertRaisesRegex(ValueError,'wrong memory'):summarize(rows,maps)
    def test_missing_block_rejected(self):
        rows,maps=fixture();rows.remove(next(r for r in rows if r['event']=='block_done'))
        with self.assertRaisesRegex(ValueError,'Missing completed block'):summarize(rows,maps)
    def test_activation_mismatch_rejected(self):
        rows,maps=fixture();next(r for r in rows if r['event']=='sample' and r['model']=='nopad')['exact']=False
        with self.assertRaisesRegex(ValueError,'Activation mismatch'):summarize(rows,maps)
    def test_duplicate_sample_rejected(self):
        rows,maps=fixture();rows.append(copy.deepcopy(next(r for r in rows if r['event']=='sample')))
        with self.assertRaisesRegex(ValueError,'Duplicate sample'):summarize(rows,maps)

if __name__=='__main__':unittest.main()
