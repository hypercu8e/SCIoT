import copy
import unittest
from analyze import FRAMES,MODES,ROUNDS,VARIANTS,summarize

TAGS=['CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','CONV_2D','PAD','DEPTHWISE_CONV_2D',
      'CONV_2D','CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','ADD']

def fixture(internal_conv_us=6000,internal_pad_us=300):
    """PSRAM: 7 ms per non-PAD node, PAD 5 ms. Internal: values given."""
    model={'nodes':[dict(index=i,op=tag,outputs=[dict(name=str(i),shape=[1],bytes=1)],macs=None) for i,tag in enumerate(TAGS)]}
    rows=[dict(event='golden',frame=f) for f in FRAMES]
    rows.append(dict(event='heap',stage='boot',internal_free=380000,internal_largest_block=300000,internal_min=379000,psram_free=8000000))
    cost={'psram':(7000,5000),'internal':(internal_conv_us,internal_pad_us)}
    for v in VARIANTS:
        for m in MODES:
            for r in ROUNDS:
                rows.append(dict(event='block',variant=v,mode=m,round=r,persistent_address='p',activation_address=v,
                                 activations_internal=v=='internal',persistent_capacity=65536,activation_capacity=245760,arena_used=229820))
                rows.append(dict(event='memory',variant=v,mode=m,round=r,internal_free=130000,psram_free=7000000,internal_min=129000))
                other,pad=cost[v]
                for f in FRAMES:
                    for i in range(30):
                        ops=[dict(event='operator',variant=v,round=r,frame=f,iteration=i,index=k,op=tag,
                                  elapsed_us=pad if tag=='PAD' else other,esp_nn_us=other//2 if 'CONV' in tag else 0,
                                  conv_calls=int(tag=='CONV_2D'),depthwise_calls=int(tag=='DEPTHWISE_CONV_2D'))
                             for k,tag in enumerate(TAGS)] if m=='profiled' else []
                        rows.append(dict(event='sample',variant=v,mode=m,round=r,frame=f,iteration=i,exact=True,conv_calls=6,
                                         depthwise_calls=3,fast_pad_calls=1,invoke_us=other*10+pad+100,
                                         operator_sum_us=sum(o['elapsed_us'] for o in ops),esp_nn_us=sum(o['esp_nn_us'] for o in ops)))
                        rows.extend(ops)
                rows.append(dict(event='block_done',variant=v,mode=m,round=r,samples=90))
    rows.append(dict(event='done',samples=1080,operator_records=5940,warmup_invocations=180,all_activations_exact=True))
    return rows,model

class Integrity(unittest.TestCase):
    def test_large_non_pad_gain_pursues_memory(self):
        rows,model=fixture();result,_=summarize(rows,model)
        self.assertEqual(result['non_pad_gain_us'],10000)
        self.assertEqual(result['pad_gain_us'],4700)
        self.assertEqual(result['decision_rule']['decision'],'pursue_memory')
        self.assertTrue(result['internal_faster_every_round_and_frame'])
    def test_gain_only_on_pad_ports_to_client(self):
        rows,model=fixture(internal_conv_us=6600);result,_=summarize(rows,model)
        self.assertEqual(result['non_pad_gain_us'],4000)
        self.assertEqual(result['decision_rule']['decision'],'port_to_client')
    def test_wrong_memory_rejected(self):
        rows,model=fixture();next(r for r in rows if r['event']=='block' and r['variant']=='internal')['activations_internal']=False
        with self.assertRaisesRegex(ValueError,'wrong memory'):summarize(rows,model)
    def test_unavailable_internal_arena_rejected(self):
        rows,model=fixture();rows.append(dict(event='internal_arena_unavailable',requested=245760,internal_largest_block=200000))
        with self.assertRaisesRegex(ValueError,'Internal arena unavailable'):summarize(rows,model)
    def test_missing_variant_block_rejected(self):
        rows,model=fixture();rows=[r for r in rows if not (r['event']=='block' and r['variant']=='internal' and r['round']==3 and r['mode']=='plain')]
        with self.assertRaisesRegex(ValueError,'Incomplete blocks'):summarize(rows,model)
    def test_moved_activation_arena_rejected(self):
        rows,model=fixture();next(r for r in rows if r['event']=='block' and r['variant']=='psram')['activation_address']='other'
        with self.assertRaisesRegex(ValueError,'Activation arena moved'):summarize(rows,model)
    def test_activation_mismatch_rejected(self):
        rows,model=fixture();next(r for r in rows if r['event']=='sample')['exact']=False
        with self.assertRaisesRegex(ValueError,'Activation mismatch'):summarize(rows,model)
    def test_duplicate_sample_rejected(self):
        rows,model=fixture();rows.append(copy.deepcopy(next(r for r in rows if r['event']=='sample')))
        with self.assertRaisesRegex(ValueError,'Duplicate sample'):summarize(rows,model)

if __name__=='__main__':unittest.main()
