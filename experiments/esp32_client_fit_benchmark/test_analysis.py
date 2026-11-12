import unittest
from analyze import CAMERA,EMBEDDED,MIN_FREE_FLOOR,PHASES,RESERVE_BYTES,summarize

def fixture(r_min_free=40000,error_phase=None):
    rows=[];terminals=[];t=0.0;outcomes=[]
    for index,mode in enumerate(PHASES,1):
        def add(row):
            nonlocal t;t+=1;rows.append(dict(host_monotonic=t,phase=index,mode=mode,row=row))
        held=mode=='R';free=r_min_free if held else r_min_free+RESERVE_BYTES
        add(dict(event='reserve',mode=mode,requested=RESERVE_BYTES if held else 0,held=held))
        add(dict(event='registration',success=True))
        for source,count in (('embedded',EMBEDDED),('camera',CAMERA)):
            for i in range(count):
                add(dict(event='sample',source=source,observed_cycle_us=250000,request_response_us=80000,invoke_us=84000))
                terminals.append(dict(event='terminal',status=200,monotonic=t))
            if source=='embedded':add(dict(event='camera_init',status=0))
        add(dict(event='memory',reserve_held=held,internal_free=free+5000,internal_min_free=free,internal_largest_block=free-4000))
        if error_phase==index:add(dict(event='error',reason='http_response'))
        add(dict(event='done',camera_attempted=CAMERA,camera_completed=CAMERA))
        outcomes.append(dict(phase=index,mode=mode,ok=True,reason=None))
    return rows,terminals,outcomes

class FitAnalysis(unittest.TestCase):
    def test_fits(self):
        result=summarize(*fixture())
        self.assertEqual(result['verdict'],'fits')
        self.assertEqual(result['internal_min_free']['R'],[40000,40000])
    def test_low_headroom(self):
        result=summarize(*fixture(r_min_free=MIN_FREE_FLOOR-1))
        self.assertEqual(result['verdict'],'does_not_fit')
    def test_error_in_reserve_phase(self):
        result=summarize(*fixture(error_phase=2))
        self.assertEqual(result['verdict'],'does_not_fit')
    def test_error_in_control_phase(self):
        result=summarize(*fixture(error_phase=1))
        self.assertEqual(result['verdict'],'environment_problem')
    def test_request_outside_phases_rejected(self):
        rows,terminals,outcomes=fixture();terminals.append(dict(event='terminal',status=200,monotonic=-1))
        with self.assertRaisesRegex(ValueError,'outside phases'):summarize(rows,terminals,outcomes)
    def test_wrong_reserve_rejected(self):
        rows,terminals,outcomes=fixture();next(r for r in rows if r['phase']==2)['row']['held']=False
        with self.assertRaisesRegex(ValueError,'wrong reserve'):summarize(rows,terminals,outcomes)

if __name__=='__main__':unittest.main()
