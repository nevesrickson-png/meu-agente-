// Barra de abas comum: preenche <nav id="abas"> e mostra o selo do sistema (Telegram, chaves, modo offline).
"use strict";
(function () {
  const alvo = document.getElementById("abas");
  if (!alvo) return;
  const abas = [["/", "TERMINAL", "TERM"], ["/acervo", "ACERVO", "ACERVO"], ["/config", "CONFIGURAÇÕES", "⚙ CONFIG"]];
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
  const selo = document.createElement("a");
  selo.className = "selo-sistema";
  selo.href = "/config#visao";
  selo.textContent = "…";
  alvo.append(selo);

  const TEXTO = {
    ligado: ["ok", "● ", "Telegram ligado"], religando: ["aviso", "◐ ", "Telegram religando"],
    desligado: ["", "○ ", "Telegram desligado"], sem_config: ["aviso", "! ", "Faltam chaves"],
    offline: ["aviso", "⊘ ", "OFFLINE"], externo: ["", "● ", "Servidor"], erro: ["erro", "✖ ", "Telegram com erro"],
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
      selo.className = "selo-sistema erro";
      selo.innerHTML = `✖ <span class="texto">sem conexão</span>`;
    }
  }
  atualizar();
  setInterval(atualizar, 15000);
  window.quironAtualizarSelo = atualizar;
})();
