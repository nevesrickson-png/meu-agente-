"""Academia no Telegram: questões com botões A–D, simulado, flashcards, diagnóstico, plano e painel.

Responde direto (sem passar pelo modelo) — rápido e sem gastar cota. Só a geração de questões novas usa o cérebro.
Botões: `ac:<ação>:...` (cabem nos 64 bytes do Telegram).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date

from quiron.servicos import areas
from quiron.servicos.academia import diagnostico, edital, estudo
from quiron.servicos.academia.banco import LETRAS, Banco, Questao
from quiron.servicos.academia.estudo import Filtro

Botao = tuple[str, str]


@dataclass
class Tela:
    """Mensagem da Academia; `linhas` = linhas de botões."""

    texto: str
    linhas: list[list[Botao]] = field(default_factory=list)


@dataclass
class Clique:
    """Resposta a um botão: `editar` troca o texto da mensagem clicada (sem botões); `novas` vêm depois."""

    editar: str | None = None
    novas: list[Tela] = field(default_factory=list)


COMANDOS = {"questoes", "simulado", "flashcards", "diagnostico", "plano", "academia", "area"}
AVISO_IA = "🤖 Questão gerada por IA e conferida por um 2º modelo. Achou erro? Toque ⚠."


def _tela_questao(q: Questao, prefixo: str, numero: str = "", aviso: bool = True) -> Tela:
    texto = q.texto(numero) + (f"\n\n{AVISO_IA}" if aviso else "")
    return Tela(texto, [[(LETRAS[i], f"{prefixo}:{i}") for i in range(4)], [("⚠ Erro na questão", f"ac:anular:{q.id}")]])


def _feedback(q: Questao, escolha: int) -> str:
    certo = escolha == q.correta
    cab = f"✅ Certo! {q.letra_correta})" if certo else f"❌ Você marcou {LETRAS[escolha]}. Correta: {q.letra_correta})"
    fontes = ("\n" + "\n".join(q.fontes)) if q.fontes else ""
    revisor = "\n⚠️ Revisada pelo mesmo modelo que gerou: confira com atenção." if q.mesmo_revisor else ""
    volta = "" if certo else "\n🔁 Ela volta amanhã para revisão."
    return f"{q.texto()}\n\n{cab} {q.alternativas[q.correta]}\n\n💡 {q.explicacao}{fontes}{revisor}{volta}"


class AcademiaBot:
    def __init__(self, banco: Banco | None = None):
        self.banco = banco or Banco()
        estudo.garantir_semente(self.banco)

    @property
    def area(self) -> str:
        return estudo.area_ativa(self.banco)

    def _area_e_resto(self, args: str) -> tuple[str, str]:
        """Área citada no começo dos argumentos vira a área ativa; senão vale a ativa."""
        achada, resto = areas.reconhecer(args or "")
        if achada:
            estudo.definir_area_ativa(self.banco, achada.id)
            return achada.id, resto
        return self.area, (args or "").strip()

    # ------------------------------------------------------------ comandos
    async def comando(self, nome: str, args: str) -> list[Tela]:
        if nome == "area":
            return [Tela(self.trocar_area(args))]
        if nome == "questoes":
            area, resto = self._area_e_resto(args)
            return await self.questao(Filtro.ler(resto, area))
        if nome == "simulado":
            return await self.iniciar_simulado(args)
        if nome == "flashcards":
            return await self.flashcards(args)
        if nome == "diagnostico":
            area, _ = self._area_e_resto(args)
            return [Tela(diagnostico.texto_diagnostico(diagnostico.diagnosticar(self.banco, area)))]
        if nome == "plano":
            return [Tela(self.plano(args))]
        return [Tela(diagnostico.painel_geral(self.banco, self.area))]

    def trocar_area(self, args: str) -> str:
        if args.strip():
            achada, _ = areas.reconhecer(args)
            if not achada:
                return f"Não achei a área “{args.strip()}”. Veja a lista com /area."
            estudo.definir_area_ativa(self.banco, achada.id)
            programa = "" if edital.tem_programa(achada.id) else "\n(Programa ainda não mapeado: as questões serão gerais da área.)"
            return (f"✅ Área ativa: {achada.nome} ({achada.id}). Agora /questoes, /simulado, /diagnostico e /plano "
                    f"valem para ela.{programa}")
        todas = areas.listar()
        campos = "\n".join(f"• {a.nome} — /area {diagnostico.comando_area(a.id)}" for a in todas if a.tipo == "campo")
        certs = ", ".join(a.id.replace("_", " ") for a in todas if a.tipo == "certificacao")
        return (f"Área ativa: {estudo.nome_area(self.area)}.\n\nCampos:\n{campos}\n\nCertificações: {certs}\n"
                "Ex.: /area economia · /area cfa i · /questoes risco 2 · /simulado renda fixa")

    async def questao(self, filtro: Filtro, cab: str = "") -> list[Tela]:
        q = await asyncio.to_thread(estudo.proxima_questao, self.banco, filtro)
        if not q:
            return [Tela("Não consegui questões agora (limite dos modelos grátis). Tente em alguns minutos.")]
        tela = _tela_questao(q, f"ac:r:{q.id}:{filtro.codigo()}")
        if cab:
            tela.texto = f"{cab}\n\n{tela.texto}"
        return [tela]

    def plano(self, args: str = "") -> str:
        area, resto = self._area_e_resto(args)
        horas = float(self.banco.pref("horas_semana", 5))
        if resto.replace(",", ".").replace("h", "").strip():
            try:
                horas = max(1.0, min(20.0, float(resto.replace(",", ".").replace("h", "").strip())))
                self.banco.definir_pref("horas_semana", horas)
            except ValueError:
                pass
        mods = diagnostico.diagnosticar(self.banco, area)
        prova = diagnostico.data_prova(self.banco, area)
        cartoes = len(self.banco.cards_vencidos(None, 999))
        blocos = diagnostico.plano_semana(mods, horas, self.banco.pref("dias_estudo"), cartoes, prova)
        return diagnostico.texto_plano(mods, blocos, horas, cartoes, prova)

    async def iniciar_simulado(self, args: str = "") -> list[Tela]:
        area, resto = self._area_e_resto(args)
        n = estudo.tamanho(resto.lower() or "mini", area)
        ids, avisos = await asyncio.to_thread(estudo.montar_simulado, self.banco, n, True, 2, area)
        if not ids:
            return [Tela("Sem questões suficientes agora (limite dos modelos grátis). Tente mais tarde.")]
        sid = self.banco.criar_simulado(area, ids, resto.lower() or "mini")
        estilo = "estilo prova" if area == "CFP" else "treino"
        cab = f"🧪 Simulado #{sid} · {estudo.nome_area(area)} — {len(ids)} questões, {estilo} (o gabarito vem no fim)."
        if area == "CFP":
            cab += f"\nTempo de referência: ~{round(len(ids) * 2.9)} min (a prova dá ≈ 2,9 min por questão)."
        if avisos:
            cab += "\n" + "\n".join(f"⚠️ {x}" for x in avisos)
        return [Tela(cab), self._tela_simulado(sid)]

    def _tela_simulado(self, sid: int) -> Tela:
        s = self.banco.simulado(sid)
        pos = s["posicao"]
        q = self.banco.questao(s["questoes"][pos])
        return _tela_questao(q, f"ac:s:{sid}:{q.id}", f"[{pos + 1}/{len(s['questoes'])}]", aviso=False)

    async def flashcards(self, args: str = "") -> list[Tela]:
        """Revisa os cards vencidos de TODAS as áreas; sem nenhum, cria novos na área ativa (ou na citada)."""
        cards = self.banco.cards_vencidos(None, 1)
        if not cards:
            area, resto = self._area_e_resto(args)
            f = Filtro.ler(resto, area)
            modulo = f.modulo or estudo._modulo_por_prioridade(self.banco, area)  # noqa: SLF001
            from quiron.servicos.academia import gerador

            alvo = f.topico or gerador.topicos_para_gerar(modulo, 1, area, self.banco)[0]
            try:
                await asyncio.to_thread(gerador.gerar_flashcards, alvo, 6, area, self.banco)
            except Exception:  # noqa: BLE001
                return [Tela("Nenhum card para revisar hoje e não consegui criar novos agora. ✅")]
            cards = self.banco.cards_vencidos(None, 1)
            if not cards:
                return [Tela("Nenhum card para revisar hoje. ✅")]
        c = cards[0]
        restantes = len(self.banco.cards_vencidos(None, 999))
        return [Tela(f"🃏 Flashcard ({restantes} para hoje) · {c.cert} · M{c.modulo} · {c.topico}\n\n{c.frente}",
                     [[("Mostrar resposta", f"ac:fv:{c.id}")]])]

    # ------------------------------------------------------------ botões
    async def clique(self, dado: str) -> Clique:
        partes = dado.split(":")
        acao = partes[1] if len(partes) > 1 else ""
        if acao == "r" and len(partes) == 5:  # ac:r:<qid>:<filtro>:<escolha>
            qid, filtro, escolha = int(partes[2]), partes[3], int(partes[4])
            q = self.banco.questao(qid)
            if not q:
                return Clique("Questão não encontrada.")
            self.banco.responder(qid, escolha)
            fim = Tela("Continuar?", [[("Próxima ▶", f"ac:prox:{filtro}"), ("Parar", "ac:parar")]])
            return Clique(_feedback(q, escolha), [fim])
        if acao == "prox" and len(partes) == 3:
            return Clique(None, await self.questao(Filtro.do_codigo(partes[2])))
        if acao == "parar":
            return Clique("Até a próxima! /diagnostico mostra como você está.")
        if acao == "s" and len(partes) == 5:  # ac:s:<sid>:<qid>:<escolha>
            sid, qid, escolha = int(partes[2]), int(partes[3]), int(partes[4])
            s = self.banco.simulado(sid)
            if not s or s["terminado_em"] or s["questoes"][s["posicao"]] != qid:
                return Clique(None, [Tela("Essa questão já foi respondida ou o simulado terminou.")])
            q = self.banco.questao(qid)
            self.banco.responder(qid, escolha, f"simulado:{sid}")
            pos = self.banco.avancar_simulado(sid)
            editar = f"{q.texto(f'[{pos}/{len(s['questoes'])}]')}\n\n➡️ Você marcou {LETRAS[escolha]}."
            if pos >= len(s["questoes"]):
                self.banco.terminar_simulado(sid)
                resultado = estudo.texto_resultado_simulado(self.banco, sid)
                diag = diagnostico.texto_diagnostico(diagnostico.diagnosticar(self.banco, s["cert"]))
                return Clique(editar, [Tela(resultado), Tela(diag), Tela(self.plano())])
            return Clique(editar, [self._tela_simulado(sid)])
        if acao == "anular" and len(partes) == 3:
            self.banco.anular(int(partes[2]))
            return Clique(None, [Tela("🗑️ Questão anulada: não volta mais e não conta no diagnóstico. Obrigado!")])
        if acao == "fv" and len(partes) == 3:
            c = self.banco.card(int(partes[2]))
            if not c:
                return Clique("Card não encontrado.")
            fontes = ("\n" + "\n".join(c.fontes)) if c.fontes else ""
            return Clique(f"🃏 {c.frente}", [Tela(f"🃏 {c.frente}\n\n✍️ {c.verso}{fontes}\n\nComo foi?",
                                      [[("Errei", f"ac:fn:{c.id}:0"), ("Difícil", f"ac:fn:{c.id}:3"),
                                        ("Bom", f"ac:fn:{c.id}:4"), ("Fácil", f"ac:fn:{c.id}:5")]])])
        if acao == "fn" and len(partes) == 4:
            prox = self.banco.revisar_card(int(partes[2]), int(partes[3]))
            restantes = self.banco.cards_vencidos(None, 1)
            msg = f"Próxima revisão desse card: {date.fromisoformat(prox):%d/%m}."
            if restantes:
                return Clique(msg, await self.flashcards())
            return Clique(msg, [Tela("✅ Revisão de flashcards do dia concluída.")])
        return Clique(None, [Tela("Botão inválido.")])
