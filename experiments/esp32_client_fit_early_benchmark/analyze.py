"""Audit three camera/Wi-Fi boots, including actual allocation and restoration."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ARENA=145760
RESERVE=32768
MODEL_SHA='43419ffa6fd970cf705ee730fce32a51436c32d0248254b34215a4ee07853b97'
REFERENCE_SHA='d41048c7accf408e57d1f6a7882ee5acebd1e6d3e9a0ba008746481cfb05b30c'
FRAMES=(48,96,145)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def one(rows,event):
    found=[r for r in rows if r['event']==event]
    if len(found)!=1:raise ValueError('Missing or duplicate '+event)
    return found[0]

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def summarize_round(rows):
    if any(r['event']=='error' for r in rows):raise ValueError('Device error')
    boot=one(rows,'boot')
    if any(boot.get(k)!=v for k,v in dict(experiment='client_fit_benchmark',model_sha256=MODEL_SHA,reference_sha256=REFERENCE_SHA,cpu_mhz=240,psram_mhz=80,http=False).items()):raise ValueError('Wrong runtime')
    order=boot.get('allocation_order','late')
    if order not in ('early','late'):raise ValueError('Unknown allocation order')
    one(rows,'ready')
    if not one(rows,'wifi_connected')['has_ip']:raise ValueError('Wi-Fi not connected')
    if one(rows,'camera_init')['status']!=0:raise ValueError('Camera initialization failed')
    candidate=one(rows,'candidate_allocated')
    expected=dict(activation_bytes=ARENA,guard_bytes_each=32,internal=True,input_internal=True,output_internal=True,persistent_psram=True,strip_rows=3,scratch_bytes=7520)
    if any(candidate.get(k)!=v for k,v in expected.items()):raise ValueError('Wrong arena or memory placement')
    validation=one(rows,'validation')
    if any(validation.get(k)!=v for k,v in dict(inputs=35,exact=True,guards=True).items()):raise ValueError('Output validation failed')
    if any(r['event']=='wifi_disconnected' and r.get('measuring',True) for r in rows):raise ValueError('Wi-Fi disconnected during measurement')
    samples=[r for r in rows if r['event']=='sample']
    if len(samples)!=1000 or [r['index'] for r in samples]!=list(range(1000)):raise ValueError('Missing, duplicate or reordered frames')
    checks=[r for r in rows if r['event']=='canonical_check']
    if [r['after_frames'] for r in checks]!=list(range(100,1001,100)) or any(r.get('inputs')!=3 or not r.get('exact') or not r.get('guards') for r in checks):raise ValueError('Canonical validation failed')
    for s in samples:
        if not s['guards'] or not s['wifi_connected'] or (s['conv_calls'],s['depthwise_calls'])!=(6,3):raise ValueError('Sample correctness failed')
        if s['invoke_us']<=0 or s['acquisition_us']<0 or s['local_cycle_us']<s['invoke_us']+s['acquisition_us']:raise ValueError('Invalid timings')
    memories=[r for r in rows if r['event']=='memory']
    stages=[r['stage'] for r in memories]
    expected_stages=(['before_internal_allocation','after_internal_allocation','services_ready','validation_done'] if order=='early' else ['services_ready','before_internal_allocation','after_internal_allocation','validation_done'])
    if stages!=expected_stages+['frame']*1000+['end']:raise ValueError('Incomplete memory trace')
    for r in memories:
        expected_measuring=r['stage']!='before_internal_allocation' if order=='early' else r['stage'] not in ('services_ready','before_internal_allocation')
        if r.get('measuring')!=expected_measuring:raise ValueError('Wrong memory observation window')
    measured=[r for r in memories if r['measuring']]+samples
    if any(r['internal_free']<RESERVE or r['internal_min_free']<RESERVE for r in measured):raise ValueError('Internal reserve insufficient')
    if any(not 0<=r['largest_block']<=r['internal_free'] or not 0<=r['internal_min_free']<=r['internal_free'] for r in memories+samples):raise ValueError('Invalid heap metrics')
    before=next(r for r in memories if r['stage']=='before_internal_allocation')
    if before['largest_block']<ARENA+64:raise ValueError('Contiguous allocation evidence inconsistent')
    # Require that the actual arena allocation follows connected services and precedes validation/frames.
    positions={event:next(i for i,r in enumerate(rows) if r['event']==event) for event in ('wifi_connected','camera_init','candidate_allocated','validation','sample','done')}
    if list(positions.values())!=sorted(positions.values()):raise ValueError('Wrong initialization order')
    if 'allocation_order' in boot:
        reserved=one(rows,'arena_reserved')
        if reserved.get('allocation_order')!=order or reserved.get('requested_bytes')!=ARENA+64 or not reserved.get('internal'):raise ValueError('Invalid reservation evidence')
        rp=rows.index(reserved)
        if order=='early' and rp>=positions['wifi_connected']:raise ValueError('Arena was not reserved before services')
        if order=='late' and rp<=positions['camera_init']:raise ValueError('Arena was not reserved after services')
    done=one(rows,'done')
    if any(done.get(k)!=v for k,v in dict(camera_completed=1000,validation_inputs=35,canonical_checks=10,all_exact=True,guards=True,wifi_disconnections=0,heap_integrity=True,response_buffer_bytes=1760).items()):raise ValueError('Incomplete final state')
    if rows[-1]['event']!='done':raise ValueError('Unexpected events after completion')
    goldens=[r for r in rows if r['event']=='golden']
    if [r['frame'] for r in goldens]!=list(FRAMES):raise ValueError('Missing reference outputs')
    return dict(passed=True,allocation_order=order,camera_frames=1000,activation_bytes=ARENA,internal_min_free=min(r['internal_min_free'] for r in measured),
                largest_block_before_allocation=before['largest_block'],internal_free_end=memories[-1]['internal_free'],
                invoke_us={f'p{p}':percentile([s['invoke_us'] for s in samples],p) for p in (50,95)},
                acquisition_us={f'p{p}':percentile([s['acquisition_us'] for s in samples],p) for p in (50,95)}),{r['frame']:r for r in goldens}

def summarize_allocation_failure(rows):
    # A bounded, observed negative experiment is distinct from missing/corrupt data.
    error=one(rows,'error')
    if error.get('reason')!='internal_allocation' or rows[-1]!=error:raise ValueError('Unsupported incomplete experiment')
    boot=one(rows,'boot')
    if any(boot.get(k)!=v for k,v in dict(experiment='client_fit_benchmark',model_sha256=MODEL_SHA,reference_sha256=REFERENCE_SHA,cpu_mhz=240,psram_mhz=80,http=False).items()):raise ValueError('Wrong runtime')
    if not one(rows,'wifi_connected')['has_ip'] or one(rows,'camera_init')['status']!=0:raise ValueError('Services not initialized')
    if any(r['event'] in ('candidate_allocated','sample','done') for r in rows):raise ValueError('Contradictory allocation failure')
    memories=[r for r in rows if r['event']=='memory']
    if [r['stage'] for r in memories]!=['services_ready','before_internal_allocation'] or any(r['measuring'] for r in memories):raise ValueError('Incomplete failure memory trace')
    before=memories[-1]
    if not 0<=before['largest_block']<ARENA+64 or before['internal_free']<before['largest_block']:raise ValueError('Allocation failure evidence inconsistent')
    goldens=[r for r in rows if r['event']=='golden']
    if [r['frame'] for r in goldens]!=list(FRAMES):raise ValueError('Missing reference outputs')
    return dict(passed=False,outcome='internal_allocation_failed_after_services',round=1,camera_frames=0,
                requested_bytes_with_guards=ARENA+64,internal_free_before_allocation=before['internal_free'],
                largest_block_before_allocation=before['largest_block'],measurement_phase_started=False),{r['frame']:r for r in goldens}

def check_recovery(completion,hardware):
    if completion.get('board')!='B' or hardware.get('mac')!='24:ec:4a:0e:c3:14':raise ValueError('Wrong board')
    if not completion.get('measurements_complete') or completion.get('rounds_completed')!=3 or completion.get('error') or completion.get('restore_error') or not completion.get('original_boot_confirmed') or not hardware.get('restored') or not hardware.get('restored_digest_verified_before_boot'):raise ValueError('Incomplete run or recovery')

def audit(run,legacy_archive):
    completion=json.loads((run/'completion.json').read_text());hardware=json.loads((run/'board/hardware.json').read_text())
    negative=not completion.get('measurements_complete')
    if negative:
        if completion.get('rounds_completed')!=0 or not completion.get('error'):raise ValueError('Unsupported incomplete campaign')
        check_recovery(dict(completion,measurements_complete=True,rounds_completed=3,error=None),hardware)
    else:check_recovery(completion,hardware)
    if (run/'board/original-flash.bin').stat().st_size!=8388608 or sha(run/'board/original-flash.bin')!=hardware['backup_sha256']:raise ValueError('Backup changed')
    if sha(run/'firmware/firmware.bin')!=hardware['installed_sha256']:raise ValueError('Installed firmware differs')
    if b'sciot_esp32_client' not in (run/'board/restored-boot.log').read_bytes():raise ValueError('Original boot unconfirmed')
    hashes=json.loads((run/'source-sha256.json').read_text())
    if any(Path(p).name=='network.local.h' for p in hashes):raise ValueError('Credentials must not be archived as sources')
    previous=load_module('scratch_audit',ROOT/'experiments/esp32_scratch_benchmark/analyze.py');previous.verify_sources(run,hashes)
    legacy=load_module('legacy_audit',ROOT/'experiments/esp32_nopad_benchmark/analyze.py')
    rounds=[]
    for r in ((1,) if negative else (1,2,3)):
        raw=(run/f'board/round-{r}.serial.log').read_bytes()
        if any(x in raw for x in (b'task_wdt:',b'Guru Meditation Error',b'Brownout detector',b'abort() was called')):raise ValueError('Invalid serial log')
        rows=[json.loads(s)['row'] for s in (run/f'board/round-{r}.events.jsonl').read_text().splitlines()]
        result,goldens=(summarize_allocation_failure(rows) if negative else summarize_round(rows))
        result.update(round=r,legacy_device_comparison=legacy.legacy_check(legacy_archive,goldens,REFERENCE_SHA));rounds.append(result)
    configuration=json.loads((run/'configuration.json').read_text()) if (run/'configuration.json').exists() else dict(allocation_order='late')
    if not negative and any(r['allocation_order']!=configuration['allocation_order'] for r in rounds):raise ValueError('Build and runtime order differ')
    return dict(passed=not negative,allocation_order=configuration['allocation_order'],rounds=rounds,total_camera_frames=0 if negative else 3000,activation_bytes=ARENA,reserve_bytes=RESERVE,
                original_flash_and_boot_verified=True,model_sha256=MODEL_SHA,board='B',http_tested=False,
                source_manifest_sha256=sha(run/'source-sha256.json'),backup_sha256=hardware['backup_sha256'])

def write_report(result,out):
    out.mkdir(parents=True,exist_ok=True);(out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result['passed']:
        r=result['rounds'][0]
        with (out/'measurements.csv').open('w') as f:
            w=csv.writer(f);w.writerow(['round','internal_free_before','largest_block_before','requested_with_guards','camera_frames','passed'])
            w.writerow([1,r['internal_free_before_allocation'],r['largest_block_before_allocation'],r['requested_bytes_with_guards'],0,False])
        text='# Capienza con camera e Wi-Fi — esito negativo\n\n'
        text+='**Allocazione interna fallita dopo l’avvio dei servizi.** Wi-Fi con indirizzo IP e camera inizializzata.\n\n'
        text+=f'- RAM interna totale libera: **{r["internal_free_before_allocation"]:,} byte**.\n- Massimo blocco contiguo: **{r["largest_block_before_allocation"]:,} byte**.\n- Blocco richiesto: **{r["requested_bytes_with_guards"]:,} byte** (145.760 più due sentinelle da 32).\n'
        text+='\nLa memoria libera è distribuita in blocchi troppo piccoli. Il driver camera e il Wi-Fi risultano inizializzati; il prefisso candidato non è stato eseguito. Il test si è fermato al primo avvio: **zero frame della misura, nessuna dichiarazione di stabilità su tre avvii**.\n\n'
        text+='Il riferimento temporaneo in PSRAM ha prodotto i tre canonici identici all’archivio ESP32 precedente. Questo non costituisce validazione del candidato con servizi attivi.\n\n'
        text+='**Flash originale degli 8 MiB ripristinata, digest verificato prima del boot e avvio confermato.** Nessun cambiamento automatico a scratch o buffer di rete.\n\n'
        text+='Prossimo esperimento proposto: riservare l’arena prima di avviare camera e Wi-Fi, come ordine di inizializzazione del client, e verificare se entrambi i servizi partono conservando i 32 KiB di riserva. Questa possibilità non è stata provata qui. HTTP, socket attivi e integrazione restano esclusi.\n'
        (out/'report.md').write_text(text);return
    with (out/'measurements.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['round','largest_block_before','internal_min_free','internal_free_end','invoke_p50_us','invoke_p95_us'])
        for r in result['rounds']:w.writerow([r['round'],r['largest_block_before_allocation'],r['internal_min_free'],r['internal_free_end'],r['invoke_us']['p50'],r['invoke_us']['p95']])
    text='# Capienza con camera e Wi-Fi — risultati\n\nOrdine di allocazione: **'+result['allocation_order']+'**.\n\n**Criteri superati in tre avvii indipendenti.** Arena interna effettiva: 145.760 byte più 64 byte di sentinelle; 3.000 frame camera.\n\n'
    text+='| Avvio | Blocco contiguo prima (B) | Minimo libero (B) | Invoke p50/p95 (ms) |\n|---|---:|---:|---:|\n'
    for r in result['rounds']:text+=f'| {r["round"]} | {r["largest_block_before_allocation"]} | {r["internal_min_free"]} | {r["invoke_us"]["p50"]/1000:.3f} / {r["invoke_us"]["p95"]/1000:.3f} |\n'
    text+='\nConfronti numerici e sentinelle superati, Wi-Fi connesso, nessuna disconnessione nella misura. Flash originale ripristinata e boot confermato.\n\nQuesta verifica usa LUT, buffer applicativi, camera e Wi-Fi, ma non richieste HTTP o socket attivi: la capienza durante trasmissione e il ciclo del servizio completo restano da misurare. Nessuna modifica al client operativo.\n'
    (out/'report.md').write_text(text)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--legacy-archive',type=Path,required=True)
    a=p.parse_args();write_report(audit(a.run,a.legacy_archive),a.output)
