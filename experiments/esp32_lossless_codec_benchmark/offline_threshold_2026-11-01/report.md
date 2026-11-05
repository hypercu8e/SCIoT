# Soglia Rice: stima offline, 1 novembre 2026

Aggiornamento successivo: [nuove misure hardware su un hotspot diverso](../../esp32_rice_threshold_benchmark/sweep_2026-11-01/report.md)
collocano la transizione del criterio completo (mediana e p95) fra 800 e
900 kbit/s. Questa pagina conserva la stima offline basata sui soli dati di
ottobre; rete e criterio differiscono, quindi non è una validazione dello stesso fit.

**Nessuna nuova prova hardware.** Si usano i CSV delle campagne native del 30 ottobre.

|Quantità stimata|Fit sulle mediane aggregate|Sensibilità ai nove abbinamenti di blocchi|
|---|---:|---:|
|Guadagno del 5% sulla sola mediana|0.696 Mbit/s|0.599–0.852 Mbit/s|
|Semplice pareggio del ciclo mediano|1.195 Mbit/s|0.872–2.157 Mbit/s|

Queste fasce **non sono intervalli di confidenza** e non coprono tutti gli errori del modello.
A 512 kbit/s Rice supera già il criterio hardware; fra 512 kbit/s e le soglie stimate
non ci sono nuove misure. Il vincolo p95 del criterio originale resta da verificare.

## Metodo

Per ciascun metodo si adatta `T(R) = a/R + b`, con T in millisecondi e R in Mbit/s,
alle mediane misurate con proxy a 128 e 512 kbit/s. Si risolvono `Traw = Trice`
e `Trice = 0,95*Traw`. Due punti determinano esattamente una curva: il fit non
costituisce una validazione del modello. Le tre coppie di giri di ogni regime
producono nove abbinamenti per esaminare la sensibilità alla variabilità osservata;
i blocchi delle due sessioni non sono coppie temporali corrispondenti.

La Wi-Fi ordinaria non ha una banda effettiva identificata e usa un percorso
senza proxy: non viene trattata come un campione a banda infinita.

## Controllo con un modello ideale

Il risparmio medio è 2074.04 byte/frame. Il costo computazionale aggiuntivo,
accoppiando stesso frame e giro ed escludendo `network_us`, ha mediana 4.018 ms.
La sola relazione `8*byte_risparmiati / costo_aggiuntivo` darebbe un pareggio
ideale di **4.13 Mbit/s**. Non considera differenze di stack, trasferimento,
proxy e variabilità radio. La distanza dalla stima empirica (1.19 Mbit/s)
mostra che non possiamo identificare con precisione una soglia reale da questi dati.
Non va usata come soglia di commutazione verificata.

## Conclusione utilizzabile

Senza ESP32 possiamo proporre **circa 0,6–0,85 Mbit/s come fascia da verificare
per un guadagno mediano del 5%**, con stima centrale intorno a 0,7 Mbit/s.
Il limite più alto per un qualunque guadagno è molto meno identificato.
La prova disponibile più vicina resta quella a 512 kbit/s. Per decidere una soglia
operativa reale servono nuove misure vicino alla fascia stimata, con p95 e più scene;
non basta fare replay sul PC o emulare il tempo della scheda con attese artificiali.

I riferimenti sono velocità del corpo applicativo in upload nel proxy, non PHY Wi-Fi.
La campagna 128 kbit/s conserva la nota di recupero del prefisso USB nel rapporto originale;
nessun tempo è stato stimato o sostituito in quell'archivio.

[Grafico della stima](threshold.png) · [Versione SVG](threshold.svg) · [Dati e assunzioni](summary.json).
