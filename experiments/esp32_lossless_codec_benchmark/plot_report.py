"""Standalone exported hardware comparison, using audited summary only."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
s=json.loads((a.run/'summary.json').read_text());fig,ax=plt.subplots(figsize=(9,5))
colors={'raw':'#2ca02c','zlib1':'#8c564b','rice_independent':'#d62728','rice_temporal':'#9467bd','deadzone4_zlib':'#ff7f0e','deadzone4_packed':'#1f77b4'}
backend='C++' if s['decoder_backend']=='native' else 'Python'
condition=f"proxy {s['bandwidth']['target_kbps']} kbit/s" if s.get('bandwidth') else 'rete ordinaria'
for name in sorted(set(g['mode'] for g in s['groups'])):
    groups=[g for g in s['groups'] if g['mode']==name and g['source']=='video']
    ax.scatter([g['payload_mean'] for g in groups],[g['cycle_p50_ms'] for g in groups],label=name,color=colors[name],marker='x' if 'deadzone' in name else 'o')
ax.set(xlabel='Payload medio, byte/frame',ylabel='Ciclo mediano, ms',title=f'FOMO INT8 su ESP32: giri video\nDecoder Rice {backend}, {condition}')
ax.grid(alpha=.25);ax.legend(fontsize=8);fig.tight_layout()
for ext in ('png','svg'):fig.savefig(a.run/f'tradeoff.{ext}',dpi=160)
