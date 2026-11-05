"""Render the offline extrapolation distinctly from the measured rate range."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--input', type=Path, required=True)
a = p.parse_args()
s = json.loads((a.input / 'summary.json').read_text())
rates = np.geomspace(.128, 3, 500)

def improvement(fits):
    raw = fits['raw']['a_ms_mbps'] / rates + fits['raw']['b_ms']
    rice = fits['rice_temporal']['a_ms_mbps'] / rates + fits['rice_temporal']['b_ms']
    return 100 * (raw - rice) / raw

y = improvement(s['fits'])
sensitivity = np.asarray([improvement(item['fits']) for item in s['sensitivity_fits']])
fig, ax = plt.subplots(figsize=(9, 5.6))
ax.fill_between(rates, sensitivity.min(axis=0), sensitivity.max(axis=0), color='#b8bec8', alpha=.4, label='Sensibilità ai 9 fit, non intervallo di confidenza')
measured_range = rates <= .512
ax.plot(rates[measured_range], y[measured_range], color='#2463a6', label='Fit nel tratto fra i due rate misurati')
ax.plot(rates[~measured_range], y[~measured_range], color='#2463a6', ls='--', label='Estrapolazione non validata')
for rate in (128, 512):
    values = s['observed_cycle_p50_ms'][str(rate)]
    gain = 100 * (1 - values['rice_temporal'] / values['raw'])
    ax.scatter([rate / 1000], [gain], color='#173b61', zorder=4)
    ax.annotate(f'{rate} kbit/s: misurato', (rate / 1000, gain), xytext=(8, 10), textcoords='offset points', fontsize=9)
ax.axhline(0, color='#666666', lw=.8)
ax.axhline(5, color='#9a6b00', ls=':', label='Obiettivo: 5% sulla sola mediana')
threshold = s['point_estimates']['five_percent_median_gain_mbps']
ax.scatter([threshold], [5], marker='x', s=70, color='#9a6b00', zorder=5)
ax.annotate(f'Stima: {threshold:.2f} Mbit/s', (threshold, 5), xytext=(12, 16), textcoords='offset points', fontsize=9, color='#805700')
ax.set_xscale('log')
ax.set_xticks([.128, .256, .512, 1, 2, 3], ['0,128', '0,256', '0,512', '1', '2', '3'])
ax.set(xlim=(.115, 3), ylim=(-10, 38), xlabel='Rate imposto al corpo della richiesta, Mbit/s (scala log)', ylabel='Riduzione della mediana rispetto al raw, %', title='Rice temporale: stima offline della soglia\nSolo 128 e 512 kbit/s misurati; p95 non previsto dal modello')
ax.grid(alpha=.2)
ax.legend(loc='upper right', fontsize=8)
fig.tight_layout()
for ext in ('png', 'svg'):
    fig.savefig(a.input / f'threshold.{ext}', dpi=160)
