# Hospedagem — decidida na Fase 5 (o kit é portátil)

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
