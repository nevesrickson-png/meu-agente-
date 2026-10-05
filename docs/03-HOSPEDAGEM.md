# Hospedagem — decidida na Fase 5 (o kit é portátil)

> **Decisão do Rickson (04/10/2026): custo mínimo, em três etapas.**
> 1. **Agora: no seu PC Windows** — atalho **Quiron** (+ CONFIGURAÇÕES → Início automático). Custo zero; funciona
>    enquanto o PC estiver ligado (briefing das 7h30 só chega com o PC ligado).
> 2. **Depois: mini PC em casa** (Linux, 24h) — mesmos scripts de `deploy/`, passo a passo abaixo.
> 3. **Futuro, se valer a pena: VPS** — `deploy/migrar.sh` leva tudo do mini PC para a VPS em menos de 1 hora.
>
> Regra de ouro: **o bot só pode rodar em UM lugar por vez** (o Telegram recusa duas cópias com o mesmo token).
> Ao mudar de etapa, desligue a anterior.

## Etapa 1 — no seu PC (Windows)
1. As chaves ficam na tela de **Configurações** (aba CONFIGURAÇÕES do Quíron; abre sozinha na 1ª vez): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS=7592218870` (o número,
   não o @usuário), `GEMINI_API_KEY` e `GROQ_API_KEY`.
2. Dois cliques em **`Abrir Quiron.bat`** (ou no atalho **Quiron** da Área de Trabalho): atualiza e abre o Quíron (Terminal, Acervo, Configurações e o Telegram). Quando o selo mostrar "● Telegram ligado", mande uma mensagem ao bot.
   Se cair, ele religa sozinho em 30 s. Fechar a janela desliga.
3. Opcional: CONFIGURAÇÕES → Início automático → **Ligar com o Windows** → liga sozinho ao entrar no Windows e impede
   o PC de dormir na tomada. O mesmo botão desliga.
4. Consumo: ~300–500 MB de RAM com os servidores de ferramentas; cabe nos 8 GB.

## Etapa 2 — mini PC em casa (passo a passo)
**Que máquina:** mini PC usado ou novo com processador Intel N100/N150 (ou similar), **8 GB de RAM no mínimo
(16 GB ideal)**, SSD de 256 GB+. Consome pouca energia (≈ 6–15 W, poucos reais por mês).
1. Grave o **Ubuntu Server 24.04 LTS** num pendrive (Rufus no Windows) e instale no mini PC. Na instalação, marque
   **"Install OpenSSH server"**. Use cabo de rede (mais estável que Wi‑Fi).
2. Na BIOS, ative **"Restore on AC Power Loss" = Power On** (religa sozinho depois de queda de energia).
3. No seu PC, gere uma chave SSH (PowerShell: `ssh-keygen -t ed25519`) e copie o conteúdo de `~/.ssh/id_ed25519.pub`.
4. No mini PC: `git clone <repositório> && sudo bash meu-agente-/deploy/preparar_host.sh "ssh-ed25519 AAAA..."`
5. `sudo tailscale up` → entre com a sua conta Tailscale (instale o Tailscale também no PC e no celular).
6. Entre como `quiron` (`ssh quiron@<nome-tailscale>`), clone em `~/quiron` e rode `bash deploy/instalar.sh`
   (1ª vez cria o `.env` para você preencher, com `TERMINAL_SENHA`; depois rode de novo).
7. **Desligue o bot no PC** (feche a janela e remova o início automático). Teste com o PC desligado.
8. Leve o que já existe no PC (conversas, memória, biblioteca): copie as pastas `dados/` e `biblioteca/` para
   `~/quiron/` no mini PC (WinSCP ou `scp -r`), antes do passo 6 ou com `docker compose restart` depois.

## Etapa 3 — VPS (futuro)
Mesma coisa da etapa 2 na VPS (passos 3 a 6), depois `bash deploy/migrar.sh quiron@<vps>` a partir do mini PC.

Nas Fases 0 a 4 tudo roda no seu PC. O host 24h só entra na Fase 5, junto com a escolha do runtime.

O Quíron roda em qualquer máquina Linux com Docker. Você pode começar num lugar e migrar depois em menos de 1 hora.

## Opções
| Opção | Custo | Prós | Contras |
|---|---|---|---|
| **Oracle Cloud Always Free** (ARM, até 4 núcleos / 24 GB) | R$ 0 | Muito potente, 24h, sem conta de luz | Instâncias ociosas podem ser recuperadas; criação às vezes falha por falta de capacidade |
| **Oracle Pay As You Go** (usando só recursos gratuitos) | R$ 0 se ficar no gratuito | Mesma máquina, menos risco de recuperação por ociosidade | Exige atenção: algo criado fora do gratuito é cobrado. Configure alerta de orçamento |
| **Mini PC em casa** (usado, Linux) | algumas centenas de reais + energia | Totalmente seu, sem risco de exclusão | Depende de energia/internet de casa; menos RAM que a Oracle, em geral |
| **WSL2 no seu PC** (temporário) | R$ 0 | Bom para testar no início | 8 GB é apertado; só funciona com o PC ligado |
Confirme as regras atuais da Oracle antes de decidir (políticas de recuperação e limites mudam).

## Sugestão prática enquanto você decide
Comece pela **Oracle Always Free como laboratório**: é grátis e potente, e a portabilidade elimina o risco de perda.
Se um dia a máquina for recuperada, você restaura o backup em outro host.

## Passo a passo genérico (vale para qualquer host)
1. Ubuntu 24.04 (ou Debian) com acesso SSH por chave.
2. `deploy/preparar_host.sh`: atualizações automáticas, usuário `quiron`, sem login por senha/root, firewall só com porta 22,
   fail2ban, Docker, swap, fuso America/Sao_Paulo.
3. Instalar e entrar no Tailscale (no host, no seu PC e no celular).
4. Clonar o repositório privado, criar o `.env`, `docker compose up -d`.
5. Configurar o runtime escolhido (`docs/07-DECISAO-RUNTIME.md`) e conectar os MCP.
6. Ativar o backup noturno (Google Drive) e fazer o simulado de desastre.

## Oracle: detalhes
- Região inicial não pode ser trocada; no Brasil há São Paulo e Vinhedo.
- Shape: VM.Standard.A1.Flex (Ampere/ARM). Se der "Out of capacity", tente mais tarde ou comece menor (2 núcleos / 12 GB).
- Pede cartão para verificação; recursos Always Free não geram cobrança.
- Security List: só a porta 22 aberta. O Terminal passa pelo Tailscale.

## Mini PC: detalhes
- Procure algo com 16 GB de RAM e SSD; instale Ubuntu Server.
- Deixe configurado para religar sozinho após queda de energia (opção na BIOS).

## Desenvolvimento
Com o PC de 8 GB, o ideal é desenvolver **dentro do host** via SSH: o Claude Code também roda no Linux do servidor.
Assim, nada pesado roda no seu Windows.
