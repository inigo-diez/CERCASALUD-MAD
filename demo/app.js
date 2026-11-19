/* CercaSalud MAD: página web al estilo WikiBarrio (SPEC P-28).
   Este archivo solo dibuja: todas las cifras y los textos vienen ya preparados en `datos/` por el
   exportador de Python (`src/cercasalud/web.py`; R-UI-01). No pide nada a internet.

   El mapa colorea secciones censales enteras con borde blanco y las calles encima, como WikiBarrio.
   Al pulsar una zona se puede desglosar en 3D: sus capas (población, red, minutos y renta) se separan
   en altura sobre el propio mapa. */
'use strict';

const $ = (id) => document.getElementById(id);
const FONDO = [236, 236, 236];
const NEGRO = [26, 26, 26];
const BLANCO = [255, 255, 255];
const GRIS_NO_EVALUABLE = [190, 190, 190];
const OPACIDAD = 225;                 // las zonas dejan ver un poco el fondo, como en WikiBarrio
const FUENTE = 'Segoe UI, Arial, sans-serif';

const E = {            // estado de la página
  paso: 'diagnosticar', variable: null, territorio: null, cartera: null,
  centros: false, mercados: false, cambia: false, zoom: 8, demo: 0, seccion: null, desglose: null,
};
const D = {};          // datos leídos

function rgb(hex) { return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)); }
function conAlfa(color, alfa) { return [color[0], color[1], color[2], alfa]; }
function el(etiqueta, atributos = {}, hijos = []) {
  const nodo = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(atributos)) {
    if (k === 'texto') nodo.textContent = v; else if (k === 'clase') nodo.className = v; else nodo.setAttribute(k, v);
  }
  for (const h of [].concat(hijos)) if (h) nodo.append(h);
  return nodo;
}
async function leer(ruta) {
  const respuesta = await fetch(ruta);
  if (!respuesta.ok) throw new Error(`No se pudo leer ${ruta} (${respuesta.status})`);
  return respuesta.json();
}
/* Punto de miles en todos los enteros, como en las cifras que prepara Python («2.151», no «2151»). */
function miles(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.'); }
function escapar(texto) {
  return String(texto).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]);
}

/* ---------------------------------------------------------------- carga */

async function arrancar() {
  try {
    const rutas = ['datos/mapa.json', 'datos/carteras.json', 'datos/puntos.json', 'datos/textos.json',
      'datos/capas/municipios.json', 'datos/capas/secciones.json'];
    const [mapa, carteras, puntos, textos, municipios, secciones] = await Promise.all(rutas.map(leer));
    Object.assign(D, { mapa, carteras, puntos, textos, municipios });
    D.sec = prepararSecciones(secciones);
    D.territorios = Object.fromEntries(mapa.territorios.map((t) => [t.clave, t]));
    D.lineas = {};
    await Promise.all(['limite_municipio', 'limite_distrito', 'via_principal', 'via_capital'].map(async (tipo) => {
      D.lineas[tipo] = await leer(`datos/capas/lineas_${tipo}.json`);
    }));
    E.variable = mapa.variable_inicial;
    E.territorio = mapa.inicial;
    E.cartera = textos.inicio.caso;
    D.caracteres = caracteresRotulos();
    crearMapa();
    montarInterfaz();
    pintarTodo();
    encuadrar(D.territorios[E.territorio].caja, false);
    $('estado-carga').textContent = '';
    aplicarDemo(0);
  } catch (error) {
    $('estado-carga').textContent = `Error: ${error.message}`;
    throw error;
  }
}

/* Deshace la codificación del exportador (`codificar_contorno`): enteros de 1e-5 grados con diferencias. */
function decodificar(plano) {
  let x = plano[0], y = plano[1];
  const puntos = [[x / 1e5, y / 1e5]];
  for (let i = 2; i < plano.length; i += 2) { x += plano[i]; y += plano[i + 1]; puntos.push([x / 1e5, y / 1e5]); }
  return puntos;
}

function prepararSecciones(s) {
  const partes = s.partes.map((anillos, i) => ({ p: anillos.map(decodificar), s: s.seccion_de_parte[i] }));
  const paletas = {};
  for (const [clave, v] of Object.entries(D.mapa.variables)) paletas[clave] = v.paleta.map(rgb);
  paletas.densidad = D.mapa.grises_densidad.map(rgb);
  paletas.refugio = D.mapa.desglose_refugio.paleta.map(rgb);
  return { ...s, partes, paletas };
}

function caracteresRotulos() {
  const letras = new Set();
  for (let i = 32; i < 127; i += 1) letras.add(String.fromCharCode(i));
  const textos = [...Object.values(D.mapa.rotulos).flat().map((r) => r[2]), ...D.mapa.desglose.map((c) => c.nombre),
    D.mapa.desglose_refugio.nombre];
  for (const t of textos) for (const ch of t) letras.add(ch);
  return [...letras].join('');
}

/* ---------------------------------------------------------------- mapa plano */

function crearMapa() {
  D.deck = new deck.Deck({
    parent: $('mapa'),
    views: new deck.MapView({ repeat: false }),
    initialViewState: { longitude: -3.7, latitude: 40.45, zoom: 8, pitch: 0, bearing: 0 },
    controller: { doubleClickZoom: true, dragRotate: false, touchRotate: false },
    layers: [],
    getTooltip: tarjetaFlotante,
    onClick: alPulsar,
    onViewStateChange: ({ viewState }) => {
      const zoom = Math.max(8, Math.min(15, Math.floor(viewState.zoom)));
      if (zoom !== E.zoom) { E.zoom = zoom; pintarMapa(); }
    },
  });
}

function variableActual() { return D.mapa.variables[E.variable]; }
function carteraActual() { return D.carteras.carteras[E.cartera]; }
function enComparar() { return E.paso !== 'diagnosticar' && carteraActual(); }
function modoCambia() { return E.cambia && enComparar() && Boolean(carteraActual().ganan); }

/* Color de una sección para una capa: clase ya calculada en Python → color de la paleta; -1 → gris. */
function colorSeccion(capa, s) {
  const clase = D.sec[`k_${capa}`][s];
  return clase < 0 ? GRIS_NO_EVALUABLE : D.sec.paletas[capa][clase];
}

function cambiaPorSeccion() {
  if (!D.cambiaCache || D.cambiaCache.clave !== E.cartera) {
    const mapa = new Map(carteraActual().ganan.secciones.map((f) => [f[0], f]));
    D.cambiaCache = { clave: E.cartera, mapa };
  }
  return D.cambiaCache.mapa;
}

function capaFondo() {
  const v = variableActual();
  const color = v.escala === 'municipios' ? `c_${E.variable}` : null;
  return new deck.PolygonLayer({
    id: 'municipios', data: D.municipios, getPolygon: (d) => d.p,
    getFillColor: color ? (d) => conAlfa(d[color], OPACIDAD) : FONDO, stroked: color !== null,
    getLineColor: BLANCO, lineWidthMinPixels: 0.8, pickable: v.escala === 'municipios',
    updateTriggers: { getFillColor: E.variable },
  });
}

function capaSecciones() {
  if (variableActual().escala !== 'celdas') return null;
  let color = (d) => conAlfa(colorSeccion(E.variable, d.s), OPACIDAD);
  if (modoCambia()) {
    const [ganan, siguen, ninguno] = D.mapa.leyenda_cambia.map((x) => rgb(x.color));
    const cambios = cambiaPorSeccion();
    color = (d) => {
      const f = cambios.get(d.s);
      return conAlfa(!f ? ninguno : f[1] === 2 ? ganan : siguen, OPACIDAD);
    };
  }
  return new deck.PolygonLayer({
    id: 'secciones', data: D.sec.partes, getPolygon: (d) => d.p, getFillColor: color,
    stroked: true, getLineColor: [255, 255, 255, 230], lineWidthUnits: 'pixels', getLineWidth: E.zoom >= 11 ? 1 : 0.5,
    pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 90],
    updateTriggers: { getFillColor: [E.variable, modoCambia(), E.cartera], getLineWidth: E.zoom >= 11 },
  });
}

function capaSeleccion() {
  if (E.seccion === null) return [];
  const partes = D.sec.partes.filter((d) => d.s === E.seccion);
  const contorno = (id, color, ancho) => new deck.PolygonLayer({
    id, data: partes, getPolygon: (d) => d.p, filled: false, stroked: true, getLineColor: color,
    lineWidthUnits: 'pixels', getLineWidth: ancho, updateTriggers: { getPolygon: E.seccion },
  });
  return [contorno('seleccion-sombra', [26, 26, 26, 120], 6), contorno('seleccion', BLANCO, 3.5)];
}

/* Calles como en WikiBarrio: por encima del color, en blanco translúcido con un borde gris suave. */
function capasLineas() {
  const capas = [];
  const camino = (id, datos, color, ancho) => new deck.PathLayer({
    id, data: datos, getPath: (d) => d.p, getColor: color, getWidth: ancho, widthUnits: 'pixels',
    capRounded: true, jointRounded: true,
  });
  if (E.zoom >= 11) capas.push(camino('via_capital', D.lineas.via_capital, [255, 255, 255, 170], 1.6));
  capas.push(camino('via_principal_borde', D.lineas.via_principal, [160, 160, 160, 120], E.zoom >= 11 ? 5 : 3),
    camino('via_principal', D.lineas.via_principal, [255, 255, 255, 215], E.zoom >= 11 ? 3 : 1.6),
    camino('limite_municipio', D.lineas.limite_municipio, [70, 70, 70, 150], 1.1));
  if (E.zoom >= 11) capas.push(camino('limite_distrito', D.lineas.limite_distrito, [70, 70, 70, 170], 1.4));
  return capas;
}

function capasPuntos() {
  const capas = [];
  if (E.centros) {
    capas.push(new deck.ScatterplotLayer({
      id: 'centros', data: D.puntos.centros, getPosition: (d) => [d.lon, d.lat], getFillColor: NEGRO,
      getLineColor: BLANCO, stroked: true, lineWidthMinPixels: 1.5, getRadius: 120, radiusMinPixels: 4, pickable: true,
    }));
  }
  if (E.mercados) {
    capas.push(new deck.ScatterplotLayer({
      id: 'mercados', data: D.puntos.mercados, getPosition: (d) => [d.lon, d.lat], getFillColor: BLANCO,
      getLineColor: NEGRO, stroked: true, lineWidthMinPixels: 2.5, getRadius: 120, radiusMinPixels: 5, pickable: true,
    }));
  }
  return capas;
}

function capasZonas() {
  const f = carteraActual();
  if (!enComparar() || !f || !f.zonas.length) return [];
  return [
    new deck.ScatterplotLayer({
      id: 'zonas', data: f.zonas, getPosition: (z) => [z.lon, z.lat], getFillColor: NEGRO, getLineColor: BLANCO,
      stroked: true, lineWidthMinPixels: 2.5, getRadius: 250, radiusMinPixels: 12, pickable: true,
      updateTriggers: { getPosition: E.cartera },
    }),
    new deck.TextLayer({
      id: 'zonas-numero', data: f.zonas, getPosition: (z) => [z.lon, z.lat], getText: (z) => String(z.orden),
      getSize: 13, getColor: BLANCO, fontWeight: 'bold', fontFamily: FUENTE, characterSet: '0123456789',
      updateTriggers: { getPosition: E.cartera },
    }),
  ];
}

function capaRotulos() {
  return new deck.TextLayer({
    id: 'rotulos', data: D.mapa.rotulos[String(E.zoom)] || [], getPosition: (r) => [r[0], r[1]],
    getText: (r) => r[2], getSize: (r) => r[3], getColor: NEGRO, fontFamily: FUENTE, fontWeight: 'bold',
    characterSet: D.caracteres, fontSettings: { sdf: true, fontSize: 96, buffer: 16, radius: 16 },
    outlineWidth: 5, outlineColor: [255, 255, 255, 235], updateTriggers: { getPosition: E.zoom },
  });
}

function pintarMapa() {
  if (!D.deck) return;
  if (E.desglose) { D.deck.setProps({ layers: capasDesglose() }); return; }
  const capas = [capaFondo(), capaSecciones(), ...capasLineas(), ...capaSeleccion(), ...capasPuntos(),
    ...capasZonas(), capaRotulos()].filter(Boolean);
  D.deck.setProps({ layers: capas });
}

function anchoPanel() {
  const panel = $('panel');
  return panel.classList.contains('plegado') || window.innerWidth <= 760 ? 28 : panel.offsetWidth;
}

function vistaParaCaja(caja) {
  const ancho = $('mapa').clientWidth, alto = $('mapa').clientHeight;
  return new deck.WebMercatorViewport({ width: ancho, height: alto }).fitBounds(
    [[caja[0], caja[1]], [caja[2], caja[3]]],
    { padding: { left: anchoPanel() + 48, right: 48, top: 80, bottom: 130 } });
}

function encuadrar(caja, animar = true) {
  const vista = vistaParaCaja(caja);
  D.deck.setProps({
    initialViewState: {
      longitude: vista.longitude, latitude: vista.latitude, zoom: Math.min(vista.zoom, 14.5), pitch: 0, bearing: 0,
      position: [0, 0, 0],
      transitionDuration: animar ? 700 : 0, transitionInterpolator: animar ? new deck.FlyToInterpolator() : undefined,
    },
  });
  E.zoom = Math.max(8, Math.min(15, Math.floor(vista.zoom)));
}

/* ---------------------------------------------------------------- tarjeta flotante (como la de WikiBarrio) */

function valorSeccion(capa, s) {
  const t = D.mapa.textos_secciones, v = D.mapa.variables[capa];
  if (capa === 'quintil_renta') {
    const q = D.sec.q[s];
    return { valor: q === null ? t.sin_renta : `Q${q}`, etiqueta: q === null ? '' : `${t.renta} (${D.sec.calidades[D.sec.cq[s]]})` };
  }
  if (capa === 'densidad') return { valor: `${miles(D.sec.densidad[s])} hab/km²`, etiqueta: '' };
  const m = D.sec[`m_${capa}`][s];
  let valor;
  if (D.sec[`k_${capa}`][s] < 0) valor = t.no_evaluable;
  else if (m === null || m > v.ultimo_limite) valor = t.mas_de[capa];
  else valor = `${m} min`;
  return { valor, etiqueta: t.mediana[capa] };
}

function htmlTarjeta(titulo, codigo, valor, etiqueta, extras = []) {
  return `<div class="tarjeta-titulo">${escapar(titulo)} <span>${escapar(codigo || '')}</span></div>`
    + `<div class="tarjeta-valor">${escapar(valor)}</div><div class="tarjeta-etiqueta">${escapar(etiqueta || '')}</div>`
    + extras.map((x) => `<div class="tarjeta-extra">${escapar(x)}</div>`).join('');
}

function tarjetaSeccion(s) {
  const t = D.mapa.textos_secciones, modo = (variableActual() || {}).modo || 'transporte';
  const lugar = D.sec.lugares[D.sec.t[s]];
  const extras = [`${miles(D.sec.g[s])} ${t.habitantes}`,
    `${String(D.sec[`sin_${modo}`][s]).replace('.', ',')} % ${t.sin[modo]}`];
  if (modoCambia()) {
    const f = cambiaPorSeccion().get(s);
    const gana = f ? f[2] : 0, siguen = f ? f[3] : 0;
    return htmlTarjeta(lugar, D.sec.cusec[s], `${miles(gana)} personas`,
      'pasan a tener un centro dentro del umbral con esta cartera', [`${miles(siguen)} siguen sin opción verificada`, extras[0]]);
  }
  const { valor, etiqueta } = valorSeccion(E.variable, s);
  return htmlTarjeta(lugar, D.sec.cusec[s], valor, etiqueta, extras);
}

function tarjetaFlotante({ layer, object }) {
  if (!layer || !object) return null;
  let html;
  if (layer.id === 'secciones') html = tarjetaSeccion(object.s);
  else if (layer.id === 'municipios') html = htmlTarjeta(object.l, '', object[`d_${E.variable}`], '', [object.g]);
  else if (layer.id === 'centros' || layer.id === 'mercados') html = htmlTarjeta(object.nombre, '', '', object.detalle);
  else if (layer.id === 'zonas') html = htmlTarjeta(`Zona ${object.orden}`, object.municipio, '', 'Celda de búsqueda de 250 m (no es un solar)');
  else return null;
  return {
    html, className: 'tarjeta-flotante',
    style: { backgroundColor: '#FFFFFF', color: '#1A1A1A', padding: '12px 16px', borderRadius: '6px',
      border: '1px solid #D0D0D0', boxShadow: '0 3px 12px rgba(0,0,0,.18)', maxWidth: '340px', fontFamily: FUENTE },
  };
}

function alPulsar({ layer, object }) {
  if (!layer || !object || E.desglose) return;
  if (layer.id === 'secciones') {
    E.seccion = object.s;
    const clave = D.sec.territorio[object.s];
    if (D.territorios[clave]) { E.territorio = clave; pintarTerritorio(); pintarLeyenda(); }
    mostrarZonaSenalada(object.s);
    pintarMapa();
  } else if (layer.id === 'municipios') {
    const t = D.mapa.territorios.find((x) => x.tipo === 'municipio' && x.nombre === object.l);
    if (t) { E.territorio = t.clave; pintarTerritorio(); pintarLeyenda(); }
  }
}

function mostrarZonaSenalada(s) {
  const caja = $('zona-senalada'), t = D.mapa.textos_secciones;
  caja.replaceChildren(el('h3', { texto: `Sección ${D.sec.cusec[s]}` }),
    el('p', { clase: 'nota', texto: `${D.sec.lugares[D.sec.t[s]]} · ${miles(D.sec.g[s])} ${t.habitantes}` }));
  for (const capa of ['min_tp_9_13', 'min_tp_16_20', 'min_pie', 'quintil_renta']) {
    caja.append(el('div', { clase: 'cifra-fila' }, [el('span', { texto: D.mapa.variables[capa].titulo }),
      el('b', { texto: valorSeccion(capa, s).valor })]));
  }
  const boton = el('button', { clase: 'principal', texto: `Desglosar ${D.territorios[E.territorio].nombre} en 3D` });
  boton.addEventListener('click', () => abrirDesglose(E.territorio));
  caja.append(boton);
  caja.hidden = false;
  caja.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ---------------------------------------------------------------- desglose en 3D de un territorio
   Las capas del territorio (población, red, minutos a pie, minutos en transporte y renta) se separan
   en altura sobre el mapa con una vista inclinada. Cada capa sube con una traslación vertical
   (`modelMatrix`); no se recalcula ninguna geometría. */

function matrizAltura(z) { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, z, 1]; }

/* Capas del desglose: las cinco comunes y, en Madrid capital (única lista oficial de refugios verificada),
   la de refugios climáticos arriba. */
function capasDeDesglose(clave) {
  const madrid = clave === 'municipio:28079' || clave.startsWith('distrito:');
  return madrid ? [...D.mapa.desglose, D.mapa.desglose_refugio] : D.mapa.desglose;
}

function prepararDesglose(clave) {
  const t = D.territorios[clave], [x0, y0, x1, y1] = t.caja;
  const dentro = (p) => p[0] >= x0 && p[0] <= x1 && p[1] >= y0 && p[1] <= y1;
  const partes = D.sec.partes.filter((d) => D.sec.territorio[d.s] === clave);
  const vias = [...D.lineas.via_principal, ...D.lineas.via_capital].filter((d) => d.p.some(dentro));
  const marco = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  const anchoM = (x1 - x0) * 111320 * Math.cos((y0 + y1) / 2 * Math.PI / 180), altoM = (y1 - y0) * 110540;
  return {
    clave, partes, vias, marco, separacion: 0, capas: capasDeDesglose(clave), objetivo: Math.max(600, 0.36 * Math.max(anchoM, altoM)),
    rotulo: [x1, (y0 + y1) / 2],
    centros: D.puntos.centros.filter((p) => dentro([p.lon, p.lat])),
    mercados: D.puntos.mercados.filter((p) => dentro([p.lon, p.lat])),
  };
}

function capasDesglose() {
  const d = E.desglose, sep = d.separacion, capas = [];
  const comun = { parameters: { depthCompare: 'always', depthWriteEnabled: false } };
  d.capas.forEach((c, nivel) => {
    const mm = matrizAltura(nivel * sep);
    capas.push(new deck.PolygonLayer({
      ...comun, id: `plano-${nivel}`, data: [d.marco], getPolygon: (x) => x, getFillColor: [250, 250, 250, 205],
      getLineColor: [120, 120, 120, 200], stroked: true, lineWidthMinPixels: 1.2, modelMatrix: mm,
    }));
    if (c.capa === 'red') {
      capas.push(new deck.PathLayer({
        ...comun, id: 'desglose-vias', data: d.vias, getPath: (x) => x.p, getColor: [90, 90, 90], getWidth: 1.6,
        widthUnits: 'pixels', modelMatrix: mm,
      }), new deck.ScatterplotLayer({
        ...comun, id: 'desglose-centros', data: d.centros, getPosition: (p) => [p.lon, p.lat], getFillColor: NEGRO,
        getLineColor: BLANCO, stroked: true, lineWidthMinPixels: 1.5, getRadius: 90, radiusMinPixels: 5, modelMatrix: mm,
      }), new deck.ScatterplotLayer({
        ...comun, id: 'desglose-mercados', data: d.mercados, getPosition: (p) => [p.lon, p.lat], getFillColor: BLANCO,
        getLineColor: NEGRO, stroked: true, lineWidthMinPixels: 2.5, getRadius: 90, radiusMinPixels: 6, modelMatrix: mm,
      }));
    } else {
      capas.push(new deck.PolygonLayer({
        ...comun, id: `desglose-${c.capa}`, data: d.partes, getPolygon: (x) => x.p,
        getFillColor: (x) => conAlfa(colorSeccion(c.capa, x.s), 235), stroked: true,
        getLineColor: [255, 255, 255, 200], lineWidthUnits: 'pixels', getLineWidth: 0.6, modelMatrix: mm,
      }));
    }
    capas.push(new deck.TextLayer({
      ...comun, id: `rotulo-${nivel}`, data: [d.rotulo], getPosition: (p) => p, getText: () => `${nivel + 1}. ${c.nombre}`,
      getSize: 15, getColor: NEGRO, fontFamily: FUENTE, fontWeight: 'bold', characterSet: D.caracteres,
      getTextAnchor: 'start', getPixelOffset: [12, 0], fontSettings: { sdf: true, fontSize: 96, buffer: 16, radius: 16 },
      outlineWidth: 5, outlineColor: [255, 255, 255, 235], modelMatrix: mm,
    }));
  });
  return capas;
}

function animarSeparacion(hasta, duracion, alTerminar) {
  const d = E.desglose, desde = d.separacion, inicio = performance.now();
  const paso = (ahora) => {
    if (E.desglose !== d) return;
    const t = Math.min(1, (ahora - inicio) / duracion), suave = t * t * (3 - 2 * t);
    d.separacion = desde + (hasta - desde) * suave;
    pintarMapa();
    if (t < 1) requestAnimationFrame(paso); else if (alTerminar) alTerminar();
  };
  requestAnimationFrame(paso);
}

function abrirDesglose(clave) {
  const t = D.territorios[clave];
  if (!t || t.tipo === 'comunidad') return;
  E.desglose = prepararDesglose(clave);
  document.body.classList.add('en-desglose');
  pintarDesglosePanel();
  const vista = vistaParaCaja(t.caja), niveles = E.desglose.capas.length;
  D.deck.setProps({
    controller: { doubleClickZoom: true, dragRotate: true, touchRotate: true },
    initialViewState: {
      longitude: vista.longitude, latitude: vista.latitude, zoom: vista.zoom - 1.3, pitch: 60, bearing: -22,
      // La vista apunta a algo más de media altura de la pila para que quepa entera sobre la barra de la demo.
      position: [0, 0, E.desglose.objetivo * (niveles - 1) * 0.58], transitionDuration: 1200,
      transitionInterpolator: new deck.LinearInterpolator(['longitude', 'latitude', 'zoom', 'pitch', 'bearing', 'position']),
    },
  });
  animarSeparacion(E.desglose.objetivo, 1400);
}

function cerrarDesglose() {
  if (!E.desglose) return;
  animarSeparacion(0, 700, () => {
    E.desglose = null;
    document.body.classList.remove('en-desglose');
    D.deck.setProps({ controller: { doubleClickZoom: true, dragRotate: false, touchRotate: false } });
    encuadrar(D.territorios[E.territorio].caja);
    pintarMapa();
  });
}

function pintarDesglosePanel() {
  const t = D.territorios[E.desglose.clave];
  const lista = [...E.desglose.capas].map((c, i) => ({ ...c, nivel: i + 1 })).reverse();
  const leyenda = (c) => {
    if (c.capa === 'red') return '';
    const colores = D.sec.paletas[c.capa];
    const etiquetas = c.capa === 'densidad' ? D.sec.etiquetas_densidad
      : c.capa === 'refugio' ? c.etiquetas : D.mapa.variables[c.capa].etiquetas;
    return el('div', { clase: 'leyenda-mini' }, colores.map((color, i) => el('span', {
      style: `background:rgb(${color.join(',')})`, title: etiquetas[i],
    })));
  };
  const cifra = (c) => {
    const modo = { min_pie: 'pie', min_tp_9_13: 'transporte' }[c.capa];
    if (c.capa === 'densidad') return `${t.poblacion} habitantes`;
    if (modo) return `${t.modos[modo].con_acceso} con acceso · ${t.modos[modo].sin_opcion} sin opción verificada`;
    if (c.capa === 'red') return `${E.desglose.centros.length} centros de primaria en el encuadre`;
    if (c.capa === 'refugio') return c.por_territorio[E.desglose.clave] || '';
    return '';
  };
  $('desglose-titulo').textContent = `${t.nombre} en 3D`;
  $('desglose-capas').replaceChildren(...lista.map((c) => el('li', {}, [
    el('b', { texto: `${c.nivel}. ${c.nombre}` }), el('span', { clase: 'nota', texto: c.texto }), leyenda(c),
    el('span', { clase: 'desglose-cifra', texto: cifra(c) })])));
}

/* ---------------------------------------------------------------- panel: diagnosticar */

function montarInterfaz() {
  const variables = $('variables');
  for (const [clave, v] of Object.entries(D.mapa.variables)) {
    const entrada = el('input', { type: 'radio', name: 'variable', value: clave });
    entrada.checked = clave === E.variable;
    entrada.addEventListener('change', () => { E.variable = clave; pintarTodo(); });
    variables.append(el('label', {}, [entrada, v.titulo]));
  }
  for (const clave of D.mapa.ir_a) {
    if (!D.territorios[clave]) continue;
    const boton = el('button', { texto: D.territorios[clave].nombre });
    boton.addEventListener('click', () => irATerritorio(clave));
    $('ir-a').append(boton);
  }
  $('ver-centros').addEventListener('change', (e) => { E.centros = e.target.checked; pintarMapa(); });
  $('ver-mercados').addEventListener('change', (e) => { E.mercados = e.target.checked; pintarMapa(); });
  $('ver-cambia').addEventListener('change', (e) => {
    E.cambia = e.target.checked; pintarComparar(); pintarMapa();
    if (E.cambia && carteraActual().ganan) encuadrar(carteraActual().ganan.caja);
  });
  $('desglose-separar').addEventListener('click', () => {
    if (!E.desglose) return;
    animarSeparacion(E.desglose.separacion > 0 ? 0 : E.desglose.objetivo, 900);
  });
  $('desglose-cerrar').addEventListener('click', cerrarDesglose);
  for (const boton of document.querySelectorAll('#pasos button')) {
    boton.addEventListener('click', () => irAPaso(boton.dataset.paso));
  }
  $('plegar').addEventListener('click', () => {
    $('panel').classList.toggle('plegado');
    $('plegar').textContent = $('panel').classList.contains('plegado') ? '›' : '‹';
  });
  montarBuscador();
  montarComparar();
  montarModales();
  montarDemo();
  $('atribuciones').textContent = [...D.textos.fuentes.atribuciones,
    `Versión de datos ${D.textos.fuentes.fecha_version} (${D.textos.fuentes.version}). Resultados precalculados.`].join(' · ');
}

function irATerritorio(clave) {
  E.territorio = clave;
  E.seccion = null; $('zona-senalada').hidden = true;
  pintarTerritorio(); pintarLeyenda(); pintarMapa();
  encuadrar(D.territorios[clave].caja);
}

function pintarTodo() {
  for (const entrada of document.querySelectorAll('input[name="variable"]')) entrada.checked = entrada.value === E.variable;
  pintarTerritorio(); pintarLeyenda();
  $('nota').textContent = variableActual().nota;
  pintarComparar(); pintarFicha(); pintarMapa();
}

function pintarTerritorio() {
  const t = D.territorios[E.territorio], caja = $('territorio');
  caja.replaceChildren(el('h3', { texto: t.nombre }), el('p', { clase: 'nota', texto: `${t.poblacion} habitantes (INE 2025)` }));
  for (const modo of ['transporte', 'transporte_16_20', 'pie']) {
    const m = t.modos[modo];
    caja.append(el('p', { clase: 'modo', texto: m.etiqueta }),
      el('div', { clase: 'cifra-fila' }, [el('span', { texto: 'Con acceso' }), el('b', { texto: m.con_acceso })]),
      el('div', { clase: 'cifra-fila' }, [el('span', { texto: 'Sin opción verificada' }),
        el('b', { texto: `${m.sin_opcion} (${m.sin_opcion_pct})` })]),
      el('div', { clase: 'cifra-fila' }, [el('span', { texto: 'No evaluable' }), el('b', { texto: m.no_evaluable })]));
  }
  if (t.tipo !== 'comunidad') {
    const boton = el('button', { clase: 'principal boton-3d', texto: 'Desglosar en 3D' });
    boton.addEventListener('click', () => abrirDesglose(E.territorio));
    caja.append(boton);
  }
}

function filaLeyenda(fila) {
  const nodos = [el('span', { clase: 'muestra', style: `background:${fila.color}` }),
    el('span', { clase: 'leyenda-etiqueta', texto: fila.etiqueta })];
  if (fila.pct !== null && fila.pct !== undefined) {
    nodos.push(el('span', { clase: 'leyenda-barra', style: `width:${Math.max(1, Math.round(1.1 * fila.pct))}px;background:${fila.color}` }),
      el('span', { clase: 'leyenda-pct', texto: fila.texto }));
  } else if (fila.texto) nodos.push(el('span', { clase: 'leyenda-pct', texto: fila.texto }));
  return el('div', { clase: 'leyenda-fila' }, nodos);
}

function pintarLeyenda() {
  const v = variableActual(), caja = $('leyenda');
  const datos = v.escala === 'municipios' ? D.mapa.leyendas.municipios[E.variable]
    : (D.mapa.leyendas[E.territorio] || {})[E.variable];
  const titulo = v.escala === 'municipios' ? '% sin opción verificada (municipios)'
    : E.variable === 'quintil_renta' ? 'Quintil de renta y % de la población' : 'Minutos al centro y % de la población evaluable';
  caja.replaceChildren(el('h3', { texto: titulo }));
  if (!datos) return;
  datos.filas.forEach((fila, i) => {
    caja.append(filaLeyenda(fila));
    if (v.umbral_tras === i) caja.append(el('div', { clase: 'umbral', texto: `umbral: ${v.umbral} min` }));
  });
  for (const fila of datos.extra) caja.append(filaLeyenda(fila));
}

/* ---------------------------------------------------------------- buscador */

function montarBuscador() {
  const entrada = $('buscar'), lista = $('sugerencias');
  const normalizar = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  let elegido = -1, coincidencias = [];
  const pintar = () => {
    lista.replaceChildren(...coincidencias.map((t, i) => {
      const li = el('li', { role: 'option', 'aria-selected': String(i === elegido), texto: t.buscar });
      li.addEventListener('mousedown', (e) => { e.preventDefault(); escoger(t); });
      return li;
    }));
    lista.hidden = coincidencias.length === 0;
  };
  const escoger = (t) => {
    entrada.value = t.buscar; lista.hidden = true;
    if (E.desglose) { E.desglose = null; document.body.classList.remove('en-desglose'); }
    irAPaso('diagnosticar'); irATerritorio(t.clave);
  };
  entrada.addEventListener('input', () => {
    const q = normalizar(entrada.value.trim());
    coincidencias = q ? D.mapa.territorios.filter((t) => normalizar(t.buscar).includes(q)).slice(0, 12) : [];
    elegido = coincidencias.length ? 0 : -1; pintar();
  });
  entrada.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { elegido = Math.min(elegido + 1, coincidencias.length - 1); pintar(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { elegido = Math.max(elegido - 1, 0); pintar(); e.preventDefault(); }
    else if (e.key === 'Enter' && coincidencias[elegido]) escoger(coincidencias[elegido]);
    else if (e.key === 'Escape') { lista.hidden = true; }
  });
  entrada.addEventListener('blur', () => { lista.hidden = true; });
}

/* ---------------------------------------------------------------- comparar */

function componenteDe(clave) { return clave.split('|')[0]; }

function montarComparar() {
  const selComp = $('componente'), selObj = $('objetivo');
  for (const c of D.carteras.componentes) selComp.append(el('option', { value: c.clave, texto: c.nombre }));
  selComp.addEventListener('change', () => {
    const c = D.carteras.componentes.find((x) => x.clave === selComp.value);
    const objetivo = c.objetivos[0][0];
    E.cartera = (c.opciones[objetivo].find((o) => /\|3(_12)?$/.test(o[0])) || c.opciones[objetivo][0])[0];
    irAPaso(E.paso);
  });
  selObj.addEventListener('change', () => {
    const c = D.carteras.componentes.find((x) => x.clave === selComp.value);
    const actual = carteraActual().opcion;
    const opciones = c.opciones[selObj.value];
    E.cartera = (opciones.find((o) => o[1] === actual) || opciones[0])[0];
    pintarComparar(); pintarFicha(); pintarMapa();
  });
}

function pintarComparar() {
  const f = carteraActual();
  if (!f) return;
  const comp = D.carteras.componentes.find((x) => x.clave === f.componente);
  $('componente').value = f.componente;
  $('objetivo').replaceChildren(...comp.objetivos.map(([valor, texto]) => el('option', { value: valor, texto })));
  $('objetivo').value = f.objetivo;
  $('opciones-cartera').replaceChildren(...comp.opciones[f.objetivo].map(([clave, texto]) => {
    const entrada = el('input', { type: 'radio', name: 'opcion', value: clave });
    entrada.checked = clave === E.cartera;
    entrada.addEventListener('change', () => { E.cartera = clave; pintarComparar(); pintarFicha(); pintarMapa(); });
    return el('label', {}, [entrada, texto]);
  }));
  $('condiciones').textContent = `${f.condiciones} · ${f.objetivo_texto}`;
  $('barras').replaceChildren(el('p', { texto: f.componente === 'b1'
    ? 'Personas con acceso a un mercado climatizado en la peor hora' : 'Personas que pasan de «sin opción verificada» a «con acceso»' }),
  ...f.barras.map((b) => el('div', { clase: 'barra-fila' }, [el('span', { texto: b.etiqueta }),
    el('span', { clase: 'barra', style: `width:${Math.max(1, Math.round(100 * b.fraccion))}%;background:${b.color}` }),
    el('b', { texto: b.texto })])));
  $('zonas-texto').textContent = f.zonas.length
    ? `Zonas elegidas (celdas de búsqueda de 250 m): ${f.municipios_zonas}. Son zonas para estudiar, no solares ni centros aprobados.` : '';
  const hayCambia = Boolean(f.ganan);
  $('casilla-cambia').hidden = !hayCambia;
  $('ver-cambia').checked = E.cambia && hayCambia;
  $('cambia-texto').textContent = hayCambia && E.cambia
    ? `Con esta cartera, ${f.ganan.texto} personas de la población objetivo pasan a tener un centro dentro del umbral. Pasa el ratón por una sección para ver cuántas ganan y cuántas siguen sin opción.` : '';
  $('leyenda-cambia').replaceChildren(...(modoCambia()
    ? D.mapa.leyenda_cambia.map((x) => filaLeyenda({ ...x, pct: null, texto: '' })) : []));
  $('titulo-escenarios').hidden = !f.escenarios;
  $('escenarios').replaceChildren(f.escenarios ? tabla(f.escenarios) : '');
  $('estado-solver').textContent = `Estado del solver: ${f.estado}.`;
  $('b-c').replaceChildren(el('h3', { texto: 'Refugios climáticos (B) y carencias coincidentes (C)' }),
    ...D.textos.b_c.b.map((t) => el('p', { clase: 'nota', texto: t })),
    ...D.textos.b_c.c.map((t) => el('p', { clase: 'nota', texto: t })));
}

function tabla(datos) {
  if (!datos || !datos.columnas.length) return '';
  return el('table', {}, [el('thead', {}, el('tr', {}, datos.columnas.map((c) => el('th', { texto: c })))),
    el('tbody', {}, datos.filas.map((fila) => el('tr', {}, fila.map((v) => el('td', { texto: v })))))]);
}

/* ---------------------------------------------------------------- ficha */

function pintarFicha() {
  const f = carteraActual();
  if (!f) return;
  $('ficha-titulo').textContent = f.titulo;
  $('ficha-resumen').replaceChildren(el('table', { clase: 'resumen' },
    el('tbody', {}, f.resumen.map(([c, v]) => el('tr', {}, [el('th', { texto: c }), el('td', { texto: v })])))));
  $('ficha-limites').replaceChildren(el('b', { texto: 'Límites que acompañan' }), el('p', { texto: f.limites }));
  const nombres = { ficha: 'Ficha legible (HTML)', csv: 'Zonas o bloques (CSV)', geojson: 'Zonas (GeoJSON)',
    json: 'Escenario reproducible (JSON)' };
  const enlaces = Object.entries(f.descargas).map(([tipo, ruta]) => el('a', {
    href: ruta, download: ruta.split('/').pop(), clase: tipo === 'ficha' ? 'boton principal' : 'boton', texto: nombres[tipo] || tipo,
  }));
  const imprimir = el('button', { texto: 'Imprimir o guardar en PDF' });
  imprimir.addEventListener('click', () => window.print());
  $('descargas').replaceChildren(...enlaces, imprimir);
  $('ficha-tabla-titulo').textContent = f.componente === 'b1' ? 'Horas que amplía la cartera' : 'Zonas de búsqueda elegidas';
  $('ficha-tabla').replaceChildren(tabla(f.tabla));
  $('ficha-alternativas').replaceChildren(...(f.alternativas.columnas.length
    ? [el('h3', { texto: 'Alternativas: ¿elección firme o empate?' }), el('p', { clase: 'nota', texto: f.texto_alternativas }), tabla(f.alternativas)]
    : []), el('p', { clase: 'nota', texto: D.textos.inicio.mide }),
  el('p', { clase: 'nota', texto: D.textos.fuentes.atribuciones.join(' · ') }));
}

/* ---------------------------------------------------------------- pasos, modales y demo */

function irAPaso(paso) {
  E.paso = paso;
  for (const boton of document.querySelectorAll('#pasos button')) boton.setAttribute('aria-selected', String(boton.dataset.paso === paso));
  for (const nombre of ['diagnosticar', 'comparar', 'ficha']) $(`vista-${nombre}`).hidden = nombre !== paso;
  // Al comparar, el mapa enseña los minutos del modo de la cartera (a pie o en transporte de 9 a 13 h).
  if (paso !== 'diagnosticar') E.variable = componenteDe(E.cartera) === 'a_pie' ? 'min_pie' : 'min_tp_9_13';
  pintarTodo();
}

function montarModales() {
  const inicio = D.textos.inicio;
  $('inicio-titulo').textContent = inicio.titulo;
  $('inicio-cifras').replaceChildren(...inicio.cifras.map((c) => el('div', {}, [el('div', { clase: 'valor', texto: c.valor }),
    el('div', { texto: c.texto })])));
  $('inicio-mide').textContent = inicio.mide;
  $('inicio-explorar').addEventListener('click', () => { cerrar('inicio'); aplicarDemo(1); });
  $('inicio-caso').addEventListener('click', () => {
    cerrar('inicio'); aplicarDemo(D.textos.inicio.demo.findIndex((p) => p.paso === 'comparar'));
  });
  const fuentes = D.textos.fuentes;
  const enlace = (texto, url) => el('a', { href: url, target: '_blank', rel: 'noopener', texto });
  $('datos-contenido').replaceChildren(el('h2', { texto: 'Para quién' }),
    ...fuentes.para_quien.map((t) => el('p', { texto: t })),
    el('p', { clase: 'nota' }, ['Fuentes: ', ...fuentes.fuentes_para_quien.flatMap((f, i) => [i ? ' · ' : '', enlace(f.texto, f.url)])]),
    el('h2', { texto: 'Viabilidad y código' }), el('ul', {}, fuentes.viabilidad.map((t) => el('li', { texto: t }))),
    el('h2', { texto: 'Datos abiertos que usa' }),
    el('p', { texto: `Versión de datos: ${fuentes.version} (${fuentes.fecha_version}). La página solo enseña resultados ya calculados.` }),
    tabla({ columnas: ['Organismo', 'Conjunto', 'Qué aporta y qué se le hace', 'Licencia', 'Descarga'],
      filas: fuentes.conjuntos.map((c) => [c.organismo, c.nombre, c.aporta, c.licencia, c.fecha || '—']) }),
    el('h3', { texto: 'Atribuciones' }), el('ul', {}, fuentes.atribuciones.map((a) => el('li', { texto: a }))),
    el('p', { texto: fuentes.odbl }), el('p', { texto: fuentes.codigo }));
  const esquema = D.textos.esquema_png ? el('img', { src: D.textos.esquema_png, alt: 'Cuatro capas de datos reales: población, red, recursos y resultado', style: 'max-width:100%' }) : '';
  $('ayuda-contenido').replaceChildren(el('h2', { texto: 'Cómo se calcula' }), el('p', { texto: inicio.mide }), esquema,
    ...Object.values(D.mapa.variables).map((v) => el('p', {}, [el('b', { texto: `${v.titulo}. ` }), v.nota])));
  $('abrir-datos').addEventListener('click', () => { $('datos').hidden = false; });
  $('abrir-ayuda').addEventListener('click', () => { $('ayuda').hidden = false; });
  for (const boton of document.querySelectorAll('[data-cerrar]')) boton.addEventListener('click', () => cerrar(boton.dataset.cerrar));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { for (const id of ['datos', 'ayuda']) cerrar(id); cerrarDesglose(); }
  });
}

function cerrar(id) { $(id).hidden = true; }

function montarDemo() {
  $('demo-siguiente').addEventListener('click', () => aplicarDemo(Math.min(E.demo + 1, D.textos.inicio.demo.length - 1)));
  $('demo-atras').addEventListener('click', () => aplicarDemo(Math.max(E.demo - 1, 0)));
  $('demo-reiniciar').addEventListener('click', () => aplicarDemo(0));
}

function aplicarDemo(i) {
  const pasos = D.textos.inicio.demo, p = pasos[i];
  E.demo = i;
  $('demo-titulo').textContent = `${i + 1}/${pasos.length} · ${p.titulo}`;
  if (E.desglose && p.paso !== 'desglose') {
    E.desglose = null; document.body.classList.remove('en-desglose');
    D.deck.setProps({ controller: { doubleClickZoom: true, dragRotate: false, touchRotate: false } });
  }
  if (p.paso === 'inicio') { $('inicio').hidden = false; return; }
  $('inicio').hidden = true;
  if (p.paso === 'desglose') {
    irAPaso('diagnosticar');
    E.territorio = p.territorio; pintarTerritorio(); pintarLeyenda();
    abrirDesglose(p.territorio);
    return;
  }
  if (p.cartera) E.cartera = p.cartera;
  if (p.variable) E.variable = p.variable;
  E.cambia = Boolean(p.que_cambia);
  E.seccion = null;
  irAPaso(p.paso);
  // Al comparar, el mapa se acerca a las zonas de la cartera y a quien gana opción con ellas.
  if (p.paso === 'comparar' && carteraActual().ganan) encuadrar(carteraActual().ganan.caja);
  else if (p.territorio) irATerritorio(p.territorio);
}

window.addEventListener('DOMContentLoaded', arrancar);
