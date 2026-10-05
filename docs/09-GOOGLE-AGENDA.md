# Conectar o Quíron ao seu Google Agenda (uma vez só, ~10 minutos)

O Quíron usa a **API oficial e gratuita** do Google Agenda. Quem autoriza é você, na sua conta Google; o Quíron nunca
vê sua senha. A permissão é só para **eventos da agenda** (nada de Gmail, Drive ou contatos). Dá para revogar quando
quiser em <https://myaccount.google.com/permissions>.

## Parte 1 — Criar a "credencial do app" no Google Cloud (grátis, sem cartão)
1. Entre em <https://console.cloud.google.com/> com a sua conta Google pessoal (a da agenda que você usa).
2. No topo, clique no seletor de projeto → **Novo projeto** → nome: `Quiron` → **Criar**. Confira que o projeto
   **Quiron** ficou selecionado no topo.
3. Menu ☰ → **APIs e serviços** → **Biblioteca** → procure **Google Calendar API** → **Ativar**.
4. Menu ☰ → **APIs e serviços** → **Tela de consentimento OAuth** (às vezes aparece como **Google Auth Platform**):
   - **Começar** → Nome do app: `Quiron` · E-mail de suporte: o seu → **Próxima**.
   - Público: **Externo** → **Próxima** → Dados de contato: o seu e-mail → aceite a política → **Criar**.
   - Em **Público-alvo** (ou "Público"), clique em **Publicar app** → **Confirmar** (fica "Em produção").
     *Por quê:* em modo "Teste" o Google derruba a autorização a cada 7 dias. Como o app é só seu, não precisa da
     verificação do Google; você só vai ver um aviso na hora de autorizar (passo 3 da Parte 2).
5. Menu ☰ → **APIs e serviços** → **Credenciais** (ou **Clientes**) → **Criar credenciais** → **ID do cliente OAuth**:
   - Tipo de aplicativo: **App para computador** · Nome: `Quiron PC` → **Criar**.
   - Na janela que abrir, clique em **Baixar JSON**.
6. Renomeie o arquivo baixado para **`google_oauth.json`** e coloque na pasta **`segredos`** do Quíron
   (ex.: `C:\Users\PC\meu-agente-\segredos\google_oauth.json`). Esse arquivo **não** vai para o GitHub.

## Parte 2 — Autorizar
1. Dê dois cliques em **`Quiron Google Agenda.bat`** (na pasta do Quíron).
2. O navegador abre na tela do Google: escolha a sua conta.
3. Vai aparecer **"O Google não verificou este app"**: clique em **Avançado** → **Acessar Quiron (não seguro)**.
   (É o seu próprio app; o aviso aparece porque ele não passou pela verificação pública do Google.)
4. Marque a permissão de **ver e editar eventos** e clique em **Continuar**.
5. A página mostra "Pronto!". Na janela preta aparece **"Conexão OK. Hoje há N evento(s)"**. Feito.

O token fica em `segredos\google_token.json` e se renova sozinho.

## No servidor (mini PC, sem tela) — quando o Quíron for para lá
- Mais fácil: copie os dois arquivos `segredos\google_oauth.json` e `segredos\google_token.json` do PC para a pasta
  `segredos` do servidor (o `deploy/migrar.sh` já leva a pasta `segredos`).
- Ou autorize direto no servidor: `docker compose run --rm agente quiron-google autorizar --sem-navegador` — abra o link
  no celular, permita, e cole de volta o endereço da página que não abriu (começa com `http://127.0.0.1`).

## Usando
- `/hoje` mostra seus compromissos do dia junto com as tarefas.
- `/evento quinta às 15h reunião com CLI-012 por 1h30` cria o evento na sua agenda.
- `/revisao` (e a revisão automática de domingo às 18h) mostra a próxima semana.
- Agenda diferente da principal: no `.env`, `GOOGLE_AGENDA_ID=<id da agenda>` (em Configurações da agenda → "ID da agenda").

## Deu erro?
- "falta a credencial": o arquivo não está em `segredos\google_oauth.json` (confira o nome, sem `.json.json`).
- "a autorização expirou ou foi revogada": o app ficou em modo Teste (Parte 1, passo 4) ou você revogou o acesso.
  Publique o app e rode o `Quiron Google Agenda.bat` de novo.
- "access_denied": na tela do Google você não marcou a permissão da agenda. Rode de novo e marque.
