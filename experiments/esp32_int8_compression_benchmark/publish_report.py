"""Publish two validated sessions without credentials or private flash images."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',type=Path,nargs=2,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    data=[json.loads((r/'summary.json').read_text()) for r in args.runs]
    if data[0]['fixed_output_sha256']!=data[1]['fixed_output_sha256']:raise ValueError('Fixed outputs differ across sessions')
    if any(d['samples']!=408 for d in data):raise ValueError('Unexpected sample count')
    compact=[]
    for path,d in zip(args.runs,data):
        row={k:v for k,v in d.items() if k!='fixed_output_sha256'}
        row.update(run=path.name,device_log_sha256=hashlib.sha256((path/'device.log').read_bytes()).hexdigest(),
            server_log_sha256=hashlib.sha256((path/'server/server.jsonl').read_bytes()).hexdigest())
        compact.append(row)
    metadata={'date':'2026-10-28','scope':'One ESP32-S3-EYE, one serial HTTP suffix server, INT8 ESP-NN, independent lossless tensors',
        'model_manifest':json.loads((HERE/'artifacts/manifest.json').read_text()),
        'miniz_revision':'293d4db1b7d0ffee9756d035b9ac6f7431ef8492','zlib_level':1,
        'firmware_sha256':hashlib.sha256((HERE/'idf/.pio/build/compression/firmware.bin').read_bytes()).hexdigest(),
        'fixed_outputs_exact_across_sessions':True,'runs':compact}
    (args.output/'summary.json').write_text(json.dumps(metadata,indent=2)+'\n')
    lines=['# INT8 con ESP-NN: non compresso contro zlib senza perdita','',
        'Prova fisica del 28 ottobre 2026: due sessioni dello stesso firmware, **816 richieste validate**, '
        'un solo interprete INT8 e un punto di divisione fisso `block_2_add` (4.608 byte). '
        'Miniz 3.0.2, livello 1, un flusso zlib indipendente per tensore. CPU 240 MHz, arena e workspace in PSRAM.','',
        '## Byte e tempo completo','',
        'Valori mediani. I byte HTTP includono richiesta e risposta con intestazioni ricostruite dal server. '
        'La risposta è sempre di 1.760 byte; TCP/IP, ritrasmissioni e occupazione radio non sono misurati.','',
        '| Sessione | Ingresso | Payload raw / zlib, B | Risparmio payload | HTTP raw / zlib, B | Ciclo raw / zlib, ms |',
        '|---|---|---:|---:|---:|---:|']
    for i,d in enumerate(data,1):
        for source,label in [('embedded','Immagini identiche'),('annotated','84 foto annotate'),('camera_alternating','Camera alternata')]:
            network=d['traffic'][source];time=d['timing'][source]
            raw=network['raw']['wire_bytes']['p50'];encoded=network['zlib']['wire_bytes']['p50']
            http={m:network[m]['http_total_bytes']['p50'] for m in ('raw','zlib')}
            latency={m:time[m]['observed_cycle_us']['p50']/1000 for m in ('raw','zlib')}
            lines.append(f'| {i} | {label} | {raw:.0f} / {encoded:.0f} | {100*(1-encoded/raw):.1f}% | {http["raw"]:.0f} / {http["zlib"]:.0f} | {latency["raw"]:.2f} / {latency["zlib"]:.2f} |')
    lines+=['','Il ciclo include preparazione ingresso, inferenza locale, checksum, compressione/reset '
        '(quando abilitata), impacchettamento, connessione TCP, HTTP, decompressione e controllo sul PC, '
        'suffisso, postprocessing FOMO e ricezione della risposta. Per la camera include acquisizione '
        'da `esp_camera_fb_get` e preprocessing; non misura età del frame o inizio esposizione. '
        'I tempi server sono già compresi in HTTP.','',
        '## Costo del codec e variabilità','',
        '| Sessione | Ingresso | Compressione p50, ms | Decompressione + controlli p50, ms | Ciclo raw p95, ms | Ciclo zlib p95, ms |',
        '|---|---|---:|---:|---:|---:|']
    for i,d in enumerate(data,1):
        for source,label in [('embedded','Immagini identiche'),('camera_alternating','Camera alternata')]:
            t=d['timing'][source]
            lines.append(f'| {i} | {label} | {t["zlib"]["compression_us"]["p50"]/1000:.3f} | {t["zlib"]["server_decompression_and_validation_us"]["p50"]/1000:.3f} | {t["raw"]["observed_cycle_us"]["p95"]/1000:.2f} | {t["zlib"]["observed_cycle_us"]["p95"]/1000:.2f} |')
    lines+=['','## Sequenze continue dalla camera','',
        '| Sessione | Raw, immagini/s nelle due sequenze | Zlib, immagini/s nelle due sequenze |',
        '|---|---:|---:|']
    for i,d in enumerate(data,1):
        fps={m:[r['frames_per_second'] for r in d['throughput'] if r['mode']==m] for m in ('raw','zlib')}
        lines.append(f'| {i} | '+ ' / '.join(f'{v:.2f}' for v in fps['raw'])+' | '+' / '.join(f'{v:.2f}' for v in fps['zlib'])+' |')
    lines+=['','Quattro sequenze da 20 frame per sessione, ordine raw/zlib/zlib/raw. Le stampe '
        'seriali sono emesse dopo la misura della sequenza. I frame camera differiscono fra modalità; '
        'il confronto a ingresso identico usa i tre frame canonici e tutte le 84 foto.','',
        '## Integrità e memoria','',
        'Per ciascuna sessione, **87 ingressi distinti** hanno attivazioni ricostruite e punteggi finali '
        'identici byte per byte tra raw e zlib (288 richieste includendo le ripetizioni). '
        'Le predizioni su tutti gli ingressi fissi coincidono anche fra le due sessioni. '
        'Ogni messaggio, inclusi quelli camera, supera controllo delle dimensioni e CRC32 del tensore originale.','']
    q=data[0]['quality']['class_agnostic']
    lines.append(f'Sulle 84 foto annotate entrambe le modalità trovano {q["tp"]} oggetti, ne mancano {q["fn"]} e producono {q["fp"]} falsi positivi. '
        'Il matching ignora la classe, come nel confronto precedente; non sono nuove misure su scene indipendenti. '
        'La compressione non aggiunge perdita a quella già presente nel modello INT8.')
    memory=data[0]['codec_memory'][0]
    lines+=['',f'Workspace allocato del codec: **{memory["workspace_bytes"]:,} byte**, buffer compresso 8.192 byte e buffer messaggio 8.224 byte. '
        'Queste allocazioni sono persistenti e presenti in entrambe le modalità dello stesso firmware; '
        'inizializzazione fuori misura, reset per tensore incluso. Non è una misura del picco RAM '
        'di due applicazioni separate.','',
        'La modalità zlib invia sempre il risultato del codec, senza fallback adattivo. '
        f'Frame espansi osservati: '+str(sum(d['traffic'][s]['zlib']['expanded_frames'] for d in data for s in d['traffic']))+'.','',
        '## Interpretazione','']
    faster=[d['timing']['embedded']['zlib']['observed_cycle_us']['p50']<d['timing']['embedded']['raw']['observed_cycle_us']['p50'] for d in data]
    if all(faster):
        lines.append('Sulle immagini identiche, nelle due sessioni la mediana del tempo completo è minore con zlib. '
            'È un miglioramento osservato in questa configurazione; la tabella camera e le sequenze continue '
            'mostrano quanto si mantiene nel flusso reale e la variabilità della rete.')
    elif not any(faster):
        lines.append('Sulle immagini identiche, nelle due sessioni zlib aumenta la mediana del tempo completo. '
            'In questa configurazione la riduzione del traffico non compensa il costo della compressione. '
            'Le prove camera restano indicate separatamente.')
    else:
        lines.append('Le due sessioni sulle immagini identiche non concordano sul vantaggio di tempo completo. '
            'Non è dimostrata una riduzione stabile dell’attesa; distinguere il risparmio di byte dalla velocità.')
    lines+=['','Per parlare di riduzione del traffico al secondo confrontare le modalità alla stessa frequenza di invio. '
        'Il risultato riguarda una scheda, questa rete, questo codec e questo taglio; '
        'compressione temporale e client concorrenti sono esperimenti successivi.','',
        'Dettagli: [summary.json](summary.json). Metodo: [README](../README.md). '
        'I log seriali e i pacchetti originali sono conservati localmente sotto `results/`, ignorato da Git.','']
    (args.output/'report.md').write_text('\n'.join(lines))
    files=['summary.json','report.md']
    (args.output/'snapshot-sha256.txt').write_text(''.join(hashlib.sha256((args.output/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in files))
    print(args.output/'report.md')

if __name__=='__main__':main()
