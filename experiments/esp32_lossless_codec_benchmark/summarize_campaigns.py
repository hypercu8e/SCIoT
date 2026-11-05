"""Combine only published, fully audited and restored hardware campaigns."""
import csv
import json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
SOURCES=[('Wi-Fi ordinaria, Python','hardware_python_2026-10-30'),('Wi-Fi ordinaria, C++','hardware_native_network_2026-10-30'),('Proxy 128 kbit/s, C++','hardware_native_128k_2026-10-30'),('Proxy 512 kbit/s, C++','hardware_native_512k_2026-10-30')]

def main():
    combined=[];measured=diagnostics=0
    for title,folder in SOURCES:
        path=HERE/folder;s=json.loads((path/'summary.json').read_text());v=json.loads((path/'verification.json').read_text())
        if not s['lossless_exact'] or not s['restored_verified'] or not v['original_boot_verified']:raise ValueError('Unaudited campaign')
        rows=list(csv.DictReader((path/'frames.csv').open()));video=[r for r in rows if int(r['source'])==0]
        measured+=s['measured'];diagnostics+=s['diagnostics'];methods={}
        for name in sorted(set(r['mode'] for r in video)):
            group=[r for r in video if r['mode']==name]
            methods[name]=dict(payload_mean=float(np.mean([float(r['payload_bytes']) for r in group])),cycle_p50_ms=float(np.median([float(r['cycle_us']) for r in group]))/1000,cycle_p95_ms=float(np.percentile([float(r['cycle_us']) for r in group],95))/1000,encode_p50_ms=float(np.median([float(r['quantize_reconstruct_us'])+float(r['compression_us']) for r in group]))/1000,server_decode_p50_ms=float(np.median([float(r['server_decode_us']) for r in group]))/1000)
        raw=methods['raw'];rice=methods['rice_temporal']
        combined.append(dict(condition=title,folder=folder,decoder=s['decoder_backend'],serial_recovery=s.get('serial_recovery'),bandwidth=s['bandwidth'],methods=methods,acceptance=s['acceptance'],rice_payload_saving_percent=100*(1-rice['payload_mean']/raw['payload_mean']),rice_cycle_change_percent=100*(rice['cycle_p50_ms']/raw['cycle_p50_ms']-1)))
    output=dict(measured_requests=measured,diagnostic_requests=diagnostics,campaigns=combined)
    (HERE/'campaign-summary.json').write_text(json.dumps(output,indent=2)+'\n')
    text='# Ultima verifica della compressione INT8\n\n'
    text+=f'{measured} richieste fisiche misurate e {diagnostics} diagnostiche; tutte le campagne complete, auditate e con firmware originale ripristinato e verificato. Tutti i percorsi lossless conservano attivazioni e uscite byte per byte.\n\n'
    text+='|Condizione|Raw p50 ms|Rice temporale p50 ms|Variazione p50 aggregata|Criterio sulle 3 coppie|\n|---|---:|---:|---:|---|\n'
    for c in combined:
        text+=f"|[{c['condition']}]({c['folder']}/report.md)|{c['methods']['raw']['cycle_p50_ms']:.2f}|{c['methods']['rice_temporal']['cycle_p50_ms']:.2f}|{c['rice_cycle_change_percent']:+.2f}%|{'superato' if c['acceptance']['rice_temporal']['passes'] else 'non superato'}|\n"
    text+='\nLe mediane aggregate descrivono tutti i sei giri video. La decisione usa invece tre confronti separati, ciascuno su due giri in ordine invertito: mediana almeno -5% e p95 non oltre +5%. Non è una garanzia statistica per altre scene o reti.\n\n'
    c=combined[1];r=c['methods']['rice_temporal']
    text+=f"Rice temporale: {r['payload_mean']:.2f} byte/frame contro 4608 raw, risparmio {c['rice_payload_saving_percent']:.2f}%. Nella campagna completa D+DZ4 con miniz e con packing producono la stessa ricostruzione con perdita; non sono candidati all'obiettivo lossless.\n\n"
    normal_passed=[name for name,v in combined[1]['acceptance'].items() if v['passes']]
    limited=[(c,[name for name,v in c['acceptance'].items() if v['passes']]) for c in combined[2:]]
    limited=[(c,names) for c,names in limited if names]
    if normal_passed:text+='Nella rete ordinaria provata superano il criterio operativo: '+', '.join(normal_passed)+'. Restano da verificare in integrazione SCIoT e su scene indipendenti.\n\n'
    elif limited:text+='Nella rete ordinaria provata nessun candidato Rice supera il criterio operativo. Il vantaggio è condizionato ai regimi limitati che superano il criterio: '+ '; '.join(c['condition']+' ('+', '.join(names)+')' for c,names in limited)+'. Raw resta il riferimento per la latenza ordinaria; Rice è un candidato opzionale per banda ridotta.\n\n'
    else:text+='Nessun regime provato supera interamente il criterio operativo per i candidati Rice. Il risparmio di byte resta distinto dal vantaggio di latenza.\n\n'
    for c in combined:
        if c['serial_recovery']:text+=f"Nota di audit ({c['condition']}): {c['serial_recovery']['recovered_records']} prefisso identificativo USB troncato ricostruito da pacchetto e righe adiacenti. Tempi presenti integralmente nel log originale, nessuna stima; manifest e hash conservati.\n\n"
    text+='## Interpretazione e limiti\n\n'
    text+='- Il decoder C++ elimina il costo del ciclo Rice interpretato; il decoder Python indipendente verifica offline tutti i pacchetti. Confrontare ciascun codec con il raw della stessa campagna, senza attribuire al backend differenze assolute fra sessioni radio diverse.\n'
    text+='- Il proxy limita il corpo applicativo della richiesta, con rate effettivo registrato. Non riproduce contesa Wi-Fi, perdita, ritrasmissioni o consumo energetico. I byte HTTP non sono occupazione radio.\n'
    text+='- Una ESP32-S3-EYE, un modello, uno split e un video. Camera verificata nella campagna completa; confronti nativi e limitati usano ingressi video identici. La fedeltà al raw INT8 non misura accuratezza rispetto ad annotazioni né equivalenza al modello float32.\n'
    text+='- I buffer comuni del benchmark non rappresentano picchi RAM di firmware separati. Integrazione SCIoT, addestramento di bottleneck e altri split rimangono fuori dalla prova.\n\n'
    text+='La ricognizione bibliografica è mirata, non esaustiva. I risultati delimitano questa esplorazione post-hoc su INT8; non dimostrano impossibilità di ulteriori codec o metodi addestrati.\n'
    (HERE/'report.md').write_text(text)
    print(json.dumps(output,indent=2))
if __name__=='__main__':main()
