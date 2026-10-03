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
  try { localStorage.setItem("quiron-layout-atual", JSON.stringify(paineis.map(({ id, ...r }) => r))); } catch (e) { /* sem storage */ }
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
  for (let a = 0; a <= xmax; a += xmax > 8 ? 2 : 1) s += `<text x="${X(a)}" y="${H - 6}" text-anchor="${a === 0 ? "start" : "middle"}">${a} ${a === 1 ? "ano" : "anos"}</text>`;
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
    ${d.regras_pendentes.length ? `<div class="erro" style="margin-top:4px">⚠ ${d.regras_pendentes.length} bloco(s) de regras de mercado sem verificação</div>` : ""}`;
  rodape(painel, "no ar desde " + hora(d.no_ar_desde));
}

const CALCS = {
  juros_compostos: { nome: "Juros compostos", campos: [["valor_inicial", "Valor inicial (R$)", 10000], ["aporte_mensal", "Aporte mensal (R$)", 1000], ["taxa_aa", "Taxa (% a.a.)", 12], ["anos", "Prazo (anos)", 10]] },
  equivalencia: { nome: "Equivalência", campos: [["taxa", "Taxa (%)", 12], ["periodo", "Período da taxa", "aa", [["aa", "ao ano"], ["am", "ao mês"]]]] },
  cdb_x_isento: { nome: "CDB × LCI", campos: [["taxa_isenta_aa", "LCI/LCA (% a.a.)", 11], ["taxa_cdb_aa", "CDB (% a.a.)", 13.5], ["dias", "Prazo (dias)", 720]] },
  taxa_real: { nome: "Taxa real", campos: [["nominal_aa", "Taxa nominal (% a.a.)", 13.75], ["inflacao_aa", "Inflação (% a.a.)", 4.5]] },
  percentual_cdi: { nome: "% do CDI", campos: [["percentual", "% do CDI", 110]] },
};
function renderCalc(corpo, _d, painel) {
  const atual = painel.p.calc || "juros_compostos";
  const def = CALCS[atual];
  corpo.innerHTML = `<div class="calc-abas">${Object.entries(CALCS).map(([k, c]) => `<button data-c="${k}" class="${k === atual ? "ativo" : ""}">${c.nome}</button>`).join("")}</div>
    <form class="calc-form">${def.campos.map(([k, rot, val, ops]) => ops
      ? `<label>${rot}<select name="${k}">${ops.map(([v, t]) => `<option value="${v}" ${v === val ? "selected" : ""}>${t}</option>`).join("")}</select></label>`
      : `<label>${rot}<input name="${k}" value="${String(val).replace(".", ",")}" inputmode="decimal"></label>`).join("")}</form>
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

function renderAjuda(corpo) {
  const cmds = [
    ["PETR4", "Visão do ativo: cotação, gráfico de 3 meses e notícias"], ["PETR4 GP", "Gráfico com médias móveis e comparação com o Ibovespa"],
    ["TOP", "Principais notícias agora"], ["NEWS <tema>", "Notícias de um tema ou ticker (ex.: NEWS COPOM)"], ["SOC <tema>", "O que as redes dizem"],
    ["ECO", "Agenda econômica"], ["CURV", "Curva de juros pré, real e inflação implícita"], ["MACRO", "Painel macro e Focus"],
    ["JUROS", "Selic, CDI e Tesouro"], ["WEI", "Índices mundiais"], ["FX", "Moedas"], ["CMDTY", "Commodities"], ["W", "Watchlist"],
    ["CALC", "Calculadoras"], ["STATUS", "Saúde do sistema"], ["HELP", "Esta ajuda"],
  ];
  corpo.innerHTML = `<dl class="ajuda">${cmds.map(([c, d]) => `<dt>${esc(c)}</dt><dd>${esc(d)}</dd>`).join("")}</dl>
    <div class="dica">Atalhos: <b>/</b> ou <b>Ctrl+K</b> barra de comando · <b>Esc</b> sai da barra · <b>Alt+1/2/3</b> layouts Manhã/Análise/Estudo · arraste o cabeçalho para mover, o canto para redimensionar.<br>
    Na v2 (Fase 12): FA, DCF, PORT, FUND, CMPF, PLAN, RPT, ACAD, TASK, ALRT e chat.</div>`;
}

function renderFita(lista) {
  if (!Array.isArray(lista)) return;
  $("#fita").innerHTML = lista.filter((c) => !c.erro).map((c) => `<span><b>${esc(c.nome)}</b> ${preco(c)} ${variacao(c.variacao)}</span>`).join("");
}
function rodape(painel, html) { $(".painel-rodape", document.getElementById(painel.id)).innerHTML = html; }

// ------------------------------------------------------------------ comandos
function abrirAtivo(ativo) { adicionarPainel("ativo", { ativo }); }
const V2 = new Set(["FA", "DCF", "PORT", "FUND", "CMPF", "PLAN", "RPT", "ACAD", "TASK", "ALRT"]);
function executar(texto) {
  const partes = texto.trim().toUpperCase().split(/\s+/).filter(Boolean);
  if (!partes.length) return;
  const [a, b, ...resto] = partes;
  const simples = { TOP: ["noticias", {}], ECO: ["agenda", {}], CURV: ["curva", {}], MACRO: ["macro", {}], JUROS: ["juros", {}], WEI: ["mundo", {}],
    FX: ["moedas", {}], CMDTY: ["commodities", {}], W: ["watchlist", {}], CALC: ["calc", {}], STATUS: ["status", {}], HELP: ["ajuda", {}], "?": ["ajuda", {}] };
  if (simples[a] && !b) return adicionarPainel(...simples[a]);
  if ((a === "NEWS" || a === "N") && b) return adicionarPainel("noticias", { termo: [b, ...resto].join(" ").toLowerCase() });
  if (a === "SOC" && b) return adicionarPainel("redes", { termo: [b, ...resto].join(" ").toLowerCase() });
  if (a === "SOC") return aviso("Use SOC <tema>, ex.: SOC COPOM");
  if (V2.has(a) || V2.has(b)) return aviso(`${b || a} chega no Terminal v2 (Fase 12).`);
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
  else if (e.altKey && ["1", "2", "3"].includes(e.key)) { e.preventDefault(); aplicarLayout(Object.values(PRESETS)[+e.key - 1]); }
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
  await fetch(`/api/layouts/${encodeURIComponent(nome)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(paineis.map(({ id, ...r }) => r)) });
  await carregarLayouts();
  aviso(`Layout "${nome}" salvo.`);
});
window.addEventListener("resize", () => { clearTimeout(window._r); window._r = setTimeout(() => paineis.filter((p) => p.tipo === "curva").forEach((p) => enviar({ tipo: "atualizar", id: p.id })), 400); });

relogio();
setInterval(relogio, 1000);
carregarLayouts();
aplicarLayout(carregarLocal() || PRESETS["Manhã"]);
conectar();
window.quiron = { executar, paineis: () => paineis }; // usado pelos testes de navegador
