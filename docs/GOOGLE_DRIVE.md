# Conectar o Google Drive ao Omnivault

Guia passo a passo para criar o "app" no Google Cloud (gratuito) que permite ao Omnivault
**ler** suas pastas de HQs no Google Drive. Faz-se **uma vez só** e leva uns 10 minutos.

> **Precisa mesmo?** Só se suas HQs estão no Google Drive. Pastas do computador
> funcionam sem nada disso (veja o [README](../README.md#6-configuração-inicial-primeiro-uso)).

---

## Sumário

1. [Como funciona (em 30 segundos)](#1-como-funciona-em-30-segundos)
2. [Criar o projeto](#2-criar-o-projeto)
3. [Ativar a Google Drive API](#3-ativar-a-google-drive-api)
4. [Configurar a tela de consentimento](#4-configurar-a-tela-de-consentimento)
5. [Escolher quem pode usar (teste × publicado)](#5-escolher-quem-pode-usar-teste--publicado)
6. [Criar a credencial (ID do cliente OAuth)](#6-criar-a-credencial-id-do-cliente-oauth)
7. [Colocar o `credentials.json` no Omnivault](#7-colocar-o-credentialsjson-no-omnivault)
8. [Conectar a conta no app](#8-conectar-a-conta-no-app)
9. [Adicionar pastas do Drive](#9-adicionar-pastas-do-drive)
10. [Problemas comuns](#10-problemas-comuns)
11. [Segurança e como revogar](#11-segurança-e-como-revogar)

---

## 1. Como funciona (em 30 segundos)

- O Google não deixa um programa ler o seu Drive sem autorização. Por isso você cria um
  **projeto seu** no Google Cloud e gera um arquivo de credencial (`credentials.json`).
- O Omnivault usa esse arquivo para abrir a tela de login do Google. Você autoriza **só a
  leitura** (escopo `drive.readonly`); o app nunca altera nem apaga arquivos.
- Depois do login, o Google entrega um token que fica em `credentials/token.json`, no seu PC.
  Ele é renovado sozinho; você não precisa logar de novo.

Nada disso sai da sua máquina, e os dois arquivos estão no `.gitignore`.

---

## 2. Criar o projeto

1. Acesse <https://console.cloud.google.com> e entre com a **conta Google onde estão as HQs**.
   - Primeira vez no Google Cloud? Aceite os termos. **Não é preciso** cadastrar cartão nem
     ativar teste grátis: a Drive API é gratuita para este uso.
2. No topo da página, clique no **seletor de projetos** (ao lado do logo "Google Cloud").
3. Clique em **Novo projeto**.
4. Nome do projeto: `Omnivault` (pode ser qualquer um). Organização/local: deixe como está.
5. Clique em **Criar**, espere a notificação e **selecione o projeto** no seletor.

> Confira sempre no topo da página que o projeto `Omnivault` está selecionado antes de
> seguir; é o erro mais comum.

---

## 3. Ativar a Google Drive API

1. Menu ☰ → **APIs e serviços** → **Biblioteca**
   (ou busque "Google Drive API" na barra de pesquisa do console).
2. Clique em **Google Drive API** → **Ativar**.

---

## 4. Configurar a tela de consentimento

É a tela que aparece quando você faz login ("O app Omnivault quer acessar…").

> O Google mudou essa área recentemente. Em consoles novos ela se chama
> **Google Auth Platform** (seções *Visão geral, Branding, Público-alvo, Clientes, Acesso a
> dados*); em consoles antigos, **Tela de permissão OAuth**. Os passos são os mesmos.

1. Menu ☰ → **APIs e serviços** → **Tela de permissão OAuth**
   (ou **Google Auth Platform** → **Primeiros passos / Get started**).
2. **Informações do app:**
   - **Nome do app:** `Omnivault`
   - **E-mail de suporte do usuário:** o seu e-mail
3. **Público-alvo / Tipo de usuário:** escolha **Externo** (External).
   - "Interno" só aparece para contas Google Workspace de empresa; não use.
4. **Dados de contato:** o seu e-mail.
5. Aceite a política de dados do Google → **Criar** / **Concluir**.
6. **Escopos / Acesso a dados:** pode **pular**. O Omnivault pede o escopo
   `.../auth/drive.readonly` sozinho na hora do login.

---

## 5. Escolher quem pode usar (teste × publicado)

O app nasce em modo **Teste** (Testing). Você tem duas opções:

| | **Teste** (padrão) | **Em produção** (publicado) |
|---|---|---|
| Quem consegue logar | só os e-mails cadastrados como **usuários de teste** | qualquer conta Google (até 100 sem verificação) |
| Validade do login | **expira a cada 7 dias**: precisa reconectar | não expira (renovação automática) |
| Aviso no login | "O Google não verificou este app" | o mesmo aviso |
| Verificação do Google | não precisa | não precisa para uso pessoal |

**Recomendado: publicar**, para não ter que reconectar toda semana.

**Opção A, manter em teste:**
1. **Público-alvo** (ou *Tela de permissão OAuth*) → **Usuários de teste** → **+ Adicionar usuários**.
2. Adicione **o seu e-mail Google** (e de quem mais for usar) → **Salvar**.
   ⚠️ Sem isso o login falha com `403: access_denied`.

**Opção B, publicar (recomendado):**
1. **Público-alvo** → **Status de publicação: Teste** → **Publicar app** → **Confirmar**.
2. O status vira **Em produção**. Não envie para verificação; não é necessário.

> O aviso "O Google não verificou este app" continua aparecendo nos dois casos. Ele é
> esperado: o app é seu, pessoal, e o Google só verifica apps distribuídos ao público.

---

## 6. Criar a credencial (ID do cliente OAuth)

1. Menu ☰ → **APIs e serviços** → **Credenciais** → **+ Criar credenciais** →
   **ID do cliente OAuth**
   (ou **Google Auth Platform** → **Clientes** → **+ Criar cliente**).
2. **Tipo de aplicativo:** **App para computador** (*Desktop app*).
   ⚠️ Tem que ser **Desktop**. Com "Aplicativo da Web" o login dá `redirect_uri_mismatch`.
3. **Nome:** `Omnivault Desktop` → **Criar**.
4. Na janela que abre, clique em **Fazer download do JSON**.
   - Fechou sem baixar? Na lista de clientes/credenciais, clique no ícone de **download ⬇**
     ao lado de `Omnivault Desktop`.
   - Em consoles novos, a **chave secreta só aparece na criação**; se perdeu o JSON, crie um
     cliente novo e apague o antigo.

---

## 7. Colocar o `credentials.json` no Omnivault

1. Renomeie o arquivo baixado (algo como `client_secret_1234-abc.apps.googleusercontent.com.json`)
   para **`credentials.json`**.
   - No Windows, se as extensões estiverem ocultas, cuidado para não virar
     `credentials.json.json` (Explorador → **Exibir** → marque **Extensões de nomes de arquivos**).
2. Mova-o para a pasta `credentials/` do projeto, ao lado do `LEIA-ME.txt`:
   ```
   omnivault/
   └── credentials/
       ├── LEIA-ME.txt
       └── credentials.json   ← aqui
   ```
3. Não precisa reiniciar o servidor: o arquivo é lido na hora do login.

O conteúdo deve começar com `{"installed":{"client_id":...` (a palavra `installed` indica
credencial Desktop).

---

## 8. Conectar a conta no app

> ⚠️ Faça este passo **no navegador do próprio PC** onde o Omnivault roda
> (`http://localhost:8000`). O Google devolve o login para `localhost`, que no iPad/celular
> aponta para o próprio aparelho e não funciona. Depois de conectado no PC, o Drive
> funciona em todos os aparelhos.

1. Abra o Omnivault no PC.
2. Vá em **Configurações → Google Drive → Conectar**
   (ou clique em **Drive offline · Conectar** no topo da tela Início).
3. Escolha a conta Google.
4. Aparece **"O Google não verificou este app"** → clique em **Avançado** →
   **Acessar Omnivault (não seguro)**.
5. Marque a permissão **"Ver e baixar todos os seus arquivos do Google Drive"** (leitura) →
   **Continuar**.
6. Você volta ao Omnivault com o Drive **conectado**. O token fica em `credentials/token.json`.

---

## 9. Adicionar pastas do Drive

1. Abra a pasta das HQs no Drive pelo navegador. A URL fica assim:
   ```
   https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz
                                          └──────────── ID ────────────┘
   ```
2. No Omnivault: **Pastas** (topo) → seção **Adicionar** → cole a **URL inteira** (ou só o ID)
   no campo **Link ou ID do Google Drive**.
3. (Opcional) dê um **Nome** (ex.: `Marvel`) → **+ Drive**.
4. A pasta aparece em **Bibliotecas**. Repita para quantas quiser.

Funciona com pastas do **Meu Drive** e pastas **compartilhadas com você**. Subpastas são
navegáveis normalmente; HQs sem extensão no nome (ex.: `Capítulo 01`) são detectadas pelo tipo.

---

## 10. Problemas comuns

| Sintoma | Causa provável → solução |
|---|---|
| Página "Falta o credentials.json" ao conectar | O arquivo não está em `credentials/credentials.json` (ou ficou `.json.json`). Veja o passo 7. |
| `Erro 403: access_denied` | App em **Teste** e seu e-mail não está em **Usuários de teste**, ou você logou com outra conta. Passo 5. |
| `Erro 400: redirect_uri_mismatch` | A credencial não é **Desktop**. Crie um cliente do tipo *App para computador* (passo 6). |
| Login abre no iPad e dá erro de "não foi possível conectar" | O login precisa ser feito no **PC** (passo 8). |
| Drive desconecta sozinho a cada 7 dias | App em modo **Teste**. Publique (passo 5, opção B) e reconecte uma vez. |
| `Google Drive API has not been used in project…` | A API não foi ativada no projeto selecionado (passo 3). |
| "Nenhuma HQ encontrada" numa pasta | A conta conectada não tem acesso à pasta, ou a pasta não tem HQs nem subpastas com HQs. |
| Trocar de conta Google | **Configurações → Google Drive → Desconectar** e conectar de novo. |

O terminal do Omnivault mostra mensagens `[auth]` com o motivo quando a renovação do token falha.

---

## 11. Segurança e como revogar

- O Omnivault pede **somente leitura** (`drive.readonly`).
- `credentials.json` identifica o **seu** app; `token.json` dá acesso de leitura ao **seu**
  Drive. Trate os dois como senha: **não compartilhe e não suba no git** (já estão no
  `.gitignore`).
- Para cortar o acesso a qualquer momento:
  - no app: **Configurações → Google Drive → Desconectar** (apaga o `token.json`);
  - na conta Google: <https://myaccount.google.com/permissions> → **Omnivault** →
    **Remover acesso**.
- Vazou o `credentials.json`? No Cloud Console, apague o cliente OAuth e crie outro.
