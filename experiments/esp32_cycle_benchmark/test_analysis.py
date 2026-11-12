import unittest
from analyze import CAMERA,EMBEDDED,LUT_CHECKED,MAX_LOST,PARTS,PHASES,summarize

def fixture(cycle=None,lost=None,activation=None,mismatch=None):
    """cycle: {variant: camera cycle us}; lost: (phase, frames); activation/mismatch: phase to corrupt."""
    cycle=cycle or {0:300000,1:260000,2:290000,3:250000}
    rows=[];terminals=[];outcomes=[];t=0.0
    for index,variant in enumerate(PHASES,1):
        v=int(variant)
        def add(row):
            nonlocal t;t+=1;rows.append(dict(host_monotonic=t,phase=index,mode=variant,row=row))
        add(dict(event='variant',variant=v,lut=bool(v&1),keep_alive=bool(v&2),lut_build_us=1,lut_checked=LUT_CHECKED,
                 lut_mismatches=1 if mismatch==index else 0,lut_sha_fnv32=7))
        add(dict(event='registration',success=True))
        for i in range(EMBEDDED):
            add(dict(event='sample',source='embedded',frame=48+i%3,reconnects=0,rssi_dbm=-50,
                     activation_fnv32=(99 if activation==index else i%3),response_fnv32=i%3,**{k:1 for k in PARTS}))
            terminals.append(dict(status=200,monotonic=t))
        n=CAMERA-(lost[1] if lost and lost[0]==index else 0)
        for i in range(n):
            add(dict(event='sample',source='camera',frame=1000+i,reconnects=0,rssi_dbm=-50,activation_fnv32=i,response_fnv32=i,
                     **{k:(cycle[v] if k=='observed_cycle_us' else 1000) for k in PARTS}))
            terminals.append(dict(status=200,monotonic=t))
        for i in range(CAMERA-n):
            add(dict(event='error',reason='http_response'));terminals.append(dict(status=408,monotonic=t))
        add(dict(event='done',camera_attempted=CAMERA,camera_completed=n))
        outcomes.append(dict(phase=index,mode=variant,ok=True,reason=None))
    return rows,terminals,outcomes

class CycleAnalysis(unittest.TestCase):
    def test_levers(self):
        r=summarize(*fixture())
        self.assertTrue(r['outputs_identical'])
        self.assertEqual({k:v['verdict'] for k,v in r['levers'].items()},{'lut':'faster','keep_alive':'faster','both':'faster'})
        self.assertEqual(r['levers']['lut']['cycle_delta_mean_us'],-40000)
    def test_small_gain_not_confirmed(self):
        r=summarize(*fixture(cycle={0:300000,1:297000,2:300000,3:250000}))
        self.assertEqual(r['levers']['lut']['verdict'],'not_confirmed')
        self.assertEqual(r['levers']['keep_alive']['verdict'],'not_confirmed')
    def test_few_lost_frames_tolerated(self):
        self.assertTrue(summarize(*fixture(lost=(3,MAX_LOST)))['all_phases_functional'])
    def test_many_lost_frames(self):
        r=summarize(*fixture(lost=(3,MAX_LOST+1)))
        self.assertEqual(r['levers']['lut']['verdict'],'environment_problem')
    def test_changed_activation_invalidates(self):
        r=summarize(*fixture(activation=5))
        self.assertFalse(r['outputs_identical']);self.assertEqual(r['levers']['lut']['verdict'],'invalid')
    def test_lut_mismatch_fails_phase(self):
        self.assertFalse(summarize(*fixture(mismatch=2))['phases'][1]['functional_ok'])

if __name__=='__main__':unittest.main()
