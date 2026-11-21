/*
 * Genera presentazione/SCIoT_presentazione.pptx
 *
 * Requisiti: node >= 18 con pptxgenjs@3.12.0, react, react-dom, react-icons, sharp.
 * Uso (dalla radice del repo):
 *   NODE_PATH=<cartella con node_modules> node presentazione/build_deck.js
 * Facoltativo: PPTX_SKILL_DIR=<cartella dello skill pptx> per applicare i colori del tema
 * (scripts/apply_theme.js). Senza, il deck resta valido ma con la palette Office di default.
 *
 * Tutti i numeri provengono dai report citati in presentazione/SPIEGAZIONE_LAVORO.md.
 */
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const Lu = require("react-icons/lu");

const OUT = path.join(__dirname, "SCIoT_presentazione.pptx");

const THEME = {
  name: "SCIoT Teal",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1E293B", lt1: "FFFFFF", dk2: "0B3B3C", lt2: "EEF4F3",
    accent1: "0F766E", accent2: "F59E0B", accent3: "94A3B8",
    accent4: "115E59", accent5: "B45309", accent6: "64748B",
    hlink: "0F766E", folHlink: "115E59",
  },
};
// Hex usati dove pptxgenjs accetta solo hex (grafici, griglie, ombre)
const HX = {
  before: "9AA8BA", after: "0F766E", hi: "F59E0B", grid: "E2E8F0",
  label: "475569", dark: "0B3B3C", text: "1E293B", tint: "EEF4F3", white: "FFFFFF",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "SCIoT: split computing su ESP32";
pres.subject = "Tirocinio Multi Device Split Computing";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333;
const MX = 0.6;
const CW = W - 2 * MX;

// ---------- Layout ----------
pres.defineSlideMaster({
  title: "TITOLO_SCURO",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 2.0, w: 11.5, h: 1.9,
      fontSize: 44, bold: true, color: C.background1, fontFace: THEME.headFontFace, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 4.1, w: 11.0, h: 1.4,
      fontSize: 20, color: C.background2, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENUTO",
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.7, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 0.85,
      fontSize: 34, bold: true, color: C.text2, fontFace: THEME.headFontFace, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "SCIoT · Multi Device Split Computing", options: { x: MX, y: 7.0, w: 6, h: 0.3,
      fontSize: 10, color: C.accent6, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
});
pres.defineSlideMaster({
  title: "CHIUSURA_SCURA",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 0.85,
      fontSize: 34, bold: true, color: C.background1, fontFace: THEME.headFontFace, valign: "middle", align: "left", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3, align: "right" },
});

// ---------- Helper ----------
async function iconPng(Icon, hex) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Icon, { color: "#" + hex, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
async function iconBadge(slide, Icon, x, y, d, name, circle = C.accent1, glyph = HX.white) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: circle }, line: { color: circle }, objectName: name + "-cerchio" });
  const p = d * 0.22;
  slide.addImage({ data: await iconPng(Icon, glyph), x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p, objectName: name + "-icona" });
}
function card(slide, x, y, w, h, name, fill = C.background2) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: name });
}
function txt(slide, text, opts) {
  slide.addText(text, Object.assign({ isTextBox: true, margin: 0, fontSize: 14, color: C.text1, valign: "top" }, opts));
}
function caption(slide, text, x, y, w) {
  txt(slide, text, { x, y, w, h: 0.35, fontSize: 11, italic: true, color: C.accent6, objectName: "didascalia" });
}
function stat(slide, x, y, w, big, label, name, color = C.accent1, size = 44) {
  txt(slide, big, { x, y, w, h: 0.85, fontSize: size, bold: true, color, fontFace: THEME.headFontFace, valign: "bottom", objectName: name + "-valore" });
  txt(slide, label, { x, y: y + 0.9, w, h: 0.6, fontSize: 14, color: C.text1, objectName: name + "-etichetta" });
}
function bullets(slide, items, opts) {
  const runs = [];
  items.forEach((item, i) => {
    const parts = Array.isArray(item) ? item : [{ text: item }];
    parts.forEach((r, j) => {
      const o = Object.assign({}, r.options || {});
      if (j === 0) Object.assign(o, { bullet: { indent: 16 }, paraSpaceAfter: 8 });
      if (j === parts.length - 1 && i < items.length - 1) o.breakLine = true;
      runs.push({ text: r.text, options: o });
    });
  });
  txt(slide, runs, Object.assign({ fontSize: 15 }, opts));
}
// Opzioni grafico: sempre un oggetto nuovo (pptxgenjs muta le opzioni)
function chartOpts(extra) {
  return Object.assign({
    showTitle: true, titleFontSize: 14, titleColor: HX.text, titleFontFace: "+mn-lt",
    catAxisLabelColor: HX.label, valAxisLabelColor: HX.label,
    catAxisLabelFontSize: 12, valAxisLabelFontSize: 11,
    catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
    valGridLine: { color: HX.grid, size: 0.75 }, catGridLine: { style: "none" },
    catAxisLineShow: false, valAxisLineShow: false,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 12, dataLabelColor: HX.text, dataLabelFontFace: "+mn-lt",
    showLegend: false, legendFontSize: 12, legendFontFace: "+mn-lt", legendColor: HX.label, legendPos: "b",
    barGapWidthPct: 60, valAxisMinVal: 0,
  }, extra);
}

// pptxgenjs 3.12 scrive un <a:pPr> prima di ogni run: dopo il primo è fuori schema
// e annulla il punto elenco del paragrafo. Teniamo solo il primo di ogni paragrafo.
async function fixMidParagraphPPr(file) {
  const JSZip = require("jszip");
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  for (const name of Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))) {
    const xml = await zip.file(name).async("string");
    const fixed = xml.replace(/(<\/a:r>)<a:pPr\b(?:[^>]*\/>|[^>]*>[\s\S]*?<\/a:pPr>)/g, "$1");
    zip.file(name, fixed);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  // ===== 1. Titolo =====
  pres.addSection({ title: "Introduzione" });
  let s = pres.addSlide({ masterName: "TITOLO_SCURO", sectionTitle: "Introduzione" });
  s.addText("Split computing su ESP32: cosa abbiamo misurato", { placeholder: "title" });
  s.addText("Tirocinio Multi Device Split Computing · SCIoT · UNIMORE\nOttobre – novembre 2026", { placeholder: "body" });
  await iconBadge(s, Lu.LuCpu, 11.4, 0.7, 1.2, "titolo", C.accent1);
  s.addNotes("Presentazione del lavoro svolto sul fork di SCIoT dal 15 ottobre al 18 novembre. Filo conduttore: ogni ottimizzazione è stata misurata sulla scheda vera e sul ciclo completo, non solo in isolamento.");

  // ===== 2. Problema =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Introduzione" });
  s.addText("Dividere la rete fra scheda e server", { placeholder: "title" });
  const steps = [
    { t: "Camera", d: "frame 96×96", icon: Lu.LuCamera },
    { t: "ESP32-S3", d: "prefisso della rete", icon: Lu.LuCpu },
    { t: "Attivazioni", d: "4.608 B in INT8", icon: Lu.LuWifi },
    { t: "Server", d: "suffisso + risultato", icon: Lu.LuServer },
  ];
  const bw = 2.55, gap = (CW - 4 * bw) / 3, by = 1.55;
  for (let i = 0; i < steps.length; i++) {
    const x = MX + i * (bw + gap);
    card(s, x, by, bw, 1.35, "blocco-" + i, i === 2 ? "FEF3C7" : C.background2);
    await iconBadge(s, steps[i].icon, x + 0.2, by + 0.33, 0.62, "blocco-" + i, i === 2 ? C.accent2 : C.accent1);
    txt(s, steps[i].t, { x: x + 0.98, y: by + 0.28, w: bw - 1.05, h: 0.4, fontSize: 17, bold: true, color: C.text2 });
    txt(s, steps[i].d, { x: x + 0.98, y: by + 0.7, w: bw - 1.05, h: 0.55, fontSize: 14 });
    if (i < steps.length - 1) {
      s.addShape(pres.shapes.LINE, { x: x + bw + 0.08, y: by + 0.675, w: gap - 0.16, h: 0, line: { color: C.accent6, width: 2, endArrowType: "triangle" }, objectName: "freccia-" + i });
    }
  }
  txt(s, "Il relatore aveva indicato due punti deboli", { x: MX, y: 3.75, w: 6, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  card(s, MX, 4.3, 5.85, 1.05, "debole-1");
  txt(s, [{ text: "Comunicazione  ", options: { bold: true } }, { text: "il percorso originale invia attivazioni float32 (18.432 B) più l'immagine" }], { x: MX + 0.25, y: 4.42, w: 5.4, h: 0.85, fontSize: 15 });
  card(s, MX, 5.5, 5.85, 1.05, "debole-2");
  txt(s, [{ text: "Un solo client  ", options: { bold: true } }, { text: "stato e statistiche condivisi fra dispositivi" }], { x: MX + 0.25, y: 5.62, w: 5.4, h: 0.85, fontSize: 15 });
  txt(s, "Domanda guida", { x: 7.1, y: 3.75, w: 5.6, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  txt(s, "Quando il risparmio di trasmissione compensa il costo di calcolo e memoria sul dispositivo, mantenendo predizioni fedeli?",
    { x: 7.1, y: 4.3, w: 5.6, h: 1.4, fontSize: 20, italic: true, color: C.accent1, fontFace: THEME.headFontFace });
  txt(s, "Modello: FOMO Beer/can · split block_2_add (un solo tensore 24×24×8)", { x: 7.1, y: 5.9, w: 5.6, h: 0.6, fontSize: 14, color: C.accent6 });
  s.addNotes("SCIoT esegue i primi layer sulla scheda e invia le attivazioni al server. Lo split block_2_add è stato scelto perché richiede un solo tensore di confine: altri tagli, a causa dei rami residui, ne richiedono più di uno. I due punti deboli indicati: comunicazione e gestione di un solo client.");

  // ===== 3. Setup e metodo =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Introduzione" });
  s.addText("Setup e metodo di misura", { placeholder: "title" });
  txt(s, "Banco di prova", { x: MX, y: 1.45, w: 5, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  bullets(s, [
    [{ text: "Due ESP32-S3-EYE ", options: { bold: true } }, { text: "(A e B): 240 MHz, PSRAM 8 MB, camera" }],
    [{ text: "TFLite Micro + ESP-NN ", options: { bold: true } }, { text: "kernel ottimizzati per ESP32-S3" }],
    [{ text: "FOMO 96×96 ", options: { bold: true } }, { text: "pubblico, non riaddestrato" }],
    [{ text: "Server Python ", options: { bold: true } }, { text: "su PC fisso o laptop" }],
    [{ text: "Reti: ", options: { bold: true } }, { text: "hotspot Pixel + ADB (fino al 10/11), router (dal 16/11)" }],
  ], { x: MX, y: 2.0, w: 5.3, h: 3.6 });
  const method = [
    { icon: Lu.LuHardDrive, t: "Backup della flash", d: "8 MiB salvati, ripristinati e verificati dopo ogni prova" },
    { icon: Lu.LuTarget, t: "Criteri prefissati", d: "es. mediana ≥ −5% e p95 ≤ +5% in tutte le coppie" },
    { icon: Lu.LuRepeat, t: "Ordini alternati", d: "più avvii e ordine A/B ruotato contro la deriva della rete" },
    { icon: Lu.LuShieldCheck, t: "Verifica byte per byte", d: "attivazioni e uscite confrontate con il riferimento" },
  ];
  for (let i = 0; i < method.length; i++) {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 6.4 + col * 3.25, y = 1.45 + row * 2.6;
    card(s, x, y, 3.05, 2.35, "metodo-" + i);
    await iconBadge(s, method[i].icon, x + 0.25, y + 0.25, 0.65, "metodo-" + i);
    txt(s, method[i].t, { x: x + 0.25, y: y + 1.0, w: 2.6, h: 0.4, fontSize: 16, bold: true, color: C.text2 });
    txt(s, method[i].d, { x: x + 0.25, y: y + 1.42, w: 2.6, h: 0.85, fontSize: 14 });
  }
  s.addNotes("Ogni esperimento segue lo stesso protocollo: backup completo della flash prima di caricare firmware sperimentali, criteri decisi prima delle misure, ordini alternati per non confondere la variabilità della rete con un effetto, e verifica byte per byte delle uscite. Report e hash sono in Git; log, firmware e backup restano locali.");

  // ===== 4. Timeline =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Introduzione" });
  s.addText("Il percorso in cinque settimane", { placeholder: "title" });
  const tl = [
    ["15–18 ott", "Compressione delle attivazioni su PC"],
    ["27 ott", "INT8 + ESP-NN sulla scheda"],
    ["30 ott–1 nov", "Codec lossless e soglia Rice"],
    ["9 nov", "Due ESP32 reali con HTTP v2"],
    ["9–10 nov", "Ingresso con tabella (LUT)"],
    ["10–16 nov", "Prefisso: PAD e memoria"],
    ["17 nov", "Causa dei blocchi: XCLK"],
    ["18 nov", "Trasporti e frame skip"],
  ];
  const ly = 4.0, lx0 = MX + 1.15, lx1 = W - MX - 1.15;
  s.addShape(pres.shapes.LINE, { x: lx0, y: ly, w: lx1 - lx0, h: 0, line: { color: C.accent3, width: 2 }, objectName: "asse-tempo" });
  const step = (lx1 - lx0) / (tl.length - 1);
  for (let i = 0; i < tl.length; i++) {
    const cx = lx0 + i * step, up = i % 2 === 0;
    const star = [1, 3, 4, 6].includes(i);
    s.addShape(pres.shapes.OVAL, { x: cx - 0.14, y: ly - 0.14, w: 0.28, h: 0.28, fill: { color: star ? C.accent2 : C.accent1 }, line: { color: C.background1, width: 2 }, objectName: "tappa-" + i });
    const bx = cx - 1.15;
    txt(s, tl[i][0], { x: bx, y: up ? ly - 1.55 : ly + 0.35, w: 2.3, h: 0.35, fontSize: 14, bold: true, color: C.accent1, align: "center" });
    txt(s, tl[i][1], { x: bx, y: up ? ly - 1.15 : ly + 0.72, w: 2.3, h: 0.8, fontSize: 14, align: "center" });
  }
  txt(s, "In arancione le tappe con i risultati principali", { x: MX, y: 6.35, w: 8, h: 0.35, fontSize: 12, italic: true, color: C.accent6 });
  s.addNotes("Prima abbiamo lavorato sui dati da trasmettere (compressione, quantizzazione), poi sul sistema reale: più client, ciclo camera, memoria, e infine la rete. Le tappe in arancione sono quelle con i risultati più forti, approfondite nelle prossime slide.");

  // ===== 5. INT8 =====
  pres.addSection({ title: "Dati e comunicazione" });
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Dati e comunicazione" });
  s.addText("INT8 + ESP-NN: cinque volte più veloce", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "FLOAT32", labels: ["Prefisso sulla scheda", "Tempo completo (risposta)"], values: [813.7, 859.9] },
    { name: "INT8 + ESP-NN", labels: ["Prefisso sulla scheda", "Tempo completo (risposta)"], values: [94.6, 161.8] },
  ], chartOpts({ x: MX, y: 1.35, w: 7.3, h: 4.9, barDir: "col", title: "Latenza mediana (ms), immagini identiche",
    chartColors: [HX.before, HX.after], showLegend: true, valAxisMaxVal: 1000, dataLabelFormatCode: "0" , objectName: "grafico-int8" }));
  caption(s, "27 ottobre · ESP32-S3-EYE · split block_2_add · server HTTP sul PC · 816 richieste validate", MX, 6.4, 7.5);
  stat(s, 8.5, 1.5, 4.2, "−75%", "byte delle attivazioni (18.432 → 4.608 B)", "stat-byte");
  stat(s, 8.5, 3.1, 4.2, "1,1 → 5 fps", "camera continua", "stat-fps");
  stat(s, 8.5, 4.7, 4.2, "≈ uguale", "F1 su 84 foto annotate: 96,5% → 96,9%", "stat-qualita", C.accent6);
  s.addNotes("Primo confronto fisico. INT8 riduce di quattro volte i byte e soprattutto permette a ESP-NN di usare le istruzioni vettoriali dell'ESP32-S3: il prefisso passa da 814 a 95 ms. Il tempo completo fino alla risposta da 860 a 162 ms. Qualità sostanzialmente uguale sul campione annotato, ignorando la classe perché l'ordine dei canali beer/can non è confermato.");

  // ===== 6. Compressione =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Dati e comunicazione" });
  s.addText("Comprimere conviene solo con poca banda", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "Byte per frame", labels: ["Raw INT8", "zlib", "Rice temporale"], values: [4608, 3949, 2534] },
  ], chartOpts({ x: MX, y: 1.35, w: 4.6, h: 4.9, barDir: "col", title: "Byte per frame (lossless)",
    chartColors: [HX.before, HX.before, HX.after], dataLabelFormatCode: "#,##0", valAxisMaxVal: 5000, objectName: "grafico-byte" }));
  s.addChart(pres.charts.BAR, [
    { name: "Guadagno mediano", labels: ["128 kbit/s", "512", "600", "800", "900", "1000", "Wi-Fi"], values: [26.9, 8.5, 8.6, 6.3, 5.7, 5.2, -0.8] },
  ], chartOpts({ x: 5.5, y: 1.35, w: 7.2, h: 4.9, barDir: "col", title: "Guadagno di Rice sul raw, latenza mediana (%)",
    chartColors: [HX.after, HX.after, HX.after, HX.after, HX.before, HX.before, HX.before], dataLabelFormatCode: "0.0", valAxisMinVal: -5, valAxisMaxVal: 30, objectName: "grafico-soglia" }));
  caption(s, "30 ott – 1 nov · proxy che limita la banda della richiesta · verde = criterio superato (mediana ≥ −5%, p95 ≤ +5%)", MX, 6.4, CW);
  s.addNotes("Dopo INT8 il messaggio da 4.608 byte si può ancora comprimere senza perdita. zlib risparmia il 14% ma costa 6,8 ms e peggiora il ciclo. Rice temporale arriva a -45% e con il decoder C++ sul server costa poco, ma su una Wi-Fi normale non migliora la latenza. Il criterio è superato solo fino a 800 kbit/s: la soglia osservata è fra 800 e 900. Messaggio: meno byte non significa meno attesa; il risultato utile è la soglia.");

  // ===== 7. Multi-client =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Dati e comunicazione" });
  s.addText("Più client: HTTP v2 su due ESP32 reali", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "Scheda A", labels: ["Da sola", "Insieme, 1.000 frame", "Insieme, un'ora"], values: [245.7, 246.0, 244.9] },
    { name: "Scheda B", labels: ["Da sola", "Insieme, 1.000 frame", "Insieme, un'ora"], values: [247.0, 248.1, 246.8] },
  ], chartOpts({ x: MX, y: 1.35, w: 6.9, h: 4.9, barDir: "col", title: "Ciclo camera p50 (ms): la concorrenza non lo peggiora",
    chartColors: [HX.after, HX.hi], showLegend: true, dataLabelFormatCode: "0", valAxisMaxVal: 300, objectName: "grafico-multiclient" }));
  caption(s, "9 novembre · hotspot Pixel + ADB · 1 worker × 1 thread · coda server p95 ≈ 0,1 ms", MX, 6.4, 7);
  stat(s, 8.1, 1.4, 4.6, "34.296", "richieste, tutte 200 e identiche al replay", "stat-richieste");
  stat(s, 8.1, 2.95, 4.6, "1 ora", "due schede in continuo: 14.137 e 14.162 frame", "stat-ora");
  card(s, 8.1, 4.6, 4.6, 1.55, "parallelismo");
  txt(s, [{ text: "Server: 1 → 4 worker\n", options: { bold: true, color: C.text2 } },
    { text: "motore 3,15× più veloce, HTTP solo +2,9%: il limite è il servizio (ricezione, log), non il calcolo" }],
    { x: 8.35, y: 4.75, w: 4.15, h: 1.3, fontSize: 14 });
  s.addNotes("Il servizio HTTP v2 separa lo stato per dispositivo, sessione e richiesta e ha una coda limitata. Con due schede reali: prove singole, insieme, riavvio di A mentre B continua, un'ora continua. 34.296 richieste corrette. Sul PC il motore scala con i worker ma il servizio HTTP quasi no, quindi il default resta 1 worker e 1 thread.");

  // ===== 8. Dove va il tempo =====
  pres.addSection({ title: "Ciclo sulla scheda" });
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Ciclo sulla scheda" });
  s.addText("Dove va il tempo del ciclo camera", { placeholder: "title" });
  const phases = [["Acquisizione", 75], ["RGB565 → float", 8.5], ["float → INT8", 38.6], ["Prefisso", 95], ["HTTP", 65]];
  const phaseColors = [HX.before, "C7D2DD", HX.hi, HX.after, "5B7083"];
  s.addChart(pres.charts.BAR, phases.map(([n, v]) => ({ name: n, labels: ["Ciclo ~284 ms"], values: [v] })),
    chartOpts({ x: MX, y: 1.35, w: CW, h: 2.6, barDir: "bar", barGrouping: "stacked", title: "Mediane per fase (ms), scheda B, rete buona",
      chartColors: phaseColors, showLegend: true, legendPos: "b", dataLabelPosition: "ctr", dataLabelFormatCode: "0", dataLabelColor: HX.white,
      catAxisHidden: true, valAxisMaxVal: 290, barGapWidthPct: 30, objectName: "grafico-fasi" }));
  caption(s, "12 novembre · prova di capienza, fase con rete buona · impacchettamento 1,1 ms non mostrato · mediane non additive, ciclo p50 284 ms", MX, 4.0, CW);
  const levers = [
    ["Prefisso", "95 ms · 33%", "PAD veloce e memoria interna (slide 10)", C.accent1],
    ["Acquisizione + HTTP", "~140 ms · 49%", "keep-alive, e poi la scoperta XCLK (slide 11)", C.accent6],
    ["float → INT8", "39 ms · 14%", "tabella LUT: quasi azzerato (slide 9)", C.accent2],
  ];
  for (let i = 0; i < levers.length; i++) {
    const x = MX + i * 4.1;
    card(s, x, 4.6, 3.9, 1.95, "leva-" + i);
    txt(s, levers[i][1], { x: x + 0.25, y: 4.75, w: 3.4, h: 0.55, fontSize: 24, bold: true, color: levers[i][3], fontFace: THEME.headFontFace });
    txt(s, levers[i][0], { x: x + 0.25, y: 5.32, w: 3.4, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
    txt(s, levers[i][2], { x: x + 0.25, y: 5.7, w: 3.4, h: 0.75, fontSize: 14 });
  }
  s.addNotes("Prima di ottimizzare abbiamo scomposto il ciclo: così si sceglie in base alla quota sul tempo totale, non al guadagno isolato. Il prefisso è un terzo del ciclo, acquisizione e rete quasi metà, la conversione in INT8 il 14%: 39 ms spesi in calcoli double fatti in software.");

  // ===== 9. LUT =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Ciclo sulla scheda" });
  s.addText("Tabella per l'ingresso: ciclo −27%", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "Conversione", labels: ["Originale (double)", "Tabella LUT"], values: [47.2, 1.3] },
  ], chartOpts({ x: MX, y: 1.35, w: 4.3, h: 4.9, barDir: "col", title: "Conversione RGB565 → INT8 (ms)",
    chartColors: [HX.before, HX.after], dataLabelFormatCode: "0.0", valAxisMaxVal: 55, objectName: "grafico-conversione" }));
  s.addChart(pres.charts.BAR, [
    { name: "Originale", labels: ["A da sola (3×1.000)", "A insieme a B", "B insieme ad A"], values: [336.2, 377.2, 265.6] },
    { name: "Con LUT", labels: ["A da sola (3×1.000)", "A insieme a B", "B insieme ad A"], values: [244.8, 204.8, 198.2] },
  ], chartOpts({ x: 5.2, y: 1.35, w: 7.5, h: 4.9, barDir: "col", title: "Ciclo completo con HTTP, p50 (ms)",
    chartColors: [HX.before, HX.after], showLegend: true, dataLabelFormatCode: "0", valAxisMaxVal: 420, objectName: "grafico-lut-ciclo" }));
  caption(s, "9–10 novembre · hotspot Pixel + ADB · tabella da 64 KiB in PSRAM · zero differenze sui 65.536 colori", MX, 6.4, CW);
  s.addNotes("Ogni pixel passava per un calcolo in double, che l'ESP32-S3 esegue in software. Ma l'uscita INT8 dipende solo dal valore RGB565: 65.536 casi, precalcolati in una tabella da 64 KiB. Conversione da 47 a 1,3 ms, verificata su tutti i colori. Sul ciclo completo con HTTP: -27% sulla mediana delle tre ripetizioni, confermato con due schede insieme. L'ora di stabilità si era interrotta per un 408: era il problema di rete e camera della slide 11, non la LUT.");

  // ===== 10. Prefisso =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Ciclo sulla scheda" });
  s.addText("Prefisso: più veloce e più leggero", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "Invoke", labels: ["Originale", "PAD veloce", "+ RAM interna"], values: [93.9, 84.5, 62.3] },
  ], chartOpts({ x: MX, y: 1.35, w: 4.9, h: 4.6, barDir: "col", title: "Tempo di Invoke() del prefisso (ms)",
    chartColors: [HX.before, HX.after, HX.after], dataLabelFormatCode: "0.0", valAxisMaxVal: 110, objectName: "grafico-invoke" }));
  s.addChart(pres.charts.BAR, [
    { name: "Picco", labels: ["Con PAD", "Senza PAD", "+ strisce a 3 righe"], values: [225.8, 178.7, 145.8] },
  ], chartOpts({ x: 5.7, y: 1.35, w: 3.9, h: 4.6, barDir: "col", title: "Picco attivazioni (kB)",
    chartColors: [HX.before, HX.after, HX.after], dataLabelFormatCode: "0", valAxisMaxVal: 260, objectName: "grafico-picco" }));
  card(s, 9.85, 1.45, 2.88, 4.4, "nota-ram");
  txt(s, [{ text: "Perché non è la priorità\n", options: { bold: true, color: C.text2, fontSize: 16 } },
    { text: "La RAM interna fa risparmiare ~22 ms su un ciclo di 280–580 ms, e con Wi-Fi e camera la memoria interna è scarsa. Con l'allocazione anticipata l'arena entra (~70 KB liberi)." }],
    { x: 10.08, y: 1.65, w: 2.42, h: 4.0, fontSize: 14 });
  caption(s, "10–16 novembre · scheda B senza rete né camera · stesse uscite byte per byte in ogni variante", MX, 6.2, CW);
  s.addNotes("La profilazione per operatore ha mostrato il PAD al 15,6%: è solo una copia con bordo, ma il kernel generico visita ogni elemento. Con copie per righe passa da 14,6 a 5,2 ms. Spostando le attivazioni in RAM interna Invoke scende a 62 ms, ma è un limite superiore misurato senza Wi-Fi e camera. Per farle entrare abbiamo tolto il nodo PAD e ridotto il buffer a strisce della depthwise: picco da 226 a 146 kB. Rispetto al ciclo il guadagno è piccolo, quindi non è la leva principale.");

  // ===== 11. XCLK =====
  pres.addSection({ title: "Rete e camera" });
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Rete e camera" });
  s.addText("La causa dei blocchi: il clock della camera", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "Risposte", labels: ["Wi-Fi senza camera", "Camera, XCLK acceso", "Camera, XCLK spento"], values: [100, 13.7, 100] },
  ], chartOpts({ x: MX, y: 1.35, w: 6.2, h: 4.8, barDir: "col", title: "Ping con risposta entro 1 s (%)",
    chartColors: [HX.before, HX.hi, HX.after], dataLabelFormatCode: "0", valAxisMaxVal: 115, objectName: "grafico-xclk" }));
  caption(s, "17 novembre · scheda B · 3 avvii, 1.500 ping · 82/600 con XCLK acceso, 600/600 spento", MX, 6.3, 6.4);
  txt(s, "Prima", { x: 7.3, y: 1.45, w: 2.6, h: 0.4, fontSize: 16, bold: true, color: C.accent6 });
  txt(s, "HTTP 408 dopo poche decine di richieste con la camera accesa. Porta, cavo, PSRAM: nessun effetto.", { x: 7.3, y: 1.85, w: 5.4, h: 0.9, fontSize: 15 });
  txt(s, "Causa", { x: 7.3, y: 2.85, w: 2.6, h: 0.4, fontSize: 16, bold: true, color: C.accent2 });
  txt(s, "cam_stop() ferma l'acquisizione ma lascia acceso XCLK a 16 MHz. Spegnerlo ripristina la rete in tutte le 12 commutazioni.", { x: 7.3, y: 3.25, w: 5.4, h: 0.9, fontSize: 15 });
  txt(s, "Dopo", { x: 7.3, y: 4.25, w: 2.6, h: 0.4, fontSize: 16, bold: true, color: C.accent1 });
  txt(s, [{ text: "18.900 / 18.900 ", options: { bold: true, color: C.accent1 } }, { text: "richieste senza timeout, con XCLK acceso solo durante l'acquisizione." }], { x: 7.3, y: 4.65, w: 5.4, h: 0.9, fontSize: 15 });
  txt(s, "Il meccanismo fisico (interferenza o carico elettrico) non è ancora distinto.", { x: 7.3, y: 5.7, w: 5.4, h: 0.6, fontSize: 13, italic: true, color: C.accent6 });
  s.addNotes("Per settimane le richieste HTTP si bloccavano con la camera accesa e il problema sembrava seguire cavo e porta USB. Leggendo il driver: cam_stop ferma l'acquisizione ma non il clock XCLK. Esperimento: con XCLK acceso rispondono 82 ping su 600, spento 600 su 600, riproducibile in tutte le commutazioni. Soluzione: clock acceso solo mentre si acquisisce il frame. Non sappiamo ancora se sia interferenza o carico elettrico: servirebbe un oscilloscopio.");

  // ===== 12. Trasporti e costo XCLK =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Rete e camera" });
  s.addText("Stabile, ma ora domina il riavvio del sensore", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "p50", labels: ["HTTP persistente", "WebSocket", "HTTP con chiusura"], values: [709.8, 711.3, 754.3] },
    { name: "p95", labels: ["HTTP persistente", "WebSocket", "HTTP con chiusura"], values: [792.6, 798.2, 820.5] },
  ], chartOpts({ x: MX, y: 1.35, w: 6.6, h: 4.8, barDir: "col", title: "Ciclo camera per trasporto (ms)",
    chartColors: [HX.after, HX.before], showLegend: true, dataLabelFormatCode: "0", valAxisMaxVal: 900, objectName: "grafico-trasporti" }));
  caption(s, "18 novembre · B · 9 avvii a ordine ruotato · 9.000 frame reali · router domestico", MX, 6.3, 6.6);
  s.addChart(pres.charts.DOUGHNUT, [
    { name: "Ciclo", labels: ["Riavvio sensore e acquisizione", "Conversione, prefisso, invio"], values: [601, 109] },
  ], { x: 7.4, y: 1.3, w: 3.0, h: 3.3, holeSize: 62, chartColors: [HX.hi, HX.after], showLegend: true, legendPos: "b", legendFontSize: 11, legendFontFace: "+mn-lt", legendColor: HX.label, showValue: false, showPercent: true,
    dataLabelColor: HX.white, dataLabelFontSize: 12, dataLabelFontFace: "+mn-lt", showTitle: false, objectName: "grafico-ciambella" });
  txt(s, [{ text: "~600 ms ", options: { bold: true, color: C.accent5 } }, { text: "su ~710 per frame: attesa di 200 ms e primo frame scartato a ogni riaccensione" }],
    { x: 10.5, y: 1.7, w: 2.25, h: 2.3, fontSize: 14 });
  card(s, 7.5, 4.85, 5.25, 1.35, "scelta-trasporto");
  txt(s, [{ text: "Scelta: HTTP persistente\n", options: { bold: true, color: C.text2 } },
    { text: "uguale a WebSocket (< 2%), 12 KB di RAM interna in più; riusare la connessione fa risparmiare ~45 ms" }],
    { x: 7.75, y: 4.98, w: 4.8, h: 1.15, fontSize: 14 });
  s.addNotes("Con la gestione di XCLK abbiamo confrontato tre trasporti in nove avvii: 18.900 richieste su 18.900. HTTP persistente e WebSocket sono equivalenti; HTTP persistente lascia 12 KB di RAM interna in più. Attenzione al confronto con i 245 ms della LUT: sono configurazioni diverse. Oggi il ciclo è stabile ma circa 600 ms su 710 servono a riavviare il sensore. Ridurre questo costo è la leva più grande rimasta.");

  // ===== 13. Frame skip =====
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Rete e camera" });
  s.addText("Frame skip: meno invii, attenzione agli eventi", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [
    { name: "Richieste", labels: ["Baseline", "Skip, rinnovo 1,5 s", "Skip, rinnovo 5 s"], values: [100, 34, 12] },
  ], chartOpts({ x: MX, y: 1.35, w: 5.8, h: 4.8, barDir: "col", title: "Richieste camera su 100 frame",
    chartColors: [HX.before, HX.after, HX.after], dataLabelFormatCode: "0", valAxisMaxVal: 115, objectName: "grafico-skip" }));
  caption(s, "18 novembre · B · soglia globale 32 · decisione ≈ 0,63 ms per frame", MX, 6.3, 6);
  stat(s, 6.9, 1.45, 2.8, "726 → 603", "ciclo p50 (ms) con skip attivo", "stat-skip-ciclo", C.accent1, 32);
  stat(s, 9.9, 1.45, 2.85, "−66 / −88%", "byte HTTP dei frame", "stat-skip-byte", C.accent1, 32);
  card(s, 6.9, 3.4, 5.85, 2.75, "qualita-skip");
  txt(s, "Il costo da controllare", { x: 7.15, y: 3.55, w: 5.4, h: 0.4, fontSize: 16, bold: true, color: C.text2 });
  bullets(s, [
    "Rinnovo a 5 s: nel replay perde 6–7 eventi su 9–10",
    "Sulla camera, allo stesso budget, l'invio uniforme perde meno eventi (4 contro 5 su 13)",
    [{ text: "Candidata: ", options: { bold: true } }, { text: "soglia 8 con rinnovo 1,5 s, nessun evento perso nel replay e un terzo di invii in meno" }],
  ], { x: 7.15, y: 4.0, w: 5.4, h: 2.1, fontSize: 14 });
  s.addNotes("Se il frame è quasi uguale all'ultimo inviato non eseguiamo il prefisso e non inviamo. Invii e byte crollano, il ciclo scende da 726 a 603 ms. Ma il punto è la qualità: con rinnovo lungo si perdono eventi brevi e, a parità di invii, l'invio uniforme ha fatto meglio. La soglia 8 con rinnovo 1,5 s è la candidata da verificare sulla camera.");

  // ===== 14. Riepilogo =====
  pres.addSection({ title: "Conclusioni" });
  s = pres.addSlide({ masterName: "CONTENUTO", sectionTitle: "Conclusioni" });
  s.addText("Riepilogo: prima e dopo", { placeholder: "title" });
  const hdr = (t) => ({ text: t, options: { bold: true, color: HX.white, fill: { color: HX.dark } } });
  const rows = [
    [hdr("Leva"), hdr("Prima"), hdr("Dopo"), hdr("Condizioni")],
    ["INT8 + ESP-NN, tempo completo", "860 ms", "162 ms", "27 ott, immagini identiche"],
    ["INT8, byte delle attivazioni", "18.432 B", "4.608 B", "split block_2_add"],
    ["Rice temporale, byte per frame", "4.608 B", "2.534 B", "lossless, conviene < ~800 kbit/s"],
    ["Conversione dell'ingresso (LUT)", "47 ms", "1,3 ms", "locale, verifica su 65.536 colori"],
    ["Ciclo completo con LUT", "336 ms", "245 ms", "hotspot Pixel, 3 × 1.000 frame"],
    ["Invoke() con PAD veloce", "93,9 ms", "84,5 ms", "senza rete né camera"],
    ["Picco attivazioni del prefisso", "226 kB", "146 kB", "senza PAD + strisce a 3 righe"],
    ["Ping con camera inizializzata", "82/600", "600/600", "XCLK acceso → spento"],
    ["Ciclo, HTTP chiusura → persistente", "754 ms", "710 ms", "router, XCLK gestito"],
    ["Più client", "1, stato condiviso", "2 ESP32 per 1 h", "34.296 richieste corrette"],
  ].map((r, i) => i === 0 ? r : r.map((c, j) => ({ text: c, options: { bold: j === 2, color: j === 2 ? HX.after : HX.text, fill: { color: i % 2 ? HX.white : HX.tint } } })));
  s.addTable(rows, { x: MX, y: 1.4, w: CW, colW: [4.0, 1.9, 2.1, 4.13], fontSize: 14, fontFace: THEME.bodyFontFace,
    rowH: 0.45, border: { type: "solid", pt: 0.5, color: HX.grid }, valign: "middle", margin: [0, 0.1, 0, 0.1], objectName: "tabella-riepilogo" });
  s.addNotes("Tabella di riepilogo da lasciare a schermo durante la discussione. Ogni riga ha le sue condizioni: le righe non vanno sommate fra loro né confrontate fra configurazioni diverse.");

  // ===== 15. Conclusioni =====
  s = pres.addSlide({ masterName: "CHIUSURA_SCURA", sectionTitle: "Conclusioni" });
  s.addText("Cosa abbiamo imparato e i prossimi passi", { placeholder: "title" });
  const lessons = [
    [Lu.LuScale, "Meno byte non è meno attesa", "Ogni codec va pesato sul ciclo completo e sulla rete reale"],
    [Lu.LuGauge, "Misurare la quota sul ciclo", "Si ottimizza la fase che pesa di più, non quella più comoda"],
    [Lu.LuShieldCheck, "Equivalenza verificata", "Ogni ottimizzazione lossless è confrontata byte per byte"],
  ];
  for (let i = 0; i < lessons.length; i++) {
    const y = 1.55 + i * 1.6;
    await iconBadge(s, lessons[i][0], MX, y, 0.75, "lezione-" + i, C.accent1);
    txt(s, lessons[i][1], { x: MX + 1.0, y, w: 4.9, h: 0.45, fontSize: 18, bold: true, color: C.background1 });
    txt(s, lessons[i][2], { x: MX + 1.0, y: y + 0.48, w: 4.9, h: 0.8, fontSize: 14, color: C.background2 });
  }
  txt(s, "Prossimi passi", { x: 7.2, y: 1.5, w: 5.5, h: 0.45, fontSize: 20, bold: true, color: C.accent2 });
  bullets(s, [
    [{ text: "Ridurre i ~600 ms della gestione XCLK ", options: { bold: true } }, { text: "(attesa, frame scartati, alimentazione)" }],
    [{ text: "Portare nel client operativo ", options: { bold: true } }, { text: "LUT, keep-alive, PAD veloce" }],
    [{ text: "Frame skip con soglia 8 ", options: { bold: true } }, { text: "su scene con eventi annotati" }],
    [{ text: "Qualità su scene indipendenti ", options: { bold: true } }, { text: "e conferma delle classi" }],
    [{ text: "Possibili temi di tesi: ", options: { bold: true } }, { text: "altri split, pipeline, frequenza adattiva" }],
  ], { x: 7.2, y: 2.1, w: 5.5, h: 4.4, fontSize: 15, color: C.background1 });
  s.addNotes("Tre lezioni metodologiche e cinque prossimi passi. Il più importante è ridurre il costo della gestione del clock della camera, che oggi occupa la maggior parte del ciclo. Poi portare nel client operativo le ottimizzazioni già verificate.");

  await pres.writeFile({ fileName: OUT });
  await fixMidParagraphPPr(OUT);
  const skill = process.env.PPTX_SKILL_DIR;
  if (skill && fs.existsSync(path.join(skill, "scripts/apply_theme.js"))) {
    const { applyTheme } = require(path.join(skill, "scripts/apply_theme.js"));
    await applyTheme(OUT, THEME);
  } else {
    console.warn("PPTX_SKILL_DIR non impostata: tema non applicato");
  }
  console.log("Scritto", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
