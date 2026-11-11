import copy
import unittest
from analyze import FRAMES,summarize

class Integrity(unittest.TestCase):
    def fixture(self):
        tags=['CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','CONV_2D','PAD','DEPTHWISE_CONV_2D',
              'CONV_2D','CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','ADD']
        model={'nodes':[dict(index=i,op=tag,outputs=[dict(name=str(i),shape=[1],bytes=1)],macs=None)
                        for i,tag in enumerate(tags)]}
        rows=[dict(event='golden',frame=f) for f in FRAMES]
        for mode in ('plain','profiled'):
            for rep in (1,2,3):
                rows.append(dict(event='block',mode=mode,round=rep,arena_address='same',arena_used=300000,arena_capacity=1048576))
                for frame in FRAMES:
                    for iteration in range(30):
                        ops=[dict(event='operator',round=rep,frame=frame,iteration=iteration,index=i,op=tag,
                                  elapsed_us=(i+1)*10,esp_nn_us=(i+1)*5 if 'CONV' in tag else 0,
                                  conv_calls=int(tag=='CONV_2D'),depthwise_calls=int(tag=='DEPTHWISE_CONV_2D'))
                             for i,tag in enumerate(tags)] if mode=='profiled' else []
                        rows.append(dict(event='sample',mode=mode,round=rep,frame=frame,iteration=iteration,
                                         exact=True,conv_calls=6,depthwise_calls=3,invoke_us=700,
                                         operator_sum_us=sum(v['elapsed_us'] for v in ops),esp_nn_us=sum(v['esp_nn_us'] for v in ops)))
                        rows.extend(ops)
                rows.append(dict(event='block_done',mode=mode,round=rep,samples=90))
        rows.append(dict(event='done',samples=540,operator_records=2970,all_activations_exact=True))
        return rows,model
    def test_complete_attribution(self):
        rows,model=self.fixture();result,_=summarize(rows,model)
        self.assertEqual(result['measured_invocations'],540)
        self.assertAlmostEqual(sum(v['share_of_invoke_pct'] for v in result['nodes'])+result['outside_operator_share_pct'],100)
    def test_missing_operator_rejected(self):
        rows,model=self.fixture();rows.pop(next(i for i,v in enumerate(rows) if v['event']=='operator'))
        with self.assertRaisesRegex(ValueError,'Incomplete operator'):summarize(rows,model)
    def test_duplicate_sample_rejected(self):
        rows,model=self.fixture();rows.append(copy.deepcopy(next(v for v in rows if v['event']=='sample')))
        with self.assertRaisesRegex(ValueError,'Duplicate sample'):summarize(rows,model)
    def test_kernel_time_outside_layer_rejected(self):
        rows,model=self.fixture();op=next(v for v in rows if v['event']=='operator');op['esp_nn_us']=op['elapsed_us']+1
        with self.assertRaisesRegex(ValueError,'Kernel outside'):summarize(rows,model)
    def test_activation_mismatch_rejected(self):
        rows,model=self.fixture();next(v for v in rows if v['event']=='sample')['exact']=False
        with self.assertRaisesRegex(ValueError,'Activation mismatch'):summarize(rows,model)

if __name__=='__main__':unittest.main()
