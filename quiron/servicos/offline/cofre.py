"""Cofre de clientes reais: o ÚNICO lugar com o mapa código → nome real (e contatos), CRIPTOGRAFADO por senha.

- Fica em `cofre/clientes.cofre` (fora do git e da pasta dados). Formato: cabeçalho "QUIRON-COFRE-1" + sal (16 bytes) +
  token Fernet (AES-128-CBC + HMAC-SHA256) com chave derivada da senha por Scrypt (n=2^15, r=8, p=1).
- Só abre na versão OFFLINE (`QUIRON_MODO=offline`), quando o cérebro é só local: nome real nunca vai para modelo na nuvem.
- Os nomes não entram em ferramentas do agente: só aparecem na tela CLI do Terminal local (127.0.0.1).
- Sem a senha não há recuperação (é o objetivo). LGPD: `remover` apaga o cliente do cofre.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from quiron.nucleo.config import RAIZ

CABECALHO = b"QUIRON-COFRE-1\n"
CAMPOS = ("nome", "cpf", "telefone", "email", "cidade", "observacoes")


class CofreBloqueado(PermissionError):
    pass


class SenhaErrada(PermissionError):
    pass


def caminho() -> Path:
    return Path(os.environ.get("QUIRON_COFRE") or RAIZ / "cofre" / "clientes.cofre")


def existe() -> bool:
    return caminho().exists()


def _exigir_offline() -> None:
    from quiron.nucleo import offline
    from quiron.nucleo.config import carregar_config

    if not offline.ativo():
        raise CofreBloqueado("o cofre de clientes só abre na versão offline (atalho “Quiron Offline”)")
    if not all(offline.e_local(m) for m in carregar_config().modelos):
        raise CofreBloqueado("há modelo de nuvem configurado; o cofre não abre")


def _chave(senha: str, sal: bytes) -> bytes:
    kdf = Scrypt(salt=sal, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(senha.encode("utf-8")))


@dataclass
class ClienteReal:
    codigo: str
    nome: str
    cpf: str = ""
    telefone: str = ""
    email: str = ""
    cidade: str = ""
    observacoes: str = ""
    atualizado_em: str = ""


@dataclass
class Cofre:
    clientes: dict[str, ClienteReal] = field(default_factory=dict)
    _senha: str = field(default="", repr=False)
    _sal: bytes = field(default=b"", repr=False)

    def salvar(self) -> None:
        dados = json.dumps({k: asdict(v) for k, v in self.clientes.items()}, ensure_ascii=False).encode("utf-8")
        token = Fernet(_chave(self._senha, self._sal)).encrypt(dados)
        arq = caminho()
        arq.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_suffix(".tmp")
        tmp.write_bytes(CABECALHO + self._sal + token)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(arq)  # troca atômica: nunca fica meio gravado

    def gravar(self, codigo: str, **dados: str) -> ClienteReal:
        from quiron.servicos.planejamento.ficha import codigo as normalizar

        cod = normalizar(codigo)
        atual = asdict(self.clientes[cod]) if cod in self.clientes else {"codigo": cod, "nome": ""}
        atual.update({k: str(v).strip() for k, v in dados.items() if k in CAMPOS and v is not None})
        if not atual.get("nome"):
            raise ValueError("informe o nome do cliente")
        atual["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        self.clientes[cod] = ClienteReal(**atual)
        self.salvar()
        return self.clientes[cod]

    def remover(self, codigo: str) -> bool:
        from quiron.servicos.planejamento.ficha import codigo as normalizar

        ok = self.clientes.pop(normalizar(codigo), None) is not None
        if ok:
            self.salvar()
        return ok

    def buscar(self, termo: str) -> list[ClienteReal]:
        t = termo.strip().lower()
        return sorted((c for c in self.clientes.values() if t in c.nome.lower() or t in c.codigo.lower()
                       or (re.sub(r"\D", "", t) and re.sub(r"\D", "", t) in re.sub(r"\D", "", c.cpf + c.telefone))),
                      key=lambda c: c.nome)

    def trocar_senha(self, nova: str) -> None:
        _validar_senha(nova)
        self._senha, self._sal = nova, secrets.token_bytes(16)
        self.salvar()


def _validar_senha(senha: str) -> None:
    if len(senha) < 10:
        raise ValueError("use uma senha de pelo menos 10 caracteres (uma frase serve)")


def criar(senha: str) -> Cofre:
    _exigir_offline()
    if existe():
        raise FileExistsError(f"já existe um cofre em {caminho()}")
    _validar_senha(senha)
    c = Cofre(_senha=senha, _sal=secrets.token_bytes(16))
    c.salvar()
    return c


def abrir(senha: str) -> Cofre:
    _exigir_offline()
    if not existe():
        raise FileNotFoundError("ainda não há cofre — crie com: uv run quiron-offline cofre criar")
    bruto = caminho().read_bytes()
    if not bruto.startswith(CABECALHO):
        raise ValueError("arquivo de cofre inválido")
    sal, token = bruto[len(CABECALHO):len(CABECALHO) + 16], bruto[len(CABECALHO) + 16:]
    try:
        dados = json.loads(Fernet(_chave(senha, sal)).decrypt(token))
    except InvalidToken as e:
        raise SenhaErrada("senha errada") from e
    return Cofre({k: ClienteReal(**v) for k, v in dados.items()}, senha, sal)
