"""Measured rate/gain points; ranges of three blocks are not confidence intervals."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);a=p.parse_args()
s=json.loads((a.input/'summary.json').read_text());points=sorted(s['points'],key=lambda x:x['rate_kbps'])
fig,(top,bottom)=plt.subplots(2,1,figsize=(9,6.8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
for point in points:
    rate=point['rate_kbps'];pairs=point['acceptance']['pairs'];color='#26853b' if point['passes'] else '#bd3535'
    gains=[100*(1-x['median_ratio']) for x in pairs]
    top.vlines(rate,min(gains),max(gains),color='#777777',lw=2)
    top.scatter([rate-5,rate,rate+5],gains,color='#777777',s=20,zorder=3)
    top.scatter([rate],[-point['median_change_percent']],color=color,s=75,zorder=4)
    bottom.scatter([rate],[max(x['p95_ratio'] for x in pairs)],color=color,s=55,zorder=3)
passed=[x['rate_kbps'] for x in points if x['passes']];failed=[x['rate_kbps'] for x in points if not x['passes']]
if passed and failed and max(passed)<min(failed) and 'bracket' in s['stop_reason']:
    for ax in (top,bottom):ax.axvspan(max(passed),min(failed),color='#d8e8f4',alpha=.45)
top.axhline(5,color='#9a6b00',ls='--',label='Guadagno richiesto: almeno 5%')
top.scatter([],[],color='#26853b',s=55,label='Criterio completo superato')
top.scatter([],[],color='#bd3535',s=55,label='Criterio completo non superato')
top.plot([],[],color='#777777',marker='o',label='Range delle 3 coppie, non IC')
top.set(ylabel='Riduzione della mediana, %',title='Rice temporale: soglia operativa misurata sull’hotspot\nPunti grandi: mediana aggregata; segmenti: tre coppie di giri')
top.legend(fontsize=8,loc='best');bottom.axhline(1.05,color='#bd3535',ls='--',label='Massimo ammesso: 1,05')
bottom.set(xlabel='Rate imposto al corpo della richiesta, kbit/s',ylabel='Peggior rapporto p95\nRice / raw')
bottom.legend(fontsize=8,loc='best');bottom.set_xticks([x['rate_kbps'] for x in points])
for ax in (top,bottom):ax.grid(alpha=.2)
fig.tight_layout()
for ext in ('png','svg'):fig.savefig(a.input/f'threshold.{ext}',dpi=160)
