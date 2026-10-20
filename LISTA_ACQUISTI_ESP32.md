# Lista acquisti per le prove SCIoT

Soluzione discussa: una ESP32-S3-DevKitC-1 con camera separata, per iniziare
le prove hardware e successivamente il lavoro con più client.

**La camera resta una candidata: manca ancora la verifica dello schema esatto
dei suoi 18 pin.** Le caratteristiche dichiarate sono adatte, ma questa
combinazione non è stata provata fisicamente con SCIoT.

## Articoli

Prezzi annotati durante la ricerca del 20 ottobre 2026, IVA inclusa e
spedizione esclusa. Prezzi e disponibilità possono cambiare.

| Quantità | Articolo esatto | Negozio e codice | Prezzo annotato | Caratteristiche controllate |
|---|---|---|---:|---|
| 1 | [Espressif ESP32-S3-DevKitC-1-N8R8](https://www.reichelt.com/it/it/shop/prodotto/scheda_di_sviluppo_esp32-s3-wroom-1-n8r8-411139) | Reichelt — `ESP32S3DK-C1N8R8`; codice produttore `ESP32-S3-DEVKITC-1-N8R8` | 17,94 € | ESP32-S3, 8 MB flash, 8 MB PSRAM, pin accessibili, porte Micro-USB. |
| 1 | [Funduino OV2640 Camera Module](https://funduino.com/en/products/ov2640-bildsensor-mit-2mp-kamera-modul) | Funduino — `F23108774` | 9,50 € | Camera su schedina, 2 MP, alimentazione dichiarata a 3,3 V, interfaccia DVP a 8 bit, connettore a 18 pin passo 2,54 mm. Piedinatura esatta ancora da verificare. |
| 1 confezione | [40 cavetti femmina-femmina, 10 cm](https://funduino.com/en/products/40-piece-breadboard-wires-female-female-10cm) | Funduino — `F23108596` | 1,69 € | Connettori femmina su entrambe le estremità, passo 2,54 mm; per collegare i pin maschi dei due moduli. |
| 1 | [Cavo Micro-USB → USB-A, 150 cm, nero](https://funduino.com/products/micro-usb-kabel-auf-usb-a-150cm-schwarz) | Funduino — titolo articolo `Micro-USB Kabel auf USB-A - 150 cm, schwarz` | 1,30 € | Dichiarato per dati e alimentazione; richiede una porta USB-A sul PC. Riutilizzabile un cavo dati equivalente già disponibile. |

**Totale articoli: 30,43 €, più le spedizioni dei due negozi.**
Prima dell'ordine confrontare il totale consegnato con una scheda ESP32-S3
con camera già inclusa: le spedizioni possono ridurre il risparmio.

## Verifiche prima dell'acquisto della camera

- Recuperare lo schema o la piedinatura del modulo Funduino `F23108774`,
  compresi alimentazione, dati, clock, sincronismi, reset e standby.
- Confermare che il connettore sia fornito con pin maschi già saldati,
  per usare direttamente i cavetti femmina-femmina indicati.
- Definire il collegamento alla DevKitC usando GPIO disponibili, senza
  occupare quelli riservati alla memoria.

## Adattamento del software e prove

Il firmware attuale usa i collegamenti della camera della S3-EYE. Con questa
soluzione occorre verificare e adattare la configurazione dei pin, quindi
provare inizializzazione della PSRAM, acquisizione RGB565 a 96×96, inferenza
e comunicazione Wi-Fi. La compatibilità delle specifiche non è ancora una
verifica di funzionamento sull'hardware.

Riferimenti nel repository:

- [Configurazione della scheda](src/client/esp32-s3-eye-mqtt/platformio.ini).
- [Configurazione dei pin camera](src/client/esp32-s3-eye-mqtt/src/conf.template.h).
- [Istruzioni e limiti delle verifiche firmware](src/client/README.md).

Per queste prime prove non servono display, microSD o breadboard.
L'alimentazione iniziale è via USB dal PC. Per iniziare il lavoro multi-client
è sufficiente una scheda fisica affiancata da client Python sul PC;
le prove con più schede reali richiederanno ulteriori dispositivi.

Come concordato, attendere la risposta del professore sulla disponibilità
di una S3-EYE in prestito prima di procedere con gli acquisti.
