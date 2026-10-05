/* Quíron Terminal — frontend sem build (JS puro).
   Painéis assinam tópicos pelo WebSocket; o servidor empurra atualizações. Números vêm calculados do Python. */
"use strict";

// ------------------------------------------------------------------ utilidades
const $ = (s, el = document) => el.querySelector(s);
const nf = (c = 2) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: c, maximumFractionDigits: c });
const fmt = (v, c = 2) => (v === null || v === undefined || isNaN(v) ? "—" : nf(c).format(v));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const linkSeguro = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
const BRT = { timeZone: "America/Sao_Paulo" };
const hora = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { ...BRT, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
const dia = (iso) => (iso ? new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("pt-BR", { ...BRT, day: "2-digit", month: "2-digit", year: "2-digit" }) : "—");
const COR = { s1: "#3987e5", s2: "#d95926", s3: "#199e70", texto3: "#8d8c84", borda: "#2e2e2b" };

function variacao(v, casas = 2) {
  if (v === null || v === undefined || isNaN(v)) return '<span class="neutro">—</span>';
  if (Math.abs(v) < 0.005) return `<span class="neutro">■ ${fmt(0, casas)}%</span>`;
  return v > 0 ? `<span class="alta">▲ +${fmt(v, casas)}%</span>` : `<span class="queda">▼ ${fmt(v, casas)}%</span>`;
}
function preco(c) {
  if (c.moeda === "BRL" && !["IBOV", "^BVSP", "SMLL", "IFIX"].includes(c.ativo)) return "R$ " + fmt(c.preco);
  if (["IBOV", "^BVSP"].includes(c.ativo)) return fmt(c.preco, 0);
  if (c.moeda === "USD" && !c.ativo.startsWith("^") && !c.ativo.includes("=X") && !c.ativo.includes(".")) return "US$ " + fmt(c.preco);
  return fmt(c.preco, c.preco < 10 ? 4 : 2);
}
function aviso(texto, ms = 4000) {
  const el = $("#aviso");
  el.textContent = texto;
  el.style.display = "block";
  clearTimeout(aviso.t);
  aviso.t = setTimeout(() => (el.style.display = "none"), ms);
}
function fonte(nome, iso, extra) {
  return `📊 ${esc(nome)} — ${hora(iso)}${extra ? " · " + esc(extra) : ""}`;
}

// ------------------------------------------------------------------ tipos de painel
// cada tipo: titulo, topico, params(p), render(corpo, dados, painel) e tamanho padrão
const TIPOS = {
  watchlist: { titulo: "Watchlist", topico: "watchlist", w: 4, h: 8, render: renderCotacoes },
  ativo: { titulo: (p) => p.ativo, topico: "ativo", params: (p) => ({ ticker: p.ativo }), w: 5, h: 10, render: renderAtivo },
  grafico: { titulo: (p) => `${p.ativo} GP`, topico: "historico", params: (p) => ({ ativo: p.ativo, periodo: p.periodo || "6mo", ...(p.comparar ? { comparar: p.comparar } : {}) }), w: 7, h: 10, render: renderGrafico },
  juros: { titulo: "Juros e Tesouro", topico: "juros", w: 4, h: 9, render: renderJuros },
  curva: { titulo: "Curva de juros — CURV", topico: "curva", w: 6, h: 10, render: renderCurva },
  macro: { titulo: "Macro", topico: "macro", w: 5, h: 9, render: renderMacro },
  noticias: { titulo: (p) => (p.termo ? `Notícias: ${p.termo}` : "Principais notícias — TOP"), topico: (p) => (p.termo ? "noticias" : "top"), params: (p) => (p.termo ? { termo: p.termo, horas: 48 } : { horas: 12 }), w: 5, h: 10, render: renderNoticias },
  redes: { titulo: (p) => `Redes: ${p.termo}`, topico: "redes", params: (p) => ({ termo: p.termo }), w: 5, h: 10, render: renderRedes },
  agenda: { titulo: "Agenda econômica — ECO", topico: "agenda", params: () => ({ dias: 10 }), w: 4, h: 8, render: renderAgenda },
  mundo: { titulo: "Índices mundiais — WEI", topico: "grupo", params: () => ({ nome: "wei" }), w: 4, h: 8, render: renderCotacoes },
  moedas: { titulo: "Moedas — FX", topico: "grupo", params: () => ({ nome: "fx" }), w: 4, h: 7, render: renderCotacoes },
  commodities: { titulo: "Commodities — CMDTY", topico: "grupo", params: () => ({ nome: "cmdty" }), w: 4, h: 8, render: renderCotacoes },
  calc: { titulo: "Calculadoras — CALC", topico: null, w: 4, h: 9, render: renderCalc },
  rpt: { titulo: "Relatórios — RPT", topico: null, w: 5, h: 10, render: renderRpt },
  status: { titulo: "Status", topico: "status", w: 3, h: 7, render: renderStatus },
  ajuda: { titulo: "Ajuda — HELP", topico: null, w: 4, h: 10, render: renderAjuda },
};

const PRESETS = {
  "Manhã": [
    { tipo: "watchlist", x: 1, y: 1, w: 3, h: 9 }, { tipo: "juros", x: 4, y: 1, w: 3, h: 9 }, { tipo: "macro", x: 7, y: 1, w: 3, h: 9 },
    { tipo: "agenda", x: 10, y: 1, w: 3, h: 9 }, { tipo: "noticias", x: 1, y: 10, w: 6, h: 10 }, { tipo: "curva", x: 7, y: 10, w: 4, h: 10 },
    { tipo: "status", x: 11, y: 10, w: 2, h: 10 },
  ],
  "Análise": [
    { tipo: "ativo", p: { ativo: "IBOV" }, x: 1, y: 1, w: 4, h: 11 }, { tipo: "grafico", p: { ativo: "IBOV" }, x: 5, y: 1, w: 8, h: 11 },
    { tipo: "mundo", x: 1, y: 12, w: 4, h: 9 }, { tipo: "moedas", x: 5, y: 12, w: 4, h: 9 }, { tipo: "commodities", x: 9, y: 12, w: 4, h: 9 },
  ],
  "Estudo": [
    { tipo: "calc", x: 1, y: 1, w: 4, h: 11 }, { tipo: "curva", x: 5, y: 1, w: 8, h: 11 }, { tipo: "noticias", x: 1, y: 12, w: 8, h: 9 },
    { tipo: "ajuda", x: 9, y: 12, w: 4, h: 9 },
  ],
};

// ------------------------------------------------------------------ estado e layouts
let paineis = []; // {id, tipo, p, x, y, w, h}
let contador = 0;
let layoutsSalvos = {};
const graficos = new Map(); // id → objetos de gráfico para limpar

function salvarLocal() {
  try { localStorage.setItem("quiron-layout-atual", JSON.stringify(paineis.map(({ id, _timer, ...r }) => r))); } catch (e) { /* sem storage */ }
}
function carregarLocal() {
  try { return JSON.parse(localStorage.getItem("quiron-layout-atual") || "null"); } catch (e) { return null; }
}

function aplicarLayout(lista) {
  for (const g of graficos.values()) g.remove?.();
  graficos.clear();
  $("#grade").innerHTML = "";
  paineis = [];
  for (const item of lista) adicionarPainel(item.tipo, item.p || {}, item, false);
  assinar();
  salvarLocal();
}

async function carregarLayouts() {
  try { layoutsSalvos = await (await fetch("/api/layouts")).json(); } catch (e) { layoutsSalvos = {}; }
  const sel = $("#layout");
  sel.innerHTML = "";
  const opt = (v, t) => Object.assign(document.createElement("option"), { value: v, textContent: t });
  sel.append(opt("", "Layout…"));
  for (const n of Object.keys(PRESETS)) sel.append(opt("p:" + n, n));
  for (const n of Object.keys(layoutsSalvos)) sel.append(opt("s:" + n, "★ " + n));
}

function proximaPosicao(w, h) {
  // primeira linha livre abaixo dos painéis existentes, à esquerda
  const fundo = paineis.reduce((m, p) => Math.max(m, p.y + p.h), 1);
  return { x: 1, y: fundo, w, h };
}

// ------------------------------------------------------------------ painéis
function adicionarPainel(tipo, p = {}, pos = null, reassinar = true) {
  const def = TIPOS[tipo];
  if (!def) return;
  const id = "p" + ++contador;
  const geo = pos && pos.x ? { x: pos.x, y: pos.y, w: pos.w, h: pos.h } : proximaPosicao(def.w, def.h);
  const painel = { id, tipo, p, ...geo };
  paineis.push(painel);
  const el = document.createElement("section");
  el.className = "painel";
  el.id = id;
  el.innerHTML = `
    <div class="painel-cab"><span class="painel-titulo"></span><span class="painel-sub"></span>
      <button data-acao="atualizar" title="Atualizar agora" aria-label="Atualizar">↻</button>
      <button data-acao="fechar" title="Fechar" aria-label="Fechar">✕</button></div>
    <div class="painel-corpo"><span class="carregando">carregando…</span></div>
    <div class="painel-rodape"></div><div class="alca" title="Arraste para redimensionar"></div>`;
  $("#grade").append(el);
  posicionar(painel);
  titular(painel);
  el.querySelector('[data-acao="fechar"]').onclick = () => fecharPainel(id);
  el.querySelector('[data-acao="atualizar"]').onclick = () => enviar({ tipo: "atualizar", id });
  arrastavel(painel, el);
  if (!def.topico) def.render(el.querySelector(".painel-corpo"), null, painel);
  if (reassinar) { assinar(); salvarLocal(); el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  return painel;
}
function titular(painel) {
  const def = TIPOS[painel.tipo];
  $(".painel-titulo", document.getElementById(painel.id)).textContent = typeof def.titulo === "function" ? def.titulo(painel.p) : def.titulo;
}
function posicionar(p) {
  const el = document.getElementById(p.id);
  el.style.gridColumn = `${p.x} / span ${p.w}`;
  el.style.gridRow = `${p.y} / span ${p.h}`;
}
function fecharPainel(id) {
  graficos.get(id)?.remove?.();
  graficos.delete(id);
  clearTimeout(paineis.find((p) => p.id === id)?._timer);
  document.getElementById(id)?.remove();
  paineis = paineis.filter((p) => p.id !== id);
  assinar();
  salvarLocal();
}

function arrastavel(painel, el) {
  const grade = $("#grade");
  const medida = () => {
    const r = grade.getBoundingClientRect();
    return { col: (r.width - 12) / 12, lin: 34 + 6 };
  };
  const iniciar = (ev, modo) => {
    if (ev.button !== 0 || ev.target.closest("button")) return;
    ev.preventDefault();
    const m = medida();
    const ini = { x: ev.clientX, y: ev.clientY, px: painel.x, py: painel.y, pw: painel.w, ph: painel.h };
    el.classList.add("arrastando");
    const mover = (e) => {
      const dx = Math.round((e.clientX - ini.x) / m.col);
      const dy = Math.round((e.clientY - ini.y) / m.lin);
      if (modo === "mover") {
        painel.x = Math.min(Math.max(1, ini.px + dx), 13 - painel.w);
        painel.y = Math.max(1, ini.py + dy);
      } else {
        painel.w = Math.min(Math.max(2, ini.pw + dx), 13 - painel.x);
        painel.h = Math.max(4, ini.ph + dy);
      }
      posicionar(painel);
    };
    const soltar = () => {
      el.classList.remove("arrastando");
      removeEventListener("pointermove", mover);
      removeEventListener("pointerup", soltar);
      graficos.get(painel.id)?.ajustar?.();
      salvarLocal();
    };
    addEventListener("pointermove", mover);
    addEventListener("pointerup", soltar);
  };
  $(".painel-cab", el).addEventListener("pointerdown", (e) => iniciar(e, "mover"));
  $(".alca", el).addEventListener("pointerdown", (e) => iniciar(e, "redimensionar"));
}

// ------------------------------------------------------------------ WebSocket
let socket = null;
let tentativas = 0;
function conectar() {
  socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  socket.onopen = () => { tentativas = 0; $("#conexao").className = "conexao ok"; $("#conexao").title = "Conectado"; assinar(); };
  socket.onclose = (e) => {
    $("#conexao").className = "conexao caiu";
    $("#conexao").title = "Sem conexão — tentando de novo";
    if (e.code === 4401) { location.href = "/login"; return; }
    setTimeout(conectar, Math.min(30000, 1000 * 2 ** tentativas++));
  };
  socket.onmessage = (ev) => receber(JSON.parse(ev.data));
}
function enviar(msg) { if (socket && socket.readyState === 1) socket.send(JSON.stringify(msg)); }
function assinar() {
  const lista = paineis.filter((p) => TIPOS[p.tipo].topico).map((p) => {
    const def = TIPOS[p.tipo];
    return { id: p.id, topico: typeof def.topico === "function" ? def.topico(p.p) : def.topico, params: def.params ? def.params(p.p) : {} };
  });
  lista.push({ id: "fita", topico: "watchlist", params: {} });
  enviar({ tipo: "assinar", paineis: lista });
}
function receber(msg) {
  if (msg.id === "fita") return renderFita(msg.dados);
  const painel = paineis.find((p) => p.id === msg.id);
  const el = painel && document.getElementById(painel.id);
  if (!el) return;
  const corpo = $(".painel-corpo", el);
  if (msg.erro) { corpo.innerHTML = `<div class="erro">Erro: ${esc(msg.erro)}</div>`; return; }
  try {
    TIPOS[painel.tipo].render(corpo, msg.dados, painel);
  } catch (e) {
    corpo.innerHTML = `<div class="erro">Falha ao desenhar: ${esc(e.message)}</div>`;
    console.error(e);
  }
  $(".painel-sub", el).textContent = "atualizado " + new Date(msg.enviado_em).toLocaleTimeString("pt-BR", BRT);
}

// ------------------------------------------------------------------ renderizadores
function renderCotacoes(corpo, lista, painel) {
  const linhas = lista.map((c) => c.erro
    ? `<tr><td class="nome">${esc(c.nome || c.ativo)}</td><td class="n dica" colspan="2" title="${esc(c.erro)}">indisponível</td></tr>`
    : `<tr class="clicavel" data-ativo="${esc(c.ativo)}" title="${esc(fonte(c.fonte, c.horario, c.atraso))}"><td class="nome">${esc(c.nome)}</td><td class="n">${preco(c)}</td><td class="n">${variacao(c.variacao)}</td></tr>`);
  corpo.innerHTML = `<table class="t"><thead><tr><th>Ativo</th><th class="n">Último</th><th class="n">Dia</th></tr></thead><tbody>${linhas.join("")}</tbody></table>`;
  corpo.querySelectorAll("tr[data-ativo]").forEach((tr) => tr.addEventListener("click", () => abrirAtivo(tr.dataset.ativo)));
  const ok = lista.find((c) => !c.erro);
  rodape(painel, ok ? `${fonte(ok.fonte, ok.obtido_em)} · clique para abrir o ativo` : "");
}

function renderAtivo(corpo, d, painel) {
  const c = d.cotacao;
  let html = "";
  if (c.erro) html += `<div class="erro">${esc(c.erro)}</div>`;
  else html += `<div><span class="dica">${esc(c.nome)}</span></div><div class="grande">${preco(c)} <span style="font-size:15px">${variacao(c.variacao)}</span></div>
                <div class="dica">${fonte(c.fonte, c.horario, c.atraso)}</div>`;
  html += `<div class="grafico" style="height:150px;margin:6px 0" data-g></div>`;
  html += `<div class="painel-titulo" style="margin:6px 0 2px">Notícias relacionadas</div>`;
  const ns = d.noticias && d.noticias.itens;
  html += ns && ns.length ? ns.slice(0, 6).map(itemNoticia).join("") : '<div class="dica">Nenhuma notícia recente.</div>';
  corpo.innerHTML = html;
  if (!d.historico.erro) desenharLinhas(painel.id, $("[data-g]", corpo), d.historico, true);
  else $("[data-g]", corpo).innerHTML = `<div class="dica">Gráfico indisponível: ${esc(d.historico.erro)}</div>`;
  rodape(painel, `Digite ${esc(painel.p.ativo)} GP para o gráfico completo`);
}

function renderGrafico(corpo, d, painel) {
  const per = [["1mo", "1M"], ["3mo", "3M"], ["6mo", "6M"], ["1y", "1A"], ["5y", "5A"]];
  corpo.innerHTML = `<div class="periodos">${per.map(([v, t]) => `<button data-per="${v}" class="${(painel.p.periodo || "6mo") === v ? "ativo" : ""}">${t}</button>`).join("")}
      <button data-comp="${painel.p.comparar ? "" : "IBOV"}" class="${painel.p.comparar ? "ativo" : ""}" title="Comparar com o Ibovespa (base 100)">× IBOV</button>
      <button data-tabela title="Ver os números em tabela">tabela</button></div>
    <div class="legenda" data-leg></div><div class="grafico" style="flex:1;min-height:0;height:auto" data-g></div>`;
  corpo.classList.add("coluna");
  corpo.querySelectorAll("[data-per]").forEach((b) => (b.onclick = () => { painel.p.periodo = b.dataset.per; reabrir(painel); }));
  $("[data-comp]", corpo).onclick = (e) => { painel.p.comparar = e.target.dataset.comp || undefined; reabrir(painel); };
  $("[data-tabela]", corpo).onclick = () => tabelaSerie(corpo, d);
  desenharLinhas(painel.id, $("[data-g]", corpo), d, false, $("[data-leg]", corpo));
  rodape(painel, `${fonte(d.fonte, d.obtido_em)} · ${d.modo === "comparacao" ? "base 100 no início do período" : "fechamento diário + médias de 20 e 50 dias"}`);
}
function reabrir(painel) { titular(painel); assinar(); salvarLocal(); $(".painel-corpo", document.getElementById(painel.id)).innerHTML = '<span class="carregando">carregando…</span>'; }

function tabelaSerie(corpo, d) {
  corpo.classList.remove("coluna");
  const nomes = Object.keys(d.series);
  const linhas = d.datas.map((dt, i) => `<tr><td>${dia(dt)}</td>${nomes.map((n) => `<td class="n">${fmt(d.series[n][i])}</td>`).join("")}</tr>`).reverse();
  corpo.innerHTML = `<button class="periodos" data-volta style="margin-bottom:4px">← gráfico</button>
    <table class="t"><thead><tr><th>Data</th>${nomes.map((n) => `<th class="n">${esc(n)}</th>`).join("")}</tr></thead><tbody>${linhas.join("")}</tbody></table>`;
  $("[data-volta]", corpo).onclick = () => enviar({ tipo: "atualizar", id: corpo.closest(".painel").id });
}

function desenharLinhas(id, alvo, d, compacto, legenda) {
  graficos.get(id)?.remove?.();
  if (!window.LightweightCharts) { alvo.innerHTML = '<div class="dica">Biblioteca de gráficos não carregou.</div>'; return; }
  const chart = LightweightCharts.createChart(alvo, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: COR.texto3, fontFamily: getComputedStyle(document.body).getPropertyValue("--mono"), fontSize: 11 },
    grid: { vertLines: { visible: false }, horzLines: { color: "#262624" } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: false },
    crosshair: { mode: 0 },
    handleScroll: !compacto, handleScale: !compacto,
    localization: { locale: "pt-BR", priceFormatter: (v) => fmt(v) },
  });
  const cores = [COR.s1, COR.s2, COR.s3];
  const nomes = Object.keys(d.series).slice(0, compacto ? 1 : 3);
  const series = nomes.map((nome, i) => {
    const s = chart.addLineSeries({ color: cores[i], lineWidth: 2, priceLineVisible: i === 0, lastValueVisible: i === 0, crosshairMarkerRadius: 4 });
    s.setData(d.datas.map((dt, k) => ({ time: dt, value: d.series[nome][k] })).filter((p) => p.value !== null && p.value !== undefined));
    return { nome, s, cor: cores[i] };
  });
  chart.timeScale().fitContent();
  if (legenda) {
    const desenhar = (param) => {
      legenda.innerHTML = series.map(({ nome, s, cor }) => {
        let v = param && param.seriesData ? param.seriesData.get(s)?.value : undefined;
        if (v === undefined) { const arr = d.series[nome].filter((x) => x !== null); v = arr[arr.length - 1]; }
        return `<span><i style="background:${cor}"></i>${esc(nome)} <b class="n">${fmt(v)}</b></span>`;
      }).join("") + (param && param.time ? `<span class="dica">${dia(param.time)}</span>` : "");
    };
    desenhar(null);
    chart.subscribeCrosshairMove(desenhar);
  }
  graficos.set(id, { remove: () => chart.remove(), ajustar: () => chart.timeScale().fitContent() });
}

function renderJuros(corpo, d, painel) {
  const kpis = d.series.map((s) => s.erro ? `<div class="kpi"><div class="kpi-r">indisponível</div><div class="dica">${esc(s.erro)}</div></div>`
    : `<div class="kpi"><div class="kpi-r">${esc(s.nome)}</div><div class="kpi-v">${fmt(s.valor)}%</div><div class="kpi-d">ref. ${dia(s.data)}${s.desatualizado ? " ⚠️ desatualizado" : ""}</div></div>`).join("");
  let tes = "";
  if (d.tesouro.carregando) tes = '<div class="carregando" style="margin-top:6px">Tesouro Direto: baixando taxas (na primeira vez leva uns 20 s)…</div>';
  else if (d.tesouro.erro) tes = `<div class="erro">Tesouro: ${esc(d.tesouro.erro)}</div>`;
  else {
    const pref = { selic: "Selic + ", ipca_mais: "IPCA + ", prefixado: "" };
    tes = `<table class="t" style="margin-top:6px"><thead><tr><th>Tesouro Direto (${dia(d.tesouro.data_base)})</th><th class="n">Taxa a.a.</th></tr></thead><tbody>${d.tesouro.titulos.map((t) =>
      `<tr><td>${esc(t.nome)}</td><td class="n">${pref[t.tipo]}${fmt(t.taxa, t.tipo === "selic" ? 4 : 2)}%</td></tr>`).join("")}</tbody></table>`;
  }
  corpo.innerHTML = `<div class="kpis">${kpis}</div>${tes}`;
  const s = d.series.find((x) => !x.erro);
  rodape(painel, [s && fonte(s.fonte, s.obtido_em), d.tesouro.fonte && fonte(d.tesouro.fonte, d.tesouro.obtido_em)].filter(Boolean).join("  "));
}

function renderMacro(corpo, d, painel) {
  const kpi = (s) => {
    if (s.erro) return `<div class="kpi"><div class="kpi-r">indisponível</div><div class="dica" title="${esc(s.erro)}">${esc(s.erro.slice(0, 60))}</div></div>`;
    const v = s.unidade === "R$" ? "R$ " + fmt(s.valor, 4) : s.unidade.includes("%") ? fmt(s.valor) + "%" : fmt(s.valor);
    return `<div class="kpi"><div class="kpi-r">${esc(s.nome)}</div><div class="kpi-v">${v}</div><div class="kpi-d">ref. ${dia(s.data)}</div></div>`;
  };
  let focus = "";
  if (!d.focus.erro) {
    focus = `<table class="t" style="margin-top:6px"><thead><tr><th>Focus — mediana ${d.focus.itens[0]?.ano || ""}</th><th class="n">Atual</th><th class="n">Semana</th></tr></thead><tbody>${d.focus.itens.map((f) => {
      if (f.erro) return `<tr><td>${esc(f.indicador)}</td><td class="n dica" colspan="2">indisponível</td></tr>`;
      const dif = f.anterior === null ? null : f.mediana - f.anterior;
      const seta = dif === null ? "—" : Math.abs(dif) < 1e-9 ? '<span class="neutro">■ estável</span>' : dif > 0 ? `<span class="neutro">▲ +${fmt(dif)}</span>` : `<span class="neutro">▼ ${fmt(dif)}</span>`;
      const val = f.indicador === "Câmbio" ? "R$ " + fmt(f.mediana) : fmt(f.mediana) + "%";
      return `<tr><td>${esc(f.indicador)}</td><td class="n">${val}</td><td class="n">${seta}</td></tr>`;
    }).join("")}</tbody></table>`;
  }
  corpo.innerHTML = `<div class="kpis">${d.series.map(kpi).join("")}</div>${focus}`;
  const s = d.series.find((x) => !x.erro);
  rodape(painel, [s && fonte(s.fonte, s.obtido_em), d.focus.fonte && fonte(d.focus.fonte + " (rel. " + dia(d.focus.itens.find((i) => i.data)?.data) + ")", d.focus.obtido_em)].filter(Boolean).join("  "));
}

function renderCurva(corpo, d, painel) {
  const vs = d.vertices.filter((v) => v.pre !== null || v.real !== null);
  corpo.innerHTML = `<div class="legenda"><span><i style="background:${COR.s1}"></i>Pré</span><span><i style="background:${COR.s2}"></i>Real (IPCA+)</span><span><i style="background:${COR.s3}"></i>Inflação implícita</span>
      <button class="periodos" data-tabela style="margin-left:auto">tabela</button></div>
    ${d.observacao ? `<div class="dica">${esc(d.observacao)}</div>` : ""}
    <div class="grafico" style="flex:1;min-height:0;height:auto" data-g></div>`;
  corpo.classList.add("coluna");
  $("[data-tabela]", corpo).onclick = () => {
    corpo.classList.remove("coluna");
    corpo.innerHTML = `<table class="t"><thead><tr><th>Prazo</th><th class="n">Pré</th><th class="n">Real</th><th class="n">Implícita</th></tr></thead><tbody>${vs.map((v) =>
      `<tr><td>${fmt(v.anos, 1)} anos (${v.du} du)</td><td class="n">${fmt(v.pre)}%</td><td class="n">${fmt(v.real)}%</td><td class="n">${fmt(v.implicita)}%</td></tr>`).join("")}</tbody></table>`;
  };
  requestAnimationFrame(() => svgCurva($("[data-g]", corpo), vs)); // mede depois do layout pronto
  rodape(painel, `${fonte(d.fonte + " (curva de " + dia(d.data) + ")", d.obtido_em)}${d.desatualizado ? " ⚠️ desatualizado" : ""}`);
}

function svgCurva(alvo, vs) {
  const W = Math.max(alvo.clientWidth, 260), H = Math.max(alvo.clientHeight - 4, 140), m = { l: 38, r: 10, t: 8, b: 20 };
  const chaves = [["pre", COR.s1, "Pré"], ["real", COR.s2, "Real"], ["implicita", COR.s3, "Implícita"]];
  const todos = vs.flatMap((v) => chaves.map(([k]) => v[k]).filter((x) => x !== null));
  if (!todos.length) { alvo.innerHTML = '<div class="dica">Sem vértices.</div>'; return; }
  const ymin = Math.floor(Math.min(...todos) - 0.5), ymax = Math.ceil(Math.max(...todos) + 0.5), xmax = Math.max(...vs.map((v) => v.anos));
  const X = (a) => m.l + (a / xmax) * (W - m.l - m.r), Y = (v) => m.t + (1 - (v - ymin) / (ymax - ymin)) * (H - m.t - m.b);
  let s = `<svg width="${W}" height="${H}" style="display:block" role="img" aria-label="Curva de juros por prazo">`;
  for (let y = ymin; y <= ymax; y += Math.max(1, Math.round((ymax - ymin) / 5))) s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(y)}" y2="${Y(y)}" stroke="#262624"/><text x="${m.l - 4}" y="${Y(y) + 3}" text-anchor="end">${y}%</text>`;
  const passo = Math.max(xmax > 8 ? 2 : 1, Math.ceil(xmax / Math.max(1, Math.floor((W - m.l - m.r) / 55))));
  for (let a = 0; a <= xmax; a += passo) s += `<text x="${X(a)}" y="${H - 6}" text-anchor="${a === 0 ? "start" : "middle"}">${a} ${a === 1 ? "ano" : "anos"}</text>`;
  for (const [k, cor] of chaves) {
    const pts = vs.filter((v) => v[k] !== null).map((v) => `${X(v.anos).toFixed(1)},${Y(v[k]).toFixed(1)}`);
    if (pts.length) s += `<polyline fill="none" stroke="${cor}" stroke-width="2" points="${pts.join(" ")}"/>`;
  }
  s += `<line data-mira x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="#55544f" stroke-dasharray="3 3" visibility="hidden"/></svg><div class="dica-svg"></div>`;
  alvo.innerHTML = s;
  const svg = $("svg", alvo), dica = $(".dica-svg", alvo), mira = $("[data-mira]", alvo);
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect(), x = e.clientX - r.left;
    const v = vs.reduce((b, c) => (Math.abs(X(c.anos) - x) < Math.abs(X(b.anos) - x) ? c : b));
    mira.setAttribute("x1", X(v.anos)); mira.setAttribute("x2", X(v.anos)); mira.setAttribute("visibility", "visible");
    dica.style.display = "block";
    dica.innerHTML = `${fmt(v.anos, 1)} anos<br>${chaves.map(([k, cor, n]) => `<span style="color:${cor}">■</span> ${n}: ${fmt(v[k])}%`).join("<br>")}`;
    dica.style.left = Math.min(x + 12, W - 140) + "px";
    dica.style.top = "8px";
  });
  svg.addEventListener("pointerleave", () => { dica.style.display = "none"; mira.setAttribute("visibility", "hidden"); });
}

function itemNoticia(n) {
  const tags = [...n.ativos.map((a) => `<span class="tag">${esc(a)}</span>`), ...n.alertas.map((a) => `<span class="tag alerta">⚠ ${esc(a)}</span>`)].join("");
  const tom = n.tom === "positivo" ? '<span class="alta" title="tom das palavras">▲</span>' : n.tom === "negativo" ? '<span class="queda" title="tom das palavras">▼</span>' : "";
  return `<div class="noticia"><a href="${linkSeguro(n.link)}" target="_blank" rel="noopener noreferrer">${esc(n.titulo)}</a>
    <div class="meta">${tom} ${esc(n.fonte)} · ${hora(n.publicado_em)} ${n.outras_fontes.length ? "· também em " + esc(n.outras_fontes.join(", ")) : ""} ${tags}</div></div>`;
}
function renderNoticias(corpo, d, painel) {
  corpo.innerHTML = d.itens.length ? d.itens.map(itemNoticia).join("") : '<div class="dica">Nada encontrado no período.</div>';
  rodape(painel, `${d.total} notícias${d.tom ? ` · tom das manchetes: ${esc(d.tom.rotulo)} (${fmt(d.tom.nota)})` : ""} · RSS de portais e órgãos oficiais`);
}

function renderRedes(corpo, d, painel) {
  corpo.innerHTML = Object.entries(d.redes).map(([nome, r]) => {
    const tit = `<div class="painel-titulo" style="margin:4px 0">${esc(nome)}${r.tom ? ` — tom ${esc(r.tom.rotulo)}` : ""}</div>`;
    if (r.configurar) return tit + `<div class="dica">${esc(r.configurar)}</div>`;
    if (r.erro) return tit + `<div class="erro">${esc(r.erro)}</div>`;
    return tit + (r.posts.length ? r.posts.map((p) => `<div class="post"><b>${esc(p.autor)}</b> <span class="dica">${esc(p.detalhe)} · ${hora(p.publicado_em)} · engajamento ${p.engajamento}</span><br>${esc(p.texto)} <a href="${linkSeguro(p.link)}" target="_blank" rel="noopener noreferrer">↗</a></div>`).join("") : '<div class="dica">Sem posts recentes.</div>');
  }).join("");
  rodape(painel, "APIs oficiais: Bluesky, Reddit, YouTube · opinião de terceiros, não é fato");
}

function renderAgenda(corpo, d, painel) {
  corpo.innerHTML = d.eventos.length
    ? `<table class="t"><tbody>${d.eventos.map((e) => `<tr><td class="n" style="text-align:left">${hora(e.quando)}</td><td class="nome" title="${esc(e.titulo)}">${esc(e.titulo)}</td><td class="dica">${esc(e.fonte)}</td></tr>`).join("")}</tbody></table>`
    : '<div class="dica">Nenhum evento no período.</div>';
  if (d.erro) corpo.innerHTML += `<div class="erro">IBGE: ${esc(d.erro)}</div>`;
  rodape(painel, "IBGE (calendário oficial) + config/agenda_fixa.yaml (Copom, resultados)");
}

function renderStatus(corpo, d, painel) {
  const redes = Object.entries(d.redes).map(([n, ok]) => `${esc(n)} ${ok ? "✓" : "—"}`).join(" · ");
  corpo.innerHTML = `<div class="kpis"><div class="kpi"><div class="kpi-r">Memória do Terminal</div><div class="kpi-v">${fmt(d.memoria_mb, 0)} MB</div><div class="kpi-d">PC: ${fmt(d.memoria_sistema_pct, 0)}% em uso</div></div></div>
    <table class="t" style="margin-top:6px"><thead><tr><th>Fonte</th><th class="n">Última consulta</th></tr></thead><tbody>${d.fontes.map((f) => `<tr><td class="nome">${esc(f.fonte)}</td><td class="n">${hora(f.atualizado_em)}</td></tr>`).join("")}</tbody></table>
    <div class="dica" style="margin-top:4px">Redes: ${redes}</div>
    ${d.analises && d.analises.ultima !== undefined ? `<div class="dica">Análises: ${d.analises.na_fila} na fila, ${d.analises.rodando} rodando${d.analises.ultima ? " · última " + esc(d.analises.ultima) : ""} — RPT</div>` : ""}
    ${d.regras_pendentes.length ? `<div class="erro" style="margin-top:4px">⚠ ${d.regras_pendentes.length} bloco(s) de regras de mercado sem verificação</div>` : ""}`;
  rodape(painel, "no ar desde " + hora(d.no_ar_desde));
}

// Calculadoras: os campos vêm do servidor (/api/calc) — fonte única com o agente e o Telegram.
let CALCS = null;
async function carregarCalcs() {
  if (!CALCS) CALCS = await (await fetch("/api/calc")).json();
  return CALCS;
}
async function renderCalc(corpo, _d, painel) {
  try { await carregarCalcs(); } catch (e) { corpo.innerHTML = `<div class="erro">Sem conexão com o servidor</div>`; return; }
  const atual = CALCS[painel.p.calc] ? painel.p.calc : "juros_compostos";
  const def = CALCS[atual];
  corpo.innerHTML = `<div class="calc-abas">${Object.entries(CALCS).map(([k, c]) => `<button data-c="${k}" class="${k === atual ? "ativo" : ""}">${esc(c.nome)}</button>`).join("")}</div>
    <form class="calc-form">${def.campos.map(([k, rot, val, tipo, ops]) => tipo === "opção"
      ? `<label>${esc(rot)}<select name="${k}">${ops.map(([v, t]) => `<option value="${v}" ${v === val ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`
      : `<label>${esc(rot)}<input name="${k}" value="${esc(tipo === "texto" ? String(val) : String(val).replace(".", ","))}" ${tipo === "texto" ? "" : 'inputmode="decimal"'}></label>`).join("")}</form>
    <div data-res></div>`;
  corpo.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => { painel.p.calc = b.dataset.c; salvarLocal(); renderCalc(corpo, null, painel); }));
  const form = $("form", corpo), res = $("[data-res]", corpo);
  const calcular = async () => {
    const entrada = Object.fromEntries(new FormData(form));
    try {
      const r = await (await fetch(`/api/calc/${atual}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(entrada) })).json();
      if (r.erro) { res.innerHTML = `<div class="erro">${esc(r.erro)}</div>`; return; }
      res.innerHTML = `<table class="t">${r.linhas.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${esc(v)}</td></tr>`).join("")}</table>
        <div class="memoria">${r.memoria.map(esc).join("<br>")}</div>${r.avisos.map((a) => `<div class="erro">⚠ ${esc(a)}</div>`).join("")}`;
    } catch (e) { res.innerHTML = `<div class="erro">Sem conexão com o servidor</div>`; }
  };
  let t;
  form.addEventListener("input", () => { clearTimeout(t); t = setTimeout(calcular, 250); });
  form.addEventListener("submit", (e) => { e.preventDefault(); calcular(); });
  calcular();
  rodape(painel, "calculado em Python no servidor, resultado enquanto você digita");
}

// Relatórios do motor de análise (fila + arquivo pesquisável)
function renderRpt(corpo, _d, painel) {
  corpo.innerHTML = `<form class="calc-form rpt-busca"><input name="q" placeholder="Buscar nos relatórios (ex.: debênture, CDB)" value="${esc(painel.p.q || "")}"></form><div data-lista></div>`;
  const lista = $("[data-lista]", corpo), form = $("form", corpo);
  const carregar = async () => {
    clearTimeout(painel._timer); // um só ciclo de atualização por painel, mesmo se redesenhado
    try {
      const r = await (await fetch(`/api/relatorios?busca=${encodeURIComponent(painel.p.q || "")}`)).json();
      lista.innerHTML = r.itens.length ? `<table class="t">${r.itens.map((t) => `<tr class="${t.id === painel.p.destaque ? "destaque" : ""}" data-rpt="${t.id}"><td>#${t.id}</td><td>${esc(t.titulo)}<div class="memoria">${esc(t.quando)} · ${esc(t.situacao)}${t.erro ? " · " + esc(t.erro) : ""}</div></td>
        <td class="n">${t.pdf ? `<a href="/relatorios/${t.id}/relatorio.pdf" target="_blank" rel="noopener">PDF</a>` : ""} ${t.planilha ? `<a href="/relatorios/${t.id}/planilha.xlsx">XLSX</a>` : ""}</td></tr>`).join("")}</table>`
        : `<div class="memoria">Nenhum relatório ainda. Digite WEGE3 DCF, FUND &lt;nome&gt; ou peça ao Quíron no CHAT/Telegram (ex.: “compare CDB 110% do CDI com LCI 92% em 2 anos”).</div>`;
      if (r.itens.some((t) => t.situacao === "na fila" || t.situacao === "rodando")) painel._timer = setTimeout(carregar, 5000);
    } catch (e) { lista.innerHTML = `<div class="erro">Sem conexão com o servidor</div>`; }
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); painel.p.q = new FormData(form).get("q"); salvarLocal(); carregar(); });
  carregar();
  rodape(painel, "relatórios em dados/relatorios · PDF + planilha · busca no texto completo");
}

function renderAjuda(corpo) {
  const cmds = [
    ["PETR4", "Visão do ativo: cotação, gráfico de 3 meses e notícias"], ["PETR4 GP", "Gráfico com médias móveis e comparação com o Ibovespa"],
    ["TOP", "Principais notícias agora"], ["RPT", "Relatórios do motor de análise (PDF e planilha)"], ["NEWS <tema>", "Notícias de um tema ou ticker (ex.: NEWS COPOM)"], ["SOC <tema>", "O que as redes dizem"],
    ["ECO", "Agenda econômica"], ["CURV", "Curva de juros pré, real e inflação implícita"], ["MACRO", "Painel macro e Focus"],
    ["JUROS", "Selic, CDI e Tesouro"], ["WEI", "Índices mundiais"], ["FX", "Moedas"], ["CMDTY", "Commodities"], ["W", "Watchlist"],
    ["CALC", "Calculadoras"], ["STATUS", "Saúde do sistema"], ["CONFIG", "Configurações: chaves, Telegram, Google Agenda, offline"], ["ACERVO", "Enviar livros e materiais"], ["HELP", "Esta ajuda"],
    ["WEGE3 FA", "Demonstrações da CVM e múltiplos (uso interno)"], ["WEGE3 DCF", "Dispara o valuation completo; o PDF aparece em RPT"],
    ["FUND <nome>", "Busca fundos na CVM (12 meses, PL); análise ou comparação"], ["CMPF", "Compara de 2 a 6 fundos"],
    ["PORT", "Cola a carteira → enquadramento no perfil e diagnóstico completo"], ["PLAN [CLI-XXX]", "Fichas de planejamento e relatórios"],
    ["ACAD", "Domínio estimado por módulo na Academia"], ["TASK", "Tarefas e lembretes (os mesmos do Telegram)"],
    ["ALRT", "Alertas de preço, variação e notícia"], ["CHAT [pergunta]", "Conversa com o Quíron dentro do Terminal"],
    ["BIB <tema>", "Procura nos seus livros (funciona sem internet)"], ["CLI", "Clientes reais — só na versão offline, com a senha do cofre"],
  ];
  corpo.innerHTML = `<dl class="ajuda">${cmds.map(([c, d]) => `<dt>${esc(c)}</dt><dd>${esc(d)}</dd>`).join("")}</dl>
    <div class="dica">Atalhos: <b>/</b> ou <b>Ctrl+K</b> barra de comando · <b>Esc</b> sai da barra · <b>Alt+1/2/3/4</b> layouts Manhã/Análise/Estudo/Assessoria · arraste o cabeçalho para mover, o canto para redimensionar.<br>
    Celular: abra pelo endereço do Tailscale e use “Adicionar à tela inicial”.</div>`;
}

function renderFita(lista) {
  if (!Array.isArray(lista)) return;
  $("#fita").innerHTML = lista.filter((c) => !c.erro).map((c) => `<span><b>${esc(c.nome)}</b> ${preco(c)} ${variacao(c.variacao)}</span>`).join("");
}
function rodape(painel, html) { $(".painel-rodape", document.getElementById(painel.id)).innerHTML = html; }

// ------------------------------------------------------------------ Terminal v2 (Fase 12): análise, assessoria e chat
// Toda ação que grava ou dispara algo leva o cabeçalho X-Quiron (o servidor recusa pedidos vindos de outros sites).
async function acao(url, corpo, metodo = "POST") {
  const r = await fetch(url, { method: metodo, headers: { "Content-Type": "application/json", "X-Quiron": "terminal" }, body: corpo === undefined ? undefined : JSON.stringify(corpo) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || d.erro || `erro ${r.status}`);
  return d;
}
const mi = (v) => (v === null || v === undefined ? "—" : fmt(v / 1e6, 0));
const pct = (v, c = 1) => (v === null || v === undefined ? "—" : fmt(v * 100, c) + "%");
const vezes = (v) => (v === null || v === undefined ? "—" : fmt(v, 1) + "x");
const atualizarPainel = (painel) => enviar({ tipo: "atualizar", id: painel.id });

// Pede uma análise ao motor (mesma fila do Telegram) e abre/atualiza o RPT com a tarefa em destaque.
async function pedirAnalise(tipo, parametros, rotulo, modo = "entregar") {
  try {
    const r = await acao("/api/analisar", { tipo, parametros, modo });
    aviso(`Análise #${r.id} (${rotulo}) na fila${r.na_frente ? ` — ${r.na_frente} na frente` : ""}. Acompanhe em RPT.`, 6000);
    let rpt = paineis.find((p) => p.tipo === "rpt");
    if (rpt) { rpt.p.destaque = r.id; rpt.p.q = ""; renderRpt($(".painel-corpo", document.getElementById(rpt.id)), null, rpt); }
    else rpt = adicionarPainel("rpt", { destaque: r.id });
    document.getElementById(rpt.id)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return r;
  } catch (e) { aviso("Não consegui pedir a análise: " + e.message, 6000); }
}
function botoes(lista) {
  return `<div class="periodos acoes">${lista.map(([k, t, dica]) => `<button type="button" data-b="${k}" title="${esc(dica || "")}">${esc(t)}</button>`).join("")}</div>`;
}
function ligar(corpo, mapa) { corpo.querySelectorAll("[data-b]").forEach((b) => (b.onclick = () => mapa[b.dataset.b]?.(b))); }

// FA — demonstrações (CVM) e múltiplos
function renderFa(corpo, d, painel) {
  const t = painel.p.ticker;
  if (d.carregando) {
    corpo.innerHTML = `<div class="carregando">Baixando as demonstrações de ${esc(t)} da CVM (na primeira vez leva até 1 minuto)…</div>`;
    return;
  }
  const m = d.multiplos;
  const kpi = (r, v) => `<div class="kpi"><div class="kpi-r">${r}</div><div class="kpi-v">${v}</div></div>`;
  const linhas = [["Receita", "receita"], ["EBITDA", "ebitda"], ["EBIT", "ebit"], ["Lucro (controladores)", "lucro_controladores"],
    ["Geração de caixa (FCO)", "fco"], ["Capex", "capex"], ["Dívida líquida", "divida_liquida"], ["Patrimônio líquido", "pl"]];
  const per = d.periodos;
  corpo.innerHTML = `<div><b>${esc(d.empresa)}</b> <span class="dica">${esc(d.setor)} · ${esc(d.segmento || "")}</span></div>
    <div class="grande" style="font-size:20px">R$ ${fmt(d.preco)} <span class="dica">valor de mercado R$ ${fmt(m.valor_mercado / 1e9, 1)} bi</span></div>
    <div class="kpis kpis-p">${kpi("P/L", vezes(m.pl))}${kpi("EV/EBITDA", vezes(m.ev_ebitda))}${kpi("P/VP", vezes(m.p_vp))}${kpi("Dividend yield", pct(m.dy))}
      ${kpi("ROE", pct(m.roe))}${kpi("Margem EBITDA", pct(m.margem_ebitda))}${kpi("Margem líquida", pct(m.margem_liquida))}${kpi("Dív. líq./EBITDA", vezes(m.divida_liquida_ebitda))}</div>
    ${botoes([["dcf", "DCF completo", "valuation em PDF (fila de análises)"], ["setor", "× setor", "múltiplos contra os pares"], ["tri", "Último trimestre", "ITR contra o ano anterior"], ["gp", "Gráfico"]])}
    <table class="t"><thead><tr><th>R$ milhões</th>${per.map((p) => `<th class="n">${esc(p.rotulo.replace("12 meses até ", "LTM "))}</th>`).join("")}</tr></thead>
    <tbody>${linhas.map(([n, k]) => `<tr><td>${n}</td>${per.map((p) => `<td class="n">${mi(p[k])}</td>`).join("")}</tr>`).join("")}</tbody></table>
    ${d.avisos.map((a) => `<div class="erro">⚠ ${esc(a)}</div>`).join("")}`;
  ligar(corpo, {
    dcf: () => pedirAnalise("valuation_dcf", { empresa: t }, `${t} DCF`),
    setor: () => pedirAnalise("setor_multiplos", { empresa: t }, `${t} × setor`),
    tri: () => pedirAnalise("resultado_trimestral", { empresa: t }, `${t} trimestre`),
    gp: () => adicionarPainel("grafico", { ativo: t }),
  });
  rodape(painel, "📊 CVM (DFP/ITR) + cotação do dia · Uso interno — não constitui relatório de análise");
}

// FUND — busca de fundos na CVM
function renderFundos(corpo, d, painel) {
  if (!d.itens.length) { corpo.innerHTML = `<div class="dica">Nenhum fundo com “${esc(d.termo)}”. Tente parte do nome ou o CNPJ.</div>`; return; }
  corpo.innerHTML = `<table class="t"><thead><tr><th></th><th>Fundo</th><th class="n">PL R$ mi</th><th class="n">12 meses</th><th></th></tr></thead><tbody>${d.itens.map((f) => `
    <tr><td><input type="checkbox" data-cnpj="${esc(f.cnpj)}" aria-label="Selecionar para comparar"></td>
      <td class="nome" title="${esc(f.nome)} · ${esc(f.gestor)}">${f.master ? '<span class="tag alerta" title="fundo master: não recebe aplicação direta">master</span>' : ""}${esc(f.nome)}<div class="memoria">${esc(f.cnpj)} · ${esc(f.anbima || "sem classificação")}</div></td>
      <td class="n">${mi(f.pl)}</td><td class="n">${f.ret12 === null ? '<span class="dica" title="série mensal ainda não baixada">—</span>' : variacao(f.ret12)}</td>
      <td><button type="button" class="mini" data-analise="${esc(f.cnpj)}" title="Análise completa em PDF">análise</button></td></tr>`).join("")}</tbody></table>
    ${botoes([["cmpf", "Comparar selecionados (CMPF)", "marque de 2 a 6 fundos"]])}`;
  corpo.querySelectorAll("[data-analise]").forEach((b) => (b.onclick = () => pedirAnalise("fundo_analise", { cnpj: b.dataset.analise }, "fundo " + b.dataset.analise)));
  ligar(corpo, {
    cmpf: () => {
      const cnpjs = [...corpo.querySelectorAll("input[data-cnpj]:checked")].map((c) => c.dataset.cnpj);
      if (cnpjs.length < 2 || cnpjs.length > 6) return aviso("Marque de 2 a 6 fundos para comparar.");
      pedirAnalise("fundos_comparativo", { cnpjs }, `comparativo de ${cnpjs.length} fundos`);
    },
  });
  rodape(painel, `${fonte(d.fonte, d.obtido_em)} · 12 meses = últimos 12 meses fechados (cota da CVM)`);
}

// CMPF — comparar fundos por CNPJ ou nome
function renderCmpf(corpo, _d, painel) {
  corpo.innerHTML = `<form class="form-v2"><label>Fundos (um CNPJ ou nome por linha, de 2 a 6)<textarea name="lista" rows="5" placeholder="Ex.:\n07.455.507/0001-89\nSPX Nimitz">${esc((painel.p.cnpjs || []).join("\n"))}</textarea></label>
    <label>Histórico<select name="anos"><option value="1">1 ano</option><option value="3" selected>3 anos</option><option value="5">5 anos</option></select></label>
    <button type="submit">Comparar (PDF + planilha)</button></form><div class="dica">Rentabilidade × CDI, risco, posição entre os pares, taxas e conferência das cotas na CVM. Para achar o CNPJ: FUND &lt;nome&gt;.</div>`;
  $("form", corpo).onsubmit = (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const cnpjs = String(f.get("lista")).split("\n").map((s) => s.trim()).filter(Boolean);
    if (cnpjs.length < 2 || cnpjs.length > 6) return aviso("Informe de 2 a 6 fundos.");
    painel.p.cnpjs = cnpjs; salvarLocal();
    pedirAnalise("fundos_comparativo", { cnpjs, anos: +f.get("anos") }, `comparativo de ${cnpjs.length} fundos`);
  };
  rodape(painel, "📊 CVM Dados Abertos (informe diário) · resultado em RPT");
}

// PORT — carteira colada → composição, enquadramento no perfil e diagnóstico completo
function renderPort(corpo, _d, painel) {
  const perfis = ["conservador", "moderado", "arrojado"];
  corpo.innerHTML = `<form class="form-v2"><label>Carteira (uma posição por linha: nome e valor)<textarea name="texto" rows="5" placeholder="Ex.:\nTesouro IPCA+ 2035 R$ 120.000\nCDB Banco X 110% CDI 80 mil\nBOVA11 R$ 45.000\nPETR4 200 (sem R$ = quantidade)">${esc(painel.p.texto || "")}</textarea></label>
    <div class="linha-form"><label>Perfil<select name="perfil">${perfis.map((p) => `<option ${p === (painel.p.perfil || "moderado") ? "selected" : ""}>${p}</option>`).join("")}</select></label>
    <label>Cliente (opcional)<input name="cliente" placeholder="CLI-001" value="${esc(painel.p.cliente || "")}" maxlength="12"></label>
    <button type="submit">Ler carteira</button></div></form><div data-res></div>`;
  const res = $("[data-res]", corpo);
  $("form", corpo).onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    if (f.cliente && !/^CLI-\w+$/i.test(f.cliente.trim())) return aviso("Cliente só como código CLI-XXX (nunca o nome).");
    Object.assign(painel.p, f); salvarLocal();
    res.innerHTML = '<div class="carregando">lendo…</div>';
    try {
      const r = await acao("/api/carteira/ler", f);
      res.innerHTML = `<div class="dica">${esc(r.id)} · ${r.posicoes.length} posições · total R$ ${fmt(r.total)}</div>
        <table class="t"><thead><tr><th>Classe (perfil ${esc(r.perfil)})</th><th class="n">Atual</th><th class="n">Faixa</th><th class="n">Alvo</th><th>Situação</th></tr></thead><tbody>${r.enquadramento.map((l) =>
          `<tr><td>${esc(l.classe)}</td><td class="n">${fmt(l.atual, 1)}%</td><td class="n">${fmt(l.minimo, 0)}–${fmt(l.maximo, 0)}%</td><td class="n">${fmt(l.alvo, 0)}%</td><td>${l.situacao === "dentro" ? "✓ dentro" : "⚠ " + esc(l.situacao)}</td></tr>`).join("")}</tbody></table>
        <details><summary class="dica">Posições lidas</summary><table class="t">${r.posicoes.map((p) => `<tr><td class="nome">${esc(p.nome)}</td><td>${esc(p.classe)}</td><td class="n">R$ ${fmt(p.valor)}</td></tr>`).join("")}</table></details>
        ${r.avisos.map((a) => `<div class="erro">⚠ ${esc(a)}</div>`).join("")}
        ${botoes([["diag", "Diagnóstico completo", "risco, stress, otimização, rebalanceamento com IR e backtest (PDF)"]])}`;
      ligar(res, { diag: () => pedirAnalise("carteira_diagnostico", { carteira_id: r.id }, "diagnóstico da carteira " + r.id) });
    } catch (err) { res.innerHTML = `<div class="erro">${esc(err.message)}</div>`; }
  };
  rodape(painel, "leitura no servidor · cliente só como CLI-XXX · a carteira fica em dados/carteiras");
}

// PLAN — fichas de planejamento (CLI-XXX)
const TIPOS_PLAN = [["planejamento_completo", "Planejamento completo"], ["aposentadoria", "Aposentadoria"], ["sucessao", "Sucessão"],
  ["tributario", "Tributário"], ["protecao", "Proteção"], ["empresario", "PF × PJ"]];
function renderPlan(corpo, d, painel) {
  if (d.lista) {
    corpo.innerHTML = d.lista.length
      ? `<table class="t"><thead><tr><th>Cliente</th><th class="n">Idade</th><th>Ocupação</th><th class="n">Patrimônio</th><th class="n">Ficha</th></tr></thead><tbody>${d.lista.map((f) =>
        `<tr class="clicavel" data-cli="${esc(f.cliente)}"><td>${esc(f.cliente)}</td><td class="n">${f.idade ?? "—"}</td><td>${esc(f.ocupacao || "")}</td><td class="n">R$ ${fmt(f.patrimonio, 0)}</td><td class="n">${dia(f.atualizado_em)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="dica">Nenhuma ficha ainda. Monte a ficha conversando com o Quíron (CHAT ou Telegram: /cliente CLI-001 …) — só com o código, nunca o nome.</div>`;
    corpo.querySelectorAll("[data-cli]").forEach((tr) => (tr.onclick = () => { painel.p.cliente = tr.dataset.cli; reabrir(painel); }));
    rodape(painel, "fichas em dados/fichas · clique para abrir");
    return;
  }
  corpo.innerHTML = `<button type="button" class="mini" data-volta>← fichas</button>
    <pre class="texto-pre">${esc(d.resumo)}</pre>
    ${d.pendencias.length ? `<div class="erro">Pendências: ${d.pendencias.map(esc).join(" · ")}</div>` : ""}
    ${botoes(TIPOS_PLAN.map(([k, t]) => [k, t, "relatório em PDF (RASCUNHO para revisão)"]))}`;
  $("[data-volta]", corpo).onclick = () => { painel.p.cliente = ""; reabrir(painel); };
  ligar(corpo, Object.fromEntries(TIPOS_PLAN.map(([k, t]) => [k, () => pedirAnalise(k, { cliente: d.cliente }, `${t} ${d.cliente}`)])));
  rodape(painel, `${esc(d.cliente)} · textos para cliente saem como RASCUNHO`);
}

// ACAD — prontidão por módulo
function renderAcad(corpo, d, painel) {
  const barra = (f) => `<span class="barra-p" role="img" aria-label="${fmt(f * 100, 0)}%"><i style="width:${Math.max(0, Math.min(1, f)) * 100}%"></i></span>`;
  corpo.innerHTML = `<div class="kpis"><div class="kpi"><div class="kpi-r">Domínio estimado — ${esc(d.nome)}</div><div class="kpi-v">${fmt(d.prontidao * 100, 0)}%</div><div class="kpi-d">meta 70%</div></div></div>
    <table class="t" style="margin-top:6px"><thead><tr><th>Módulo</th><th class="n">Peso</th><th class="n">Respostas</th><th class="n">Acerto</th><th></th></tr></thead><tbody>${d.modulos.map((m) =>
      `<tr><td class="nome" title="${esc(m.titulo)}">M${m.numero} ${esc(m.titulo)}</td><td class="n">${m.peso}%</td><td class="n">${m.respostas}</td><td class="n">${m.acerto === null ? "—" : fmt(m.acerto * 100, 0) + "%"}</td><td>${m.acerto === null ? "" : barra(m.acerto)}</td></tr>`).join("")}</tbody></table>`;
  rodape(painel, "Pratique no Telegram: /questao, /simulado, /flashcards · /area troca a área ativa");
}

// TASK — lembretes e tarefas (os mesmos do Telegram)
function renderTask(corpo, d, painel) {
  const tarefas = d.tarefas || [];
  corpo.innerHTML = `<form class="form-v2 linha-form" data-rapida><label style="flex:3 1 220px">Tarefa rápida<input name="texto" required placeholder="amanhã às 10h ligar para o CLI-012"></label><button type="submit">Criar</button></form>
    ${tarefas.length ? `<table class="t">${tarefas.map((t) => `<tr><td class="nome" title="${esc(t.texto)}">${esc(t.descricao)}</td>
      <td><button type="button" class="mini" data-org="${t.id}:feito" aria-label="Concluir">✓</button> <button type="button" class="mini" data-org="${t.id}:amanha" title="Adiar para amanhã">→</button></td></tr>`).join("")}</table>` : '<div class="dica">Nenhuma tarefa pendente.</div>'}
    <div class="painel-titulo" style="margin:8px 0 2px">Rotinas e lembretes</div>
    ${d.itens.length ? `<table class="t"><tbody>${d.itens.map((a) => `<tr><td class="n" style="text-align:left">${hora(a.proxima)}</td><td class="nome" title="${esc(a.texto)}">${a.tipo === "lembrete" ? "⏰" : "⚙️"} ${esc(a.texto)}</td><td class="dica">${esc(a.recorrencia)}</td><td><button type="button" class="mini" data-del="${a.id}" aria-label="Cancelar">✕</button></td></tr>`).join("")}</tbody></table>`
    : '<div class="dica">Nenhum agendamento.</div>'}
    <form class="form-v2 linha-form" style="margin-top:6px"><label style="flex:2 1 180px">Texto<input name="texto" required placeholder="Ligar para CLI-004"></label>
      <label>Tipo<select name="tipo"><option value="lembrete">lembrete</option><option value="tarefa">tarefa do agente</option></select></label>
      <label>Quando<input name="quando" type="datetime-local"></label>
      <label>Repetir<select name="recorrencia"><option>uma vez</option><option value="diario">todo dia</option><option value="dias_uteis">dias úteis</option><option value="semanal">toda semana</option><option value="mensal">todo mês</option></select></label>
      <button type="submit">Agendar</button></form>`;
  corpo.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    try { await acao(`/api/tarefas/${b.dataset.del}`, undefined, "DELETE"); atualizarPainel(painel); } catch (e) { aviso(e.message); }
  }));
  corpo.querySelectorAll("[data-org]").forEach((b) => (b.onclick = async () => {
    const [id, ac] = b.dataset.org.split(":");
    try { const r = await acao(`/api/organizacao/tarefa/${id}/${ac}`); aviso(r.descricao || "ok"); atualizarPainel(painel); } catch (e) { aviso(e.message); }
  }));
  $("[data-rapida]", corpo).onsubmit = async (e) => {
    e.preventDefault();
    try { const r = await acao("/api/organizacao/tarefa", Object.fromEntries(new FormData(e.target))); aviso(r.descricao, 6000); atualizarPainel(painel); } catch (err) { aviso(err.message, 6000); }
  };
  $("form:not([data-rapida])", corpo).onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    if (f.recorrencia !== "uma vez") { // o agendador pede o dia e a hora da repetição: tirados do campo "Quando"
      if (!f.quando) return aviso("Para repetir, preencha “Quando” com a primeira data e hora.");
      const dt = new Date(f.quando), hhmm = f.quando.slice(11, 16);
      const dias = ["domingo", "segunda", "terca", "quarta", "quinta", "sexta", "sabado"];
      if (f.recorrencia === "semanal") f.recorrencia += " " + dias[dt.getDay()];
      if (f.recorrencia === "mensal") f.recorrencia += " " + Math.min(28, dt.getDate());
      f.recorrencia += " " + hhmm;
      delete f.quando;
    }
    try { const r = await acao("/api/tarefas", f); aviso("Agendado: " + r.descricao); atualizarPainel(painel); } catch (err) { aviso(err.message, 6000); }
  };
  rodape(painel, "o bot do Telegram avisa na hora · tarefa do agente = o Quíron executa o pedido e manda o resultado");
}

// ALRT — alertas de preço, variação e notícia
function renderAlrt(corpo, d, painel) {
  corpo.innerHTML = `${d.itens.length ? `<table class="t"><tbody>${d.itens.map((a) => `<tr><td class="nome" title="${esc(a.descricao)}">${a.ativo_agora ? "🔔" : "·"} ${esc(a.descricao.replace(/^#\d+ /, "").replace(" 🔔 DISPARADO", ""))}</td><td class="dica">${a.disparado_em ? "último: " + hora(a.disparado_em) : ""}</td><td><button type="button" class="mini" data-del="${a.id}" aria-label="Remover">✕</button></td></tr>`).join("")}</tbody></table>`
    : '<div class="dica">Nenhum alerta. Crie abaixo (ex.: PETR4 abaixo de 30, IBOV variar 2%, notícia “Copom”).</div>'}
    <form class="form-v2 linha-form" style="margin-top:6px"><label>Tipo<select name="tipo">${Object.entries(d.tipos).map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join("")}</select></label>
      <label>Ativo ou palavra<input name="alvo" required placeholder="PETR4"></label><label>Valor<input name="valor" inputmode="decimal" placeholder="30,50"></label>
      <button type="submit">Criar</button><button type="button" data-avaliar title="Confere todos os alertas agora">avaliar agora</button></form>`;
  corpo.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    try { await acao(`/api/alertas/${b.dataset.del}`, undefined, "DELETE"); atualizarPainel(painel); } catch (e) { aviso(e.message); }
  }));
  $("form", corpo).onsubmit = async (e) => {
    e.preventDefault();
    try { const r = await acao("/api/alertas", Object.fromEntries(new FormData(e.target))); aviso("Criado: " + r.descricao); atualizarPainel(painel); } catch (err) { aviso(err.message, 6000); }
  };
  $("[data-avaliar]", corpo).onclick = async () => {
    try { const r = await acao("/api/alertas/avaliar"); aviso(r.disparados.length ? "🔔 " + r.disparados.join(" · ") : "Nenhum alerta disparou agora."); atualizarPainel(painel); } catch (err) { aviso(err.message); }
  };
  rodape(painel, "o bot do Telegram confere a cada 5 minutos e avisa uma vez por disparo");
}

// CHAT — o agente do Quíron dentro do Terminal (mesmas ferramentas, persona e regras de compliance do Telegram)
function textoChat(s) {
  return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|\s)\*(\S.*?\S)\*(?=\s|$)/g, "$1<b>$2</b>").replace(/\n/g, "<br>");
}
async function renderChat(corpo, _d, painel) {
  corpo.classList.add("coluna");
  corpo.innerHTML = `<div class="chat-msgs" data-msgs></div>
    <form class="chat-form"><textarea name="texto" rows="2" placeholder="Pergunte ao Quíron… (Enter envia, Shift+Enter quebra linha, /novo reinicia)" aria-label="Mensagem para o Quíron"></textarea><button type="submit">Enviar</button></form>`;
  const msgs = $("[data-msgs]", corpo), form = $("form", corpo), caixa = $("textarea", corpo);
  const balao = (papel, html) => { const el = document.createElement("div"); el.className = "msg " + papel; el.innerHTML = html; msgs.append(el); msgs.scrollTop = msgs.scrollHeight; return el; };
  const pendencias = (lista) => lista.forEach((p) => {
    const el = balao("sistema", `🔐 Aprovar? ${esc(p.resumo)} <button type="button" class="mini" data-s>✅ aprovar</button> <button type="button" class="mini" data-n>❌ negar</button>`);
    const decidir = async (aprovar) => {
      el.querySelectorAll("button").forEach((b) => (b.disabled = true));
      try { const r = await acao("/api/chat/decidir", { id: p.id, aprovar }); balao("quiron", textoChat(r.resposta)); } catch (e) { balao("sistema", esc(e.message)); }
    };
    $("[data-s]", el).onclick = () => decidir(true);
    $("[data-n]", el).onclick = () => decidir(false);
  });
  try {
    const h = await (await fetch("/api/chat/historico")).json();
    h.mensagens.forEach((m) => balao(m.papel === "user" ? "eu" : "quiron", textoChat(m.texto)));
    if (!h.mensagens.length) balao("sistema", "Converse com o Quíron como no Telegram: análises, estudo, fundos, empresas, clientes (só CLI-XXX).");
  } catch (e) { balao("sistema", "Sem conexão com o servidor."); }
  form.onsubmit = async (e) => {
    e.preventDefault();
    const texto = caixa.value.trim();
    if (!texto) return;
    caixa.value = "";
    balao("eu", textoChat(texto));
    const espera = balao("sistema", '<span class="carregando">Quíron pensando… (pode levar até 1 minuto)</span>');
    form.querySelector("button").disabled = true;
    try {
      const r = await acao("/api/chat", { texto });
      espera.remove();
      balao("quiron", textoChat(r.resposta) + (r.ferramentas?.length ? `<div class="memoria">ferramentas: ${esc(r.ferramentas.join(", "))}${r.segundos ? ` · ${fmt(r.segundos, 0)} s` : ""}</div>` : ""));
      pendencias(r.pendencias || []);
      if (r.ferramentas?.some((f) => f.includes("analisar"))) paineis.filter((p) => p.tipo === "rpt").forEach((p) => renderRpt($(".painel-corpo", document.getElementById(p.id)), null, p));
    } catch (err) { espera.innerHTML = `<span class="erro">${esc(err.message)}</span>`; }
    form.querySelector("button").disabled = false;
    caixa.focus();
  };
  caixa.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  rodape(painel, "mesmo agente do Telegram (persona, ferramentas e compliance) · conversa própria do Terminal");
}

// BIB — biblioteca (funciona sem internet)
function renderBib(corpo, _d, painel) {
  corpo.innerHTML = `<form class="form-v2 linha-form"><label style="flex:3 1 220px">Procurar nos livros<input name="q" value="${esc(painel.p.q || "")}" placeholder="duration e convexidade"></label><button type="submit">Buscar</button></form><div data-res class="texto-pre"></div>`;
  const res = $("[data-res]", corpo);
  const buscar = async () => {
    if (!painel.p.q) { res.textContent = "Digite um tema."; return; }
    res.innerHTML = '<span class="carregando">procurando…</span>';
    try {
      const r = await fetch(`/api/biblioteca?q=${encodeURIComponent(painel.p.q)}`);
      const d = await r.json();
      res.textContent = r.ok ? d.texto : (d.detail || "erro");
    } catch (e) { res.textContent = "Sem conexão com o servidor"; }
  };
  $("form", corpo).onsubmit = (e) => { e.preventDefault(); painel.p.q = new FormData(e.target).get("q"); salvarLocal(); titular(painel); buscar(); };
  buscar();
  rodape(painel, "📚 índice local da biblioteca · cite livro e capítulo");
}

// CLI — clientes reais (só na versão offline, só neste PC; cofre criptografado)
async function renderCli(corpo, _d, painel) {
  const modo = await (await fetch("/api/modo")).json().catch(() => ({}));
  if (!modo.offline) { corpo.innerHTML = '<div class="dica">Os nomes reais dos clientes só aparecem na versão offline (atalho “Quiron Offline”), neste PC.</div>'; return; }
  if (!modo.cofre_aberto) {
    corpo.innerHTML = `<form class="form-v2" data-abrir><label>${modo.cofre_existe ? "Senha do cofre" : "Crie a senha do cofre (mín. 10 caracteres — sem ela não há recuperação)"}<input name="senha" type="password" autocomplete="current-password" required></label>
      <button type="submit">${modo.cofre_existe ? "Abrir" : "Criar cofre"}</button></form>`;
    $("[data-abrir]", corpo).onsubmit = async (e) => {
      e.preventDefault();
      try { await acao("/api/cofre/abrir", { senha: new FormData(e.target).get("senha"), criar: !modo.cofre_existe }); renderCli(corpo, null, painel); }
      catch (err) { aviso(err.message); }
    };
    rodape(painel, "cofre criptografado (Scrypt + AES) · fecha sozinho após 15 min");
    return;
  }
  const lista = await (await fetch(`/api/cofre/clientes?q=${encodeURIComponent(painel.p.q || "")}`, { headers: { "X-Quiron": "terminal" } })).json();
  corpo.innerHTML = `<form class="form-v2 linha-form" data-busca><label style="flex:3 1 160px">Nome, código ou telefone<input name="q" value="${esc(painel.p.q || "")}"></label><button type="submit">Filtrar</button><button type="button" data-fechar>🔒 Fechar</button></form>
    <table class="t">${(lista.itens || []).map((c) => `<tr class="clicavel" data-cod="${esc(c.codigo)}"><td>${esc(c.codigo)}</td><td class="nome">${esc(c.nome)}</td><td class="dica">${esc(c.cidade || "")}</td></tr>`).join("") || '<tr><td class="dica">Nenhum cliente no cofre.</td></tr>'}</table>
    <details><summary class="dica">+ cadastrar / editar cliente</summary><form class="form-v2" data-novo>
      <div class="linha-form"><label>Código<input name="codigo" required placeholder="CLI-012"></label><label style="flex:2 1 160px">Nome<input name="nome" required></label></div>
      <div class="linha-form"><label>Telefone<input name="telefone"></label><label>E-mail<input name="email"></label><label>Cidade<input name="cidade"></label></div>
      <button type="submit">Salvar no cofre</button></form></details><div data-cli></div>`;
  $("[data-busca]", corpo).onsubmit = (e) => { e.preventDefault(); painel.p.q = new FormData(e.target).get("q"); renderCli(corpo, null, painel); };
  $("[data-fechar]", corpo).onclick = async () => { await acao("/api/cofre/fechar"); renderCli(corpo, null, painel); };
  $("[data-novo]", corpo).onsubmit = async (e) => {
    e.preventDefault();
    try { await acao("/api/cofre/cliente", Object.fromEntries(new FormData(e.target))); aviso("Salvo no cofre."); renderCli(corpo, null, painel); } catch (err) { aviso(err.message); }
  };
  corpo.querySelectorAll("[data-cod]").forEach((tr) => (tr.onclick = async () => {
    const alvo = $("[data-cli]", corpo);
    try {
      const r = await fetch(`/api/cofre/cliente/${encodeURIComponent(tr.dataset.cod)}`, { headers: { "X-Quiron": "terminal" } });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail);
      const c = d.cliente;
      alvo.innerHTML = `<div class="grande" style="font-size:18px">${esc(c.nome)} <span class="dica">${esc(c.codigo)}</span></div>
        <div class="dica">${[c.telefone, c.email, c.cidade].filter(Boolean).map(esc).join(" · ")}</div><pre class="texto-pre">${esc(d.dossie)}</pre>`;
    } catch (err) { alvo.innerHTML = `<div class="erro">${esc(err.message)}</div>`; }
  }));
  rodape(painel, "só neste PC, versão offline · o agente e os relatórios continuam usando só o código CLI-XXX");
}

Object.assign(TIPOS, {
  bib: { titulo: (p) => (p.q ? `Biblioteca: ${p.q}` : "Biblioteca — BIB"), topico: null, w: 6, h: 11, render: renderBib },
  cli: { titulo: "Clientes — CLI (offline)", topico: null, w: 6, h: 12, render: renderCli },
});
PRESETS["Offline"] = [
  { tipo: "cli", x: 1, y: 1, w: 6, h: 13 }, { tipo: "chat", x: 7, y: 1, w: 6, h: 13 },
  { tipo: "bib", x: 1, y: 14, w: 6, h: 10 }, { tipo: "task", x: 7, y: 14, w: 6, h: 10 },
];

Object.assign(TIPOS, {
  fa: { titulo: (p) => `${p.ticker} FA`, topico: "fa", params: (p) => ({ ticker: p.ticker }), w: 6, h: 12, render: renderFa },
  fundos: { titulo: (p) => `Fundos: ${p.termo}`, topico: "fundos", params: (p) => ({ termo: p.termo }), w: 6, h: 11, render: renderFundos },
  cmpf: { titulo: "Comparar fundos — CMPF", topico: null, w: 4, h: 9, render: renderCmpf },
  port: { titulo: "Carteira — PORT", topico: null, w: 6, h: 12, render: renderPort },
  plan: { titulo: (p) => (p.cliente ? `Planejamento ${p.cliente}` : "Planejamento — PLAN"), topico: "plano", params: (p) => ({ cliente: p.cliente || "" }), w: 5, h: 11, render: renderPlan },
  acad: { titulo: "Academia — ACAD", topico: "academia", w: 5, h: 10, render: renderAcad },
  task: { titulo: "Tarefas e lembretes — TASK", topico: "tarefas", w: 6, h: 9, render: renderTask },
  alrt: { titulo: "Alertas — ALRT", topico: "alertas", w: 6, h: 9, render: renderAlrt },
  chat: { titulo: "Chat com o Quíron", topico: null, w: 5, h: 14, render: renderChat },
});
PRESETS["Assessoria"] = [
  { tipo: "chat", x: 1, y: 1, w: 5, h: 14 }, { tipo: "rpt", x: 6, y: 1, w: 4, h: 8 }, { tipo: "alrt", x: 10, y: 1, w: 3, h: 8 },
  { tipo: "task", x: 6, y: 9, w: 4, h: 6 }, { tipo: "plan", x: 10, y: 9, w: 3, h: 6 }, { tipo: "acad", x: 1, y: 15, w: 5, h: 9 },
  { tipo: "watchlist", x: 6, y: 15, w: 4, h: 9 }, { tipo: "noticias", x: 10, y: 15, w: 3, h: 9 },
];

// comandos da v2; devolve true se tratou
function executarV2(original, a, b, resto) {
  const unico = { PORT: "port", ACAD: "acad", TASK: "task", ALRT: "alrt", CMPF: "cmpf", CHAT: "chat", IA: "chat", CLI: "cli", BIB: "bib" };
  if (a === "BIB" && b) { adicionarPainel("bib", { q: original.trim().split(/\s+/).slice(1).join(" ") }); return true; }
  if (unico[a] && !b) { adicionarPainel(unico[a]); return true; }
  if (a === "CHAT" || a === "IA") { // CHAT <pergunta>: abre o chat já com a pergunta
    const p = adicionarPainel("chat");
    setTimeout(() => { const c = $(`#${p.id} textarea`); if (c) { c.value = original.trim().split(/\s+/).slice(1).join(" "); $(`#${p.id} form`).requestSubmit(); } }, 400);
    return true;
  }
  if (a === "CMPF") { adicionarPainel("cmpf", { cnpjs: [b, ...resto] }); return true; }
  if (a === "PLAN") {
    if (b && !/^CLI-\w+$/.test(b)) { aviso("Use PLAN CLI-XXX (só o código do cliente)."); return true; }
    adicionarPainel("plan", { cliente: b || "" }); return true;
  }
  if (a === "FUND") {
    if (!b) { aviso("Use FUND <nome ou CNPJ>, ex.: FUND VERDE"); return true; }
    adicionarPainel("fundos", { termo: original.trim().split(/\s+/).slice(1).join(" ") }); return true;
  }
  const [cmd, ticker] = ["FA", "DCF"].includes(a) ? [a, b] : [b, a];
  if (cmd === "FA" || cmd === "DCF") {
    if (!ticker || !/^[A-Z]{4}\d{1,2}$/.test(ticker)) { aviso(`Use TICKER ${cmd}, ex.: WEGE3 ${cmd}`); return true; }
    if (cmd === "FA") adicionarPainel("fa", { ticker });
    else pedirAnalise("valuation_dcf", { empresa: ticker }, `${ticker} DCF`);
    return true;
  }
  return false;
}

// ------------------------------------------------------------------ comandos
function abrirAtivo(ativo) { adicionarPainel("ativo", { ativo }); }
function executar(texto) {
  if (!texto.trim()) return;
  const partes = texto.trim().toUpperCase().split(/\s+/).filter(Boolean);
  if (!partes.length) return;
  const [a, b, ...resto] = partes;
  const simples = { TOP: ["noticias", {}], ECO: ["agenda", {}], CURV: ["curva", {}], MACRO: ["macro", {}], JUROS: ["juros", {}], WEI: ["mundo", {}],
    FX: ["moedas", {}], CMDTY: ["commodities", {}], W: ["watchlist", {}], CALC: ["calc", {}], RPT: ["rpt", {}], STATUS: ["status", {}], HELP: ["ajuda", {}], "?": ["ajuda", {}] };
  if (simples[a] && !b) return adicionarPainel(...simples[a]);
  const telas = { CONFIG: "/config", CONF: "/config", CONFIGURACOES: "/config", "CONFIGURAÇÕES": "/config", SIS: "/config", ACERVO: "/acervo" };
  if (telas[a] && !b) { location.href = telas[a]; return; }
  if ((a === "NEWS" || a === "N") && b) return adicionarPainel("noticias", { termo: [b, ...resto].join(" ").toLowerCase() });
  if (a === "SOC" && b) return adicionarPainel("redes", { termo: [b, ...resto].join(" ").toLowerCase() });
  if (a === "SOC") return aviso("Use SOC <tema>, ex.: SOC COPOM");
  if (executarV2(texto, a, b, resto)) return;
  const ativo = { DOLAR: "USDBRL", "DÓLAR": "USDBRL", EURO: "EURBRL", BRENT: "petroleo_brent", OURO: "ouro" }[a] || a;
  if (/^[A-Z0-9^=.\-_]{2,12}$/i.test(ativo)) return adicionarPainel(b === "GP" ? "grafico" : "ativo", { ativo });
  aviso("Comando não reconhecido. Digite HELP.");
}

// ------------------------------------------------------------------ início
function relogio() {
  $("#relogio").textContent = new Date().toLocaleString("pt-BR", { ...BRT, weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
document.addEventListener("keydown", (e) => {
  const naBarra = document.activeElement === $("#comando");
  if ((e.key === "/" && !naBarra && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) || (e.ctrlKey && e.key.toLowerCase() === "k")) {
    e.preventDefault(); $("#comando").focus(); $("#comando").select();
  } else if (e.key === "Escape" && naBarra) { $("#comando").blur(); }
  else if (e.altKey && ["1", "2", "3", "4"].includes(e.key)) { e.preventDefault(); aplicarLayout(Object.values(PRESETS)[+e.key - 1]); }
});
$("#barra").addEventListener("submit", (e) => { e.preventDefault(); executar($("#comando").value); $("#comando").value = ""; });
$("#layout").addEventListener("change", (e) => {
  const v = e.target.value;
  if (v.startsWith("p:")) aplicarLayout(PRESETS[v.slice(2)]);
  if (v.startsWith("s:")) aplicarLayout(layoutsSalvos[v.slice(2)]);
  e.target.value = "";
});
$("#salvar").addEventListener("click", async () => {
  const nome = prompt("Nome do layout:");
  if (!nome) return;
  await fetch(`/api/layouts/${encodeURIComponent(nome)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(paineis.map(({ id, _timer, ...r }) => r)) });
  await carregarLayouts();
  aviso(`Layout "${nome}" salvo.`);
});
window.addEventListener("resize", () => { clearTimeout(window._r); window._r = setTimeout(() => paineis.filter((p) => p.tipo === "curva").forEach((p) => enviar({ tipo: "atualizar", id: p.id })), 400); });

const semLayoutSalvo = !carregarLocal();
fetch("/api/modo").then((r) => r.json()).then((m) => {
  if (!m.offline) return;
  const selo = Object.assign(document.createElement("span"), { className: "selo-offline", textContent: "OFFLINE", title: `Sem internet · modelo local ${m.modelo} · dados de mercado do último cache` });
  $(".marca").append(selo);
  if (semLayoutSalvo) aplicarLayout(PRESETS["Offline"]);
}).catch(() => {});
relogio();
setInterval(relogio, 1000);
carregarLayouts();
aplicarLayout(carregarLocal() || PRESETS["Manhã"]);
conectar();
window.quiron = { executar, paineis: () => paineis }; // usado pelos testes de navegador
