// Barra de abas comum: preenche <nav id="abas"> e mostra o selo do sistema (Telegram, chaves, modo offline).
"use strict";
(function () {
  const alvo = document.getElementById("abas");
  if (!alvo) return;
  const abas = [["/", "Terminal", "Terminal"], ["/tv", "TV", "TV"], ["/acervo", "Acervo", "Acervo"], ["/config", "Configurações", "Ajustes"]];
  const aqui = location.pathname.replace(/\/+$/, "") || "/";
  alvo.classList.add("abas");
  alvo.setAttribute("aria-label", "Telas do Quíron");
  for (const [href, longo, curto] of abas) {
    const a = document.createElement("a");
    a.href = href;
    a.innerHTML = `<span class="longo">${longo}</span><span class="curto">${curto}</span>`;
    if (aqui === href) a.setAttribute("aria-current", "page");
    alvo.append(a);
  }
  const extra = document.createElement("span");
  extra.className = "nav-extra";
  const selo = document.createElement("a");
  selo.className = "selo-sistema";
  selo.href = "/config#visao";
  selo.textContent = "…";
  // tema: automático (segue o sistema) → claro → escuro
  const ROTULO = { auto: ["auto", "Tema automático (segue o sistema)"], claro: ["sol", "Tema claro"], escuro: ["lua", "Tema escuro"] };
  const botaoTema = document.createElement("button");
  botaoTema.type = "button";
  botaoTema.className = "botao-tema";
  const lerTema = () => { try { return localStorage.getItem("quiron-tema") || "auto"; } catch (e) { return "auto"; } };
  const mostrarTema = () => {
    const [icone, rotulo] = ROTULO[lerTema()] || ROTULO.auto;
    botaoTema.innerHTML = window.ico ? window.ico(icone) : "◐";
    botaoTema.title = rotulo + " — clique para trocar";
    botaoTema.setAttribute("aria-label", rotulo);
  };
  botaoTema.onclick = () => {
    const ordem = ["auto", "claro", "escuro"];
    const novo = ordem[(ordem.indexOf(lerTema()) + 1) % ordem.length];
    try { localStorage.setItem("quiron-tema", novo); } catch (e) { /* sem armazenamento: vale só nesta página */ }
    const efetivo = novo === "auto" ? (matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "escuro") : novo;
    document.documentElement.setAttribute("data-tema", efetivo);
    mostrarTema();
    document.dispatchEvent(new CustomEvent("quiron:tema", { detail: efetivo }));
  };
  mostrarTema();
  extra.append(selo, botaoTema);
  const lugar = document.getElementById("nav-extra");  // a página pode reservar o lugar (ex.: canto direito do Terminal)
  if (lugar) lugar.replaceWith(extra); else alvo.after(extra);

  const TEXTO = {
    // classes s-* (não "aviso"/"erro": o Terminal já usa esses nomes para outras coisas)
    ligado: ["s-ok", "", "Telegram ligado"], religando: ["s-aviso", "", "Telegram religando"],
    desligado: ["", "", "Telegram desligado"], sem_config: ["s-aviso", "", "Faltam chaves"],
    offline: ["s-aviso", "", "Offline"], externo: ["s-ok", "", "Servidor"], erro: ["s-erro", "", "Telegram com erro"],
  };
  async function atualizar() {
    try {
      const r = await fetch("/api/sistema/resumo", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      window.quironResumo = d;
      const chave = d.offline ? "offline" : (!d.config_completa ? "sem_config" : d.telegram.situacao);
      const [classe, icone, texto] = TEXTO[chave] || ["", "● ", chave];
      selo.className = "selo-sistema " + classe;
      selo.innerHTML = `${icone}<span class="texto">${texto}</span>`;
      selo.title = texto + " — abrir Configurações";
      document.dispatchEvent(new CustomEvent("quiron:resumo", { detail: d }));
    } catch (e) {
      selo.className = "selo-sistema s-erro";
      selo.innerHTML = `<span class="texto">Sem conexão</span>`;
    }
  }
  atualizar();
  setInterval(() => { if (!document.hidden) atualizar(); }, 15000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });
  window.quironAtualizarSelo = atualizar;
})();
