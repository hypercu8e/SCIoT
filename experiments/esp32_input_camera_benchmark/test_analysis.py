import copy
import unittest
from analyze import choose, percentile, confirm_two

class Selection(unittest.TestCase):
    def stats(self):
        result={}
        for r in (1,2,3):
            for name,value in [('reference_hold',250),('lut_hold',200),('reference_early',245),('lut_early',180)]:
                result[f'single_r{r}_{name}']={'A':{'memory_stable':True,'metrics_ms':{
                    'observed_cycle_us':{'p50':value,'p95':value+20},'age_at_result_us':{'p95':value+100}}}}
        return result
    def test_fastest_valid(self): self.assertEqual(choose(self.stats()),3)
    def test_reject_old_frame(self):
        s=self.stats()
        for r in (1,2,3): s[f'single_r{r}_lut_early']['A']['metrics_ms']['age_at_result_us']['p95']=900
        self.assertEqual(choose(s),1)
    def test_reject_memory_loss(self):
        s=self.stats();s['single_r1_lut_early']['A']['memory_stable']=False
        self.assertEqual(choose(s),1)
    def test_no_candidate(self):
        s=self.stats()
        for k,v in s.items():
            if not k.endswith('reference_hold'): v['A']['metrics_ms']['observed_cycle_us']['p50']=249
        self.assertIsNone(choose(s))
    def test_percentile(self): self.assertEqual(percentile([0,10],95),9.5)
    def test_lut_only_without_other_variants(self):
        s={k:v for k,v in self.stats().items() if k.endswith(('reference_hold','lut_hold'))}
        self.assertEqual(choose(s,variants=(1,)),1)
    def test_two_board_regression_blocks_confirmation(self):
        s=self.stats()
        base=copy.deepcopy(s['single_r1_reference_hold']['A'])
        trial=copy.deepcopy(s['single_r1_lut_hold']['A'])
        base['frames']=trial['frames']=1000
        stats={'two_reference_hold':{'A':copy.deepcopy(base),'B':copy.deepcopy(base)},
               'two_lut_hold':{'A':copy.deepcopy(trial),'B':copy.deepcopy(trial)}}
        self.assertTrue(all(v['passed'] for v in confirm_two(stats,1).values()))
        stats['two_lut_hold']['B']['metrics_ms']['age_at_result_us']['p95']=900
        result=confirm_two(stats,1)
        self.assertTrue(result['A']['passed'])
        self.assertFalse(result['B']['passed'])

if __name__=='__main__': unittest.main()
