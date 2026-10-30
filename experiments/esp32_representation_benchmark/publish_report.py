"""Create a compact, credential-free archive from two validated hardware runs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

HERE=Path(__file__).resolve().parent
MODES=('float32','int8')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def predictions(run):
    rows=[json.loads(x) for x in (run/'server/server.jsonl').read_text().splitlines()]
    return {(r['mode'],r['frame'],r['iteration']):Path(str(run/'server'/r['request'])+'.response.bin').read_bytes()[32:]
            for r in rows if r['frame']<1000 or r['frame']>=3000}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',nargs=2,type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    runs=[json.loads((r/'summary.json').read_text()) for r in args.runs]
    first,second=map(predictions,args.runs)
    if first.keys()!=second.keys() or any(first[k]!=second[k] for k in first):
        raise ValueError('Fixed-input predictions differ between repeated sessions')
    for data in runs:
        if data['samples']!=408:raise ValueError('Unexpected sample count')
    compact=[]
    for path,data in zip(args.runs,runs):
        quality={k:v for k,v in data['quality'].items() if k!='frames'}
        device_rows=[json.loads(line) for line in (path/'device.log').read_text(errors='replace').splitlines()
                     if line.startswith('{"event":"sample"') or line.startswith('{"event": "sample"')]
        rssi=[r['rssi_dbm'] for r in device_rows]
        compact.append(dict(run=path.name,raw_summary_sha256=digest(path/'summary.json'),
            device_log_sha256=digest(path/'device.log'),server_log_sha256=digest(path/'server/server.jsonl'),
            samples=data['samples'],timing=data['timing'],throughput=data['throughput'],
            network=data['network'],quality=quality,allocations=data['allocations'],
            desktop_fidelity=data['desktop_fidelity'],kernel_evidence=data['kernel_evidence'],
            wifi_rssi_dbm={'min':min(rssi),'median':statistics.median(rssi),'max':max(rssi)},
            stability=data['stability']))
    result={'date':'2026-10-27','board':'ESP32-S3-EYE 24:EC:4A:0E:B7:6C',
        'cpu_mhz':240,'idf_version':'5.4.0','platformio_platform':'espressif32@6.10.0',
        'components':json.loads((HERE/'idf/components.json').read_text()),
        'experiment':json.loads((HERE/'artifacts/manifest.json').read_text()),
        'quality_inputs_sha256':json.loads((HERE/'artifacts/quality-inputs.json').read_text())['input_sha256'],
        'decoder_verification':json.loads((HERE/'artifacts/decoder-verification.json').read_text()),
        'firmware_sha256':digest(HERE/'idf/.pio/build/espnn/firmware.bin'),
        'fixed_prediction_comparisons_across_runs':len(first),'fixed_predictions_exact_across_runs':True,
        'runs':compact,'limitations':runs[0]['limitations']}
    (args.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    with (args.output/'quality-per-image.csv').open('w',newline='') as stream:
        names=['frame','annotations','float32_tp','float32_fp','float32_fn','int8_tp','int8_fp','int8_fn','objects_lost_vs_float32','objects_gained_vs_float32']
        writer=csv.DictWriter(stream,fieldnames=names);writer.writeheader()
        for row in runs[0]['quality']['frames']:
            out={'frame':row['frame'],'annotations':row['annotations'],
                'objects_lost_vs_float32':len(row['lost_vs_float32']),'objects_gained_vs_float32':len(row['gained_vs_float32'])}
            out.update({f'{m}_{k}':row[m][k] for m in MODES for k in ('tp','fp','fn')});writer.writerow(out)
    lines=['# FOMO INT8 con ESP-NN: confronto fisico del 27 ottobre 2026','',
        'Due sessioni dello stesso firmware su una ESP32-S3-EYE e un PC sulla rete locale: '
        '**816 richieste complete validate**. Stesso taglio `block_2_add`, arene in PSRAM, CPU 240 MHz. '
        'Il modello è il candidato Beer/can 96×96 in grigio già usato nelle prove PC; '
        'INT8 quantizza pesi e attivazioni. Non sono prove del server originale SCIoT o di due client.','',
        '## Traffico per immagine','',
        '| Misura | FLOAT32 | INT8 | Riduzione |','|---|---:|---:|---:|']
    for label,key in [('Sole attivazioni','activation_bytes'),('Corpo richiesta','request_body_bytes'),('HTTP completo nelle due direzioni, intestazioni incluse','http_total_bytes')]:
        f=runs[0]['network']['float32'][key]['p50'];q=runs[0]['network']['int8'][key]['p50']
        lines.append(f'| {label} | {f:,.0f} B | {q:,.0f} B | {100*(1-q/f):.2f}% |')
    lines+=['','Le richieste misurate non contengono immagini diagnostiche. La risposta è uguale: '
        '1.760 byte, con tutti i punteggi finali. Gli header HTTP sono ricostruiti dal server; '
        'TCP/IP, ritrasmissioni e tempo radio non sono misurati. Il risparmio di traffico/s '
        'vale a parità di frequenza di elaborazione.','',
        '## Tempo completo fino alla risposta','',
        'Mediana e percentile 95 in millisecondi. Il timer camera parte prima della richiesta '
        'del frame (`esp_camera_fb_get`), senza misurare età del frame o inizio esposizione. '
        'Il timer sulle immagini incorporate parte dalla preparazione dell’ingresso.','',
        '| Sessione | Ingresso | FLOAT32 p50 / p95 | INT8 p50 / p95 | Rapporto p50 FLOAT32/INT8 |',
        '|---|---|---:|---:|---:|']
    for index,data in enumerate(runs,1):
        for source,label in [('embedded','Immagini identiche'),('camera_alternating','Telecamera, frame alternati')]:
            f=data['timing'][source]['float32']['observed_cycle_us'];q=data['timing'][source]['int8']['observed_cycle_us']
            lines.append(f'| {index} | {label} | {f["p50"]/1000:.1f} / {f["p95"]/1000:.1f} | {q["p50"]/1000:.1f} / {q["p95"]/1000:.1f} | {f["p50"]/q["p50"]:.2f}× |')
    lines+=['','Ogni sessione comprende 60 campioni per rappresentazione sulle immagini identiche '
        'e 20 campioni per rappresentazione nella camera alternata. I frame della camera differiscono '
        'fra esecuzioni. I tempi del server sono già compresi in HTTP e non si sommano di nuovo.','',
        '## Calcolo e sequenze continue','',
        '| Sessione | Prefisso FLOAT32, p50 ms | Prefisso INT8, p50 ms | FPS continui FLOAT32 | FPS continui INT8 |',
        '|---|---:|---:|---:|---:|']
    for index,data in enumerate(runs,1):
        fps={m:[r['frames_per_second'] for r in data['throughput'] if r['mode']==m] for m in MODES}
        invoke={m:data['timing']['embedded'][m]['invoke_us']['p50']/1000 for m in MODES}
        lines.append(f'| {index} | {invoke["float32"]:.1f} | {invoke["int8"]:.1f} | '+
            ' / '.join(f'{v:.2f}' for v in fps['float32'])+' | '+' / '.join(f'{v:.2f}' for v in fps['int8'])+' |')
    lines+=['','Gli FPS sono misurati su sequenze continue da 20 frame, due sequenze per '
        'rappresentazione e sessione, ordine AB/BA. Le stampe seriali avvengono dopo la sequenza. '
        'Non sono l’inverso della latenza mediana. L’ingresso INT8 richiede ancora circa 39 ms '
        'per la quantizzazione in double del firmware; questo costo è incluso nel tempo completo.','',
        'Il controllo sul dispositivo conta **6 convoluzioni e 3 depthwise ottimizzate ESP32-S3** '
        'per prefisso INT8 e zero per FLOAT32. Le due sessioni usano lo stesso runtime ufficiale '
        'e lo stesso binario. Il confronto con la vecchia baseline Arduino non isola il solo '
        'beneficio di ESP-NN, perché cambia anche la versione del runtime.','',
        '## Qualità su 84 foto annotate','',
        'Soglia fissata a 0,5; 112 oggetti annotati dopo il ritaglio. Matching uno a uno '
        'con centro del rilevamento dentro il box annotato. **La classe è ignorata**: '
        'l’ordine beer/can dei canali del nostro H5 non è confermato.','',
        '| Versione | Oggetti trovati | Oggetti mancati | Falsi positivi | Precisione | Richiamo | F1 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for mode in MODES:
        q=runs[0]['quality'][mode]
        lines.append(f'| {mode} | {q["tp"]} | {q["fn"]} | {q["fp"]} | {100*q["precision"]:.2f}% | {100*q["recall"]:.2f}% | {100*q["f1"]:.2f}% |')
    lines+=['','Le predizioni sulle immagini identiche sono esattamente ripetibili fra le due '
        'sessioni. Nel campione INT8 perde un oggetto riconosciuto da FLOAT32 e produce due '
        'falsi positivi in meno. Questa differenza non dimostra una qualità generalmente '
        'superiore o inferiore. La relazione tra queste foto pubbliche e i dati di addestramento '
        'dell’H5 esportato non è dimostrata; servono scene nuove e nomi dei canali verificati '
        'prima di concludere sull’utilizzabilità nell’applicazione.','',
        'Il decoder Python è verificato contro le funzioni C++ del SDK ufficiale su 250 mappe '
        'sintetiche. I punteggi INT8 hardware non sono identici a quelli dell’interprete desktop: '
        'errore massimo osservato 0,16796875. I conteggi qui sopra provengono dalla scheda.','',
        '## Conclusione e limiti','',
        '**In questa configurazione INT8 con ESP-NN riduce sia il traffico per immagine sia '
        'il tempo completo client-server.** Osserviamo un oggetto mancato in più sui 112 del campione, '
        'insieme a due falsi positivi in meno. È un candidato utile da validare su scene nuove.','',
        'Restano aperti qualità per classe, dati indipendenti, altri tagli, integrazione nel '
        'protocollo SCIoT originale e comportamento con due client. Le arene effettive sono '
        '907.272 byte FLOAT32 e 229.820 byte INT8, ma sono entrambe residenti e riservate a '
        '1 MiB: non è una misura del picco RAM di un’applicazione con un solo modello.','',
        'Dati riassunti: [summary.json](summary.json). '
        'Conteggi per foto: [quality-per-image.csv](quality-per-image.csv). '
        'Metodo e riproduzione: [README](../README.md). '
        'I log e i pacchetti originali restano nelle directory locali ignorate `results/`.','']
    (args.output/'report.md').write_text('\n'.join(lines))
    files=['summary.json','quality-per-image.csv','report.md']
    (args.output/'snapshot-sha256.txt').write_text(''.join(f'{digest(args.output/name)}  {name}\n' for name in files))
    print(args.output/'report.md')

if __name__=='__main__':main()
