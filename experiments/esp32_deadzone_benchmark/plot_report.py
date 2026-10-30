"""Standalone video tradeoff figure; uses system matplotlib, no model runtime."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    args=p.parse_args()
    report=json.loads((args.run/'summary.json').read_text())
    if not report['verified']:raise ValueError('Audit required before plotting')
    rows=[r for r in report['configurations'] if r['source']=='video']
    groups={c:[r for r in rows if r['config']==c] for c in range(12)}
    families=[('INT8 raw / zlib',range(3),'#414141','s'),
              ('Indipendente',range(3,6),'#3579b6','o'),
              ('DPCM uniforme',range(6,9),'#21866c','^'),
              ('DPCM dead-zone',range(9,12),'#c25a29','D')]
    fig,axes=plt.subplots(1,2,figsize=(13,5.4),layout='constrained')
    for label,configs,color,marker in families:
        for c in configs:
            group=groups[c];x=sum(r['http_bytes']/r['frames'] for r in group)/len(group)
            changed=sum(r['changed_cells'] for r in group)/len(group)
            times=[r['cycle_us_p50']/1000 for r in group];center=sum(times)/len(times)
            for axis,y in zip(axes,(changed,center)):
                axis.scatter(x,y,color=color,marker=marker,s=54,label=label if c==min(configs) else None,zorder=3)
            axes[1].errorbar(x,center,yerr=[[center-min(times)],[max(times)-center]],color=color,capsize=3,lw=1)
            name=group[0]['mode'] if c<3 else str((4,6,8)[(c-3)%3])+' bit'
            offset=((5,6) if c==0 else (5,10) if c==1 else (5,-14)) if c<3 else (5,5+(c//3-1)*8)
            for axis,y in zip(axes,(changed,center)):
                axis.annotate(name,(x,y),xytext=offset,textcoords='offset points',fontsize=8,color=color)
    for axis in axes:
        axis.set_xlabel('Byte HTTP per frame, richiesta e risposta')
        axis.grid(alpha=.22)
        axis.margins(x=.12,y=.15)
    axes[0].set_ylabel('Celle diverse da INT8 raw su 146 frame\n(soglia 0,5; fedeltà, non accuratezza)')
    axes[1].set_ylabel('Ciclo completo, ms\n(media dei p50; barre: min/max dei due giri)')
    axes[0].set_title('Traffico e cambiamenti nelle predizioni')
    axes[1].set_title('Traffico e tempo sulla ESP32-S3-EYE')
    axes[0].legend(fontsize=8,loc='best')
    fig.suptitle('FOMO INT8 con ESP-NN — stesso video, stesso split, due giri',fontsize=13)
    fig.savefig(args.run/'tradeoff.png',dpi=180)
    fig.savefig(args.run/'tradeoff.svg')
    print(args.run/'tradeoff.png')


if __name__=='__main__':main()
