"""Trava entre PROCESSOS (bot, Terminal e servidores MCP gravam os mesmos arquivos) — sem dependência extra.

    with trava_arquivo(pasta_dados() / "alertas.json"):
        ...  # ler, mudar e gravar sem outro processo no meio
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_locais: dict[str, threading.Lock] = {}
_guarda = threading.Lock()


@contextmanager
def trava_arquivo(alvo: Path, espera: float = 30.0):
    """Trava `<alvo>.trava` (fcntl no Linux, msvcrt no Windows) + uma trava de thread do próprio processo."""
    caminho = Path(str(alvo) + ".trava")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with _guarda:
        local = _locais.setdefault(str(caminho), threading.Lock())
    with local:
        with open(caminho, "a+b") as f:
            limite = time.monotonic() + espera
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt

                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > limite:
                        raise TimeoutError(f"{alvo.name} ocupado por outro processo") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt

                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def gravar_atomico(arq: Path, texto: str) -> None:
    """Grava num temporário e troca de uma vez: queda no meio nunca deixa o arquivo pela metade."""
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_name(f".{arq.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(texto, encoding="utf-8")
    for tentativa in range(5):
        try:
            os.replace(tmp, arq)
            return
        except PermissionError:  # Windows: antivírus/leitor com o arquivo aberto por um instante
            if tentativa == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.2 * (tentativa + 1))
