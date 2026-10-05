# Quíron offline no seu PC (Windows, 8 GB de RAM)

A versão offline roda **só no seu computador, sem internet**: um modelo de IA local (Ollama), sua biblioteca, as
fichas, tarefas e calculadoras — e o **cofre de clientes reais**, o único lugar onde código CLI-XXX vira nome de verdade.

## O que muda em relação ao Quíron normal
| | Normal (servidor/PC com internet) | Offline |
|---|---|---|
| IA | Gemini/Groq (nuvem grátis) | modelo local qwen2.5 3B (Ollama) — mais simples e mais lento |
| Clientes | só CLI-XXX | CLI-XXX + nome real (cofre criptografado, só neste PC) |
| Mercado | dados ao vivo | último dado guardado, marcado DESATUALIZADO |
| Telegram | sim | não (sem internet) |

Regras que continuam valendo: o agente e os relatórios usam só o código CLI-XXX; o nome real aparece apenas na tela
**CLI** do Terminal local. O cofre **não abre** se houver modelo de nuvem configurado e **não abre** pelo Tailscale.

## Instalar (uma vez, com internet — ~15 minutos)
1. Rode o **Abrir Quiron.bat** normal (ele atualiza o Quíron e cria o atalho **Quiron - Offline** na Área de Trabalho).
2. Instale o **Ollama**: <https://ollama.com/download> → Windows → instalar (ele fica na bandeja do relógio).
3. Abra o **Prompt de Comando** e baixe o modelo (1,9 GB): `ollama pull qwen2.5:3b`
   - Lento demais no seu PC? Tente `ollama pull llama3.2:3b` e troque o `modelo` em `config/offline.yaml`.
4. Biblioteca: se seus livros já foram processados neste PC, nada a fazer. Se o processamento pesado foi no servidor,
   copie para cá com: `uv run quiron-offline baixar https://<endereço-do-servidor>.ts.net` (pede a senha do Terminal).
5. Crie o cofre: dois cliques em **Quiron - Offline**, comando **CLI** e defina uma senha longa (uma frase).
   **Sem a senha não há como recuperar os nomes** — guarde num gerenciador de senhas.

## Usar
- Dois cliques em **Quiron - Offline**. Ele confere tudo (✅/❌) e abre o Terminal com o selo **OFFLINE**.
- **CLI** — destranque o cofre, cadastre/consulte clientes reais (nome, telefone, e-mail, cidade). Clicar no cliente
  mostra o dossiê dele (ficha, carteira, vencimentos, reuniões, tarefas). O cofre fecha sozinho após 15 minutos.
- **BIB duration** — busca nos seus livros. **CHAT** — o Quíron com o modelo local (biblioteca, fichas, tarefas,
  calculadoras). Respostas levam de 10 s a 1 min no CPU.
- Linha de comando: `uv run quiron-offline cofre listar | adicionar CLI-012 "Nome" | remover CLI-012 | trocar-senha`.

## Memória (8 GB)
O modelo usa ~2,5 GB; o Terminal e os 5 servidores leves, ~0,8 GB. Feche o navegador pesado/jogos se ficar lento.
`uv run quiron-offline verificar` mostra a memória livre.

## Segurança e LGPD
- Cofre: `cofre/clientes.cofre`, criptografado (Scrypt + AES/Fernet). Não vai para o GitHub nem para o pacote.
- `/esquecer CLI-012` apaga os dados de trabalho; para tirar também o nome do cofre: `quiron-offline cofre remover CLI-012`.
- Faça cópia do arquivo do cofre num pendrive guardado (ele continua criptografado).
