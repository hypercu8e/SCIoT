import hashlib
import tempfile
from pathlib import Path
import unittest
from analyze import MODEL_SHA,REFERENCE_SHA,FRAMES,summarize_round,summarize_allocation_failure,check_recovery
from prepare import check_network

def fixture():
    rows=[dict(event='boot',experiment='client_fit_benchmark',model_sha256=MODEL_SHA,reference_sha256=REFERENCE_SHA,cpu_mhz=240,psram_mhz=80,http=False),dict(event='ready'),dict(event='wifi_connected',has_ip=True),dict(event='camera_init',status=0)]
    def mem(stage,measuring):return dict(event='memory',stage=stage,measuring=measuring,internal_free=50000 if measuring else 200000,internal_min_free=48000 if measuring else 180000,largest_block=40000 if measuring else 170000)
    rows.append(mem('services_ready',False));rows.extend(dict(event='golden',frame=f) for f in FRAMES);rows.append(mem('before_internal_allocation',False));rows.append(mem('after_internal_allocation',True))
    rows.append(dict(event='candidate_allocated',activation_bytes=145760,guard_bytes_each=32,internal=True,input_internal=True,output_internal=True,persistent_psram=True,strip_rows=3,scratch_bytes=7520))
    rows.append(dict(event='validation',inputs=35,exact=True,guards=True));rows.append(mem('validation_done',True))
    for i in range(1000):
        rows.append(dict(event='sample',index=i,invoke_us=62500,acquisition_us=10000,local_cycle_us=75000,guards=True,wifi_connected=True,conv_calls=6,depthwise_calls=3,internal_free=50000,internal_min_free=48000,largest_block=40000))
        rows.append(mem('frame',True))
        if (i+1)%100==0:rows.append(dict(event='canonical_check',after_frames=i+1,inputs=3,exact=True,guards=True))
    rows.append(mem('end',True));rows.append(dict(event='done',camera_completed=1000,validation_inputs=35,canonical_checks=10,all_exact=True,guards=True,wifi_disconnections=0,heap_integrity=True,response_buffer_bytes=1760))
    return rows

class Analysis(unittest.TestCase):
    def test_complete(self):self.assertTrue(summarize_round(fixture())[0]['passed'])
    def test_early_reservation(self):
        rows=fixture()
        boot=dict(rows[0],allocation_order='early')
        before=next(r for r in rows if r['event']=='memory' and r['stage']=='before_internal_allocation')
        after=next(r for r in rows if r['event']=='memory' and r['stage']=='after_internal_allocation')
        services=dict(after,stage='services_ready')
        reserved=dict(event='arena_reserved',allocation_order='early',requested_bytes=145824,internal=True)
        skip=('services_ready','before_internal_allocation','after_internal_allocation')
        rest=[r for r in rows[4:] if not (r['event']=='memory' and r['stage'] in skip)]
        early=[boot,rows[1],before,reserved,after,rows[2],rows[3],services]+rest
        self.assertEqual(summarize_round(early)[0]['allocation_order'],'early')
        early.remove(reserved);early.insert(early.index(next(r for r in early if r['event']=='candidate_allocated')),reserved)
        with self.assertRaisesRegex(ValueError,'not reserved before'):summarize_round(early)

    def test_allocation_failure(self):
        rows=fixture();rows.insert(8,dict(event='error',reason='internal_allocation'))
        with self.assertRaisesRegex(ValueError,'Device error'):summarize_round(rows)
    def test_reserve(self):
        rows=fixture();next(r for r in rows if r['event']=='sample')['internal_min_free']=32767
        with self.assertRaisesRegex(ValueError,'reserve insufficient'):summarize_round(rows)
    def test_placement(self):
        rows=fixture();next(r for r in rows if r['event']=='candidate_allocated')['internal']=False
        with self.assertRaisesRegex(ValueError,'memory placement'):summarize_round(rows)
    def test_validation(self):
        rows=fixture();next(r for r in rows if r['event']=='validation')['exact']=False
        with self.assertRaisesRegex(ValueError,'validation failed'):summarize_round(rows)
    def test_missing_or_duplicate_frames(self):
        for duplicate in (False,True):
            rows=fixture();sample=next(r for r in rows if r['event']=='sample')
            if duplicate:rows.append(sample.copy())
            else:rows.remove(sample)
            with self.assertRaisesRegex(ValueError,'frames'):summarize_round(rows)
    def test_wifi_disconnected(self):
        rows=fixture();rows.insert(50,dict(event='wifi_disconnected',measuring=True))
        with self.assertRaisesRegex(ValueError,'Wi-Fi disconnected'):summarize_round(rows)
    def test_startup_disconnect_allowed(self):
        rows=fixture();rows.insert(2,dict(event='wifi_disconnected',measuring=False));self.assertTrue(summarize_round(rows)[0]['passed'])
    def test_guards(self):
        rows=fixture();next(r for r in rows if r['event']=='sample')['guards']=False
        with self.assertRaisesRegex(ValueError,'correctness'):summarize_round(rows)
    def test_late_canonical_mismatch(self):
        rows=fixture();next(r for r in rows if r['event']=='canonical_check')['exact']=False
        with self.assertRaisesRegex(ValueError,'Canonical'):summarize_round(rows)
    def test_missing_memory_trace(self):
        rows=fixture();rows.remove(next(r for r in rows if r['event']=='memory'))
        with self.assertRaisesRegex(ValueError,'memory trace'):summarize_round(rows)
    def test_recovery(self):
        c=dict(board='B',measurements_complete=True,rounds_completed=3,error=None,restore_error=None,original_boot_confirmed=True)
        h=dict(mac='24:ec:4a:0e:c3:14',restored=True,restored_digest_verified_before_boot=True)
        check_recovery(c,h)
        with self.assertRaisesRegex(ValueError,'recovery'):check_recovery(dict(c,original_boot_confirmed=False),h)
    def test_verified_negative_allocation(self):
        rows=fixture()
        rows=rows[:next(i for i,r in enumerate(rows) if r['event']=='memory' and r['stage']=='after_internal_allocation')]
        rows[-1]['largest_block']=124928;rows[-1]['internal_free']=219755
        rows.append(dict(event='error',reason='internal_allocation'))
        result,_=summarize_allocation_failure(rows)
        self.assertFalse(result['passed']);self.assertEqual(result['camera_frames'],0)
        rows.insert(-1,dict(event='sample'))
        with self.assertRaisesRegex(ValueError,'Contradictory'):summarize_allocation_failure(rows)

    def test_network_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'network.local.h';p.write_text('#define WIFI_SSID "CONFIGURE_ROUTER_SSID"\n#define WIFI_PASSWORD "CONFIGURE_ROUTER_PASSWORD"\n')
            with self.assertRaisesRegex(ValueError,'Configure router'):check_network(p)
            p.write_text('#define WIFI_SSID "test-network"\n#define WIFI_PASSWORD "test-only-password"\n');check_network(p)

if __name__=='__main__':unittest.main()
