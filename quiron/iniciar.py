"""`uv run quiron` — abre o Quíron inteiro com um comando só (é o que o atalho Quiron chama).

Sobe o Terminal no modo central (Terminal + Acervo + Configurações + bot do Telegram supervisionado) e fica de olho:
- se o Terminal pedir troca de modo (código 3), religa no modo gravado em `dados/modo_proximo` (normal/offline);
- se cair por erro, religa em 30 segundos;
- se o Quíron já estiver aberto, só abre a tela no navegador (nunca dois ao mesmo tempo)."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser

import httpx

from quiron.terminal.backend.central import CODIGO_TROCA_MODO, arquivo_modo, ler_modo_pedido

CODIGO_TERMINAL = "from quiron.terminal.backend.app import main; main()"


def ja_aberto(porta: int) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{porta}/api/sistema/resumo", timeout=2)
    except httpx.HTTPError:
        return False
    return r.status_code in {200, 401}  # 401 = Terminal com senha: também é o Quíron


def porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", porta))
        except OSError:
            return False
    return True


def ambiente(modo: str) -> dict[str, str]:
    env = {**os.environ, "QUIRON_CENTRAL": "1", "PYTHONIOENCODING": "utf-8"}
    if modo == "offline":
        env["QUIRON_MODO"] = "offline"
    else:
        env.pop("QUIRON_MODO", None)
    return env


def rodar(modo: str, porta: int, navegador: bool, chamar=subprocess.call, dormir=time.sleep, espera: float = 30) -> int:
    """Laço do lançador. `chamar`/`dormir` são trocados nos testes."""
    primeira, quedas_rapidas = True, 0
    while True:
        print(f"\n=== Quíron — modo {'OFFLINE (sem internet)' if modo == 'offline' else 'normal'} ===")
        cmd = [sys.executable, "-c", CODIGO_TERMINAL, "--central", "--porta", str(porta)]
        if not (navegador and primeira):
            cmd.append("--sem-navegador")
        inicio = time.monotonic()
        try:
            codigo = chamar(cmd, env=ambiente(modo))
        except KeyboardInterrupt:
            return 0
        primeira = False
        quedas_rapidas = quedas_rapidas + 1 if time.monotonic() - inicio < 20 and codigo not in (0, CODIGO_TROCA_MODO) else 0
        if quedas_rapidas >= 3:
            print("O Quíron não conseguiu abrir 3 vezes seguidas. Veja a mensagem de erro acima "
                  "(se precisar de ajuda, copie as últimas linhas desta janela).")
            return 1
        if codigo == CODIGO_TROCA_MODO:
            modo = ler_modo_pedido(modo)
            continue
        if codigo in (0, 130) or codigo < 0 and os.name != "nt":
            return 0
        print(f"O Quíron parou (código {codigo}). Religando em {int(espera)} segundos — feche a janela para desligar de vez.")
        try:
            dormir(espera)
        except KeyboardInterrupt:
            return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Abre o Quíron (Terminal + Configurações + Telegram)")
    p.add_argument("--offline", action="store_true", help="abre direto na versão offline (sem internet)")
    p.add_argument("--porta", type=int, default=int(os.environ.get("TERMINAL_PORTA", "8765").split(" #")[0] or 8765))
    p.add_argument("--sem-navegador", action="store_true")
    a = p.parse_args()
    if ja_aberto(a.porta):
        print("O Quíron já está aberto: abrindo a tela no navegador.")
        if not a.sem_navegador:
            webbrowser.open(f"http://localhost:{a.porta}/")
        return
    if not porta_livre(a.porta):
        print(f"A porta {a.porta} do PC está ocupada por outro programa, então o Quíron não consegue abrir.\n"
              "Feche esse programa ou reinicie o PC e abra o Quíron de novo.")
        raise SystemExit(1)
    modo = "offline" if a.offline else "normal"
    arquivo_modo().unlink(missing_ok=True)
    raise SystemExit(rodar(modo, a.porta, not a.sem_navegador))


if __name__ == "__main__":
    main()
