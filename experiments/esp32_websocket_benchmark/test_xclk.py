import unittest
from analyze_xclk import analyze_boot,classify

def fixture():
    rows=[dict(event='validation',inputs=35,exact=True,guards=True),dict(event='camera_init',status=0),dict(event='xclk_camera_paused',buffers_retained=True,clock_not_disabled=True)]
    for phase,name in enumerate(('baseline','on_1','off_1','on_2','off_2')):
        on=phase in (1,3)
        if phase:rows.append(dict(event='xclk_gate',phase=phase,enabled=on,signal_index=149 if on else 256,route_verified=True,buffers_retained=True,gpio=15,output_latch_low=True))
        rows.append(dict(event='xclk_phase_begin',phase=phase,name=name,camera_initialized=phase>0,xclk_enabled=on,internal_min_free=48000))
        for role in ('gateway','laptop'):
            for i in range(1,51):rows.append(dict(event='xclk_ping',phase=phase,target=role,sequence=i,received=True,elapsed_ms=500 if on else 5))
            rows.append(dict(event='xclk_ping_summary',phase=phase,target=role,attempted=50,sent=50,received=50))
    rows.append(dict(event='done',experiment='xclk_diagnostic',phases_completed=5,probes_expected=500,guards=True,heap_integrity=True))
    return rows

class XclkTests(unittest.TestCase):
    def test_requires_three_complete_reversible_boots(self):
        b=analyze_boot(fixture());self.assertTrue(b['complete'])
        self.assertEqual(classify([b]*3,True)['conclusion'],'xclk_effect_reproduced')
        self.assertEqual(classify([b]*2,True)['conclusion'],'inconclusive')
        self.assertEqual(classify([b]*3,False)['conclusion'],'inconclusive')

    def test_partial_and_duplicate_records_cannot_pass(self):
        rows=fixture();rows.pop();self.assertFalse(analyze_boot(rows)['complete'])
        rows=fixture();r=next(r for r in rows if r['event']=='xclk_ping');r['sequence']=2
        self.assertFalse(analyze_boot(rows)['complete'])

    def test_wrong_gpio_route_rejected(self):
        rows=fixture();next(r for r in rows if r['event']=='xclk_gate' and not r['enabled'])['signal_index']=149
        self.assertFalse(analyze_boot(rows)['complete'])

    def test_no_effect_is_inconclusive(self):
        rows=fixture()
        for r in rows:
            if r['event']=='xclk_ping':r['elapsed_ms']=5
        b=analyze_boot(rows);self.assertTrue(b['complete']);self.assertEqual(classify([b]*3,True)['conclusion'],'inconclusive')

    def test_timeouts_are_loss_not_latency(self):
        rows=fixture()
        for r in rows:
            if r['event']=='xclk_ping' and r['phase']==2 and r['sequence']==50:r.update(received=False,elapsed_ms=1000)
            if r['event']=='xclk_ping_summary' and r['phase']==2:r['received']=49
        b=analyze_boot(rows);self.assertTrue(b['complete'])
        self.assertEqual(b['phases']['off_1']['gateway']['p95_ms'],5)

    def test_both_reversals_must_recover(self):
        rows=fixture()
        for r in rows:
            if r['event']=='xclk_ping' and r['phase']==4:r['elapsed_ms']=500
        b=analyze_boot(rows);self.assertTrue(b['complete']);self.assertEqual(classify([b]*3,True)['conclusion'],'inconclusive')

    def test_summary_mismatch_and_ram_violation_rejected(self):
        rows=fixture();next(r for r in rows if r['event']=='xclk_ping_summary')['received']=49
        self.assertFalse(analyze_boot(rows)['complete'])
        rows=fixture();next(r for r in rows if r['event']=='xclk_phase_begin')['internal_min_free']=32000
        self.assertFalse(analyze_boot(rows)['complete'])

if __name__=='__main__':unittest.main()
