<p align="center">
  <img src="static/emblem.png" width="110" alt="Omnivault">
</p>

<h1 align="center">Omnivault</h1>

<p align="center">
  Sua biblioteca pessoal de HQs e mangás: leia <b>CBZ, CBR, CB7, PDF, ZIP e RAR</b>
  direto do <b>Google Drive</b> ou de <b>pastas do computador</b>, no PC, no iPad e no
  celular, pela mesma rede Wi-Fi.
</p>

<p align="center">
  Self-hosted · sem banco de dados · sem build · FastAPI + HTML/JS puro · PWA
</p>

<p align="center">
  <a href="https://github.com/hassan-hamdan99/omnivault/actions/workflows/tests.yml"><img src="https://github.com/hassan-hamdan99/omnivault/actions/workflows/tests.yml/badge.svg" alt="Testes"></a>
  <a href="https://github.com/hassan-hamdan99/omnivault/releases"><img src="https://img.shields.io/github/v/release/hassan-hamdan99/omnivault" alt="Versão"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue" alt="Python 3.11–3.13">
  <img src="https://img.shields.io/badge/licen%C3%A7a-MIT-green" alt="Licença MIT">
</p>

---

## Índice

1. [O que é o Omnivault](#1-o-que-é-o-omnivault)
2. [Funcionalidades](#2-funcionalidades)
3. [Requisitos](#3-requisitos)
4. [Instalação](#4-instalação)
5. [Como iniciar e encerrar](#5-como-iniciar-e-encerrar)
6. [Configuração inicial (primeiro uso)](#6-configuração-inicial-primeiro-uso)
7. [Google Drive](#7-google-drive)
8. [Usar no iPad/celular](#8-usar-no-ipadcelular)
9. [Como usar a interface](#9-como-usar-a-interface)
10. [Variáveis de ambiente (`.env`)](#10-variáveis-de-ambiente-env)
11. [Backup, atualização e desinstalação](#11-backup-atualização-e-desinstalação)
12. [Solução de problemas](#12-solução-de-problemas)
13. [Privacidade e segurança](#13-privacidade-e-segurança)
14. [Estrutura do projeto e documentação técnica](#14-estrutura-do-projeto-e-documentação-técnica)
15. [Testes](#15-testes) · [Licença](#16-licença)

---

## 1. O que é o Omnivault

O Omnivault é um **servidor local**: um programa que roda no seu PC e serve uma interface
web de biblioteca e leitor de quadrinhos. Ele **não copia nem move** seus arquivos. Lê as
HQs de onde já estão (uma pasta no disco e/ou pastas no Google Drive), gera as capas,
organiza e abre tudo num leitor próprio.

```
 ┌──────────── PC (servidor) ────────────┐        mesma Wi-Fi
 │  Omnivault  ←→  pastas locais         │  ◄──────────────────►  iPad / celular
 │      ↑                                 │                         (navegador ou
 │      └──→  Google Drive (só leitura)   │                          app na tela inicial)
 └────────────────────────────────────────┘
```

Você abre no navegador do **PC** (`http://localhost:8000`) e no **iPad/celular**
(`http://IP-do-PC:8000`). O progresso fica salvo no PC: começa a ler num aparelho e
continua no outro, na página exata.

> **Ajuda dentro do app:** o botão **?** no topo (ou a tecla `?` no PC) abre um guia
> rápido de uso, separado por assunto.

---

## 2. Funcionalidades

**Biblioteca**
- **Duas fontes**: Google Drive (somente leitura, via OAuth) e pastas locais.
- **Formatos**: `.cbz`, `.cbr`, `.cb7`, `.pdf`, `.zip`, `.rar`, inclusive arquivos do Drive
  **sem extensão no nome** (detectados pelo tipo/conteúdo).
- **Capas automáticas** extraídas dos próprios arquivos, sem baixar tudo (CBZ por leitura
  parcial, PDF pelos primeiros MB). A capa de pasta é editável (recorte 2:3).
- **Ordenar** (A→Z, data, tamanho, nota), **filtrar** (não lidas, em andamento, na fila,
  com nota, baixadas), **agrupar séries** e **seleção em lote**.
- **Faixa da série** ao entrar numa pasta: progresso, nota média e "Continuar série".
- **Busca** por nome em todo o Drive e nas pastas locais (`/` ou `Ctrl+K` no PC).

**Leitura**
- **Leitor completo**: zoom (rodinha, pinça, duplo clique/toque), página que acompanha o
  dedo, teclado, **modo mangá** (direita→esquerda), **página dupla**, brilho/contraste,
  tela cheia e barra de progresso arrastável.
- **Retomada sincronizada** entre aparelhos ("Retomando da pág. X · Do início").
- **Fim da HQ**: nota de 1 a 5 estrelas e atalho para o **próximo volume** da pasta.

**Organização**
- **Perfis** estilo Netflix ("Quem está lendo?"): cada pessoa tem seu andamento, lidas,
  fila, listas, notas e atividade. A biblioteca é compartilhada.
- **Início** com "Continuar lendo", prateleiras (fila, próximo da série, favoritas, lidos
  recentemente) e **mapa de atividade**.
- **Andamento**, **Lidas** (agrupadas por mês), **Fila**, **Listas** (coleções) e
  **marcar pasta inteira como lida**.
- **Backup**: exportar/importar progresso, fila e listas (JSON).

**Técnico**
- **PWA** instalável na tela de início, com download de HQs para ler offline (ver
  limitação em [§8](#8-usar-no-ipadcelular)).
- **Cache inteligente**: capas permanentes, arquivos do Drive em cache LRU (padrão 15 GB)
  e páginas pré-geradas em segundo plano.

---

## 3. Requisitos

| Componente | Observação |
|---|---|
| **Windows 10/11, Linux ou macOS** | o PC que guarda/acessa as HQs e fica ligado enquanto você lê |
| **Python 3.11, 3.12 ou 3.13** | testado automaticamente nas três versões (Windows e Linux; macOS com 3.13) |
| **7-Zip** (Windows) ou **p7zip/unrar** (Linux/macOS) | só para abrir **CBR/RAR/CB7** |
| **Conta Google** + projeto gratuito no Google Cloud | só se for usar o **Google Drive** ([guia](docs/GOOGLE_DRIVE.md)) |
| Node / npm / banco de dados | **não precisa** |

Espaço em disco: o programa ocupa poucos MB. O cache de HQs do Drive cresce até o limite
(`CACHE_MAX_GB`, padrão **15 GB**), e as capas ocupam alguns KB cada.

---

## 4. Instalação

### Windows (passo a passo)

1. **Instale o Python** (3.11, 3.12 ou 3.13) em <https://www.python.org/downloads/windows/>
   (*Windows installer 64-bit*).
   - Na primeira tela do instalador, **marque "Add python.exe to PATH"** e clique em
     **Install Now**.
   - Para conferir, abra o **Prompt de Comando** e rode `python --version`; deve aparecer
     `Python 3.1x.x`.
2. **(Só para CBR/RAR)** instale o **[7-Zip](https://www.7-zip.org)**, versão 64-bit, no
   local padrão. O Omnivault encontra `C:\Program Files\7-Zip\7z.exe` sozinho (WinRAR
   também serve).
3. **Baixe o Omnivault**, de uma das duas formas:
   - **Com git:**
     ```bat
     git clone https://github.com/hassan-hamdan99/omnivault.git
     ```
   - **Sem git:** na página do repositório, **Code → Download ZIP**, e extraia numa pasta
     fixa (ex.: `C:\Omnivault`). Evite pastas sincronizadas (OneDrive) para os dados.
4. Dê dois cliques em **`setup.bat`**. Ele confere o Python, instala as dependências e
   cria as pastas necessárias.
5. No fim, o `setup.bat` pergunta se você quer um **atalho "Omnivault" na Área de
   Trabalho**, com o ícone do app. Depois é só dar dois cliques nele para iniciar.
   Para criar o atalho mais tarde (ou recriar depois de mover a pasta), rode
   **`criar-atalho.bat`**.

### Linux / macOS

```bash
# Debian/Ubuntu: sudo apt install python3 python3-venv p7zip-full
# macOS (Homebrew): brew install python@3.12 sevenzip
git clone https://github.com/hassan-hamdan99/omnivault.git
cd omnivault
python3 -m venv .venv && source .venv/bin/activate     # recomendado
pip install -r backend/requirements.txt
chmod +x run.sh
```

---

## 5. Como iniciar e encerrar

| Sistema | Iniciar |
|---|---|
| **Windows** | dois cliques no atalho **Omnivault** da Área de Trabalho (ou em `start.bat`) |
| **Linux/macOS** | `./run.sh` (com o venv ativo) ou `cd backend && python3 main.py` |

- Uma janela de terminal abre: **é o servidor**. Deixe-a aberta (pode minimizar)
  enquanto usa o app.
- O navegador abre sozinho em **`http://localhost:8000`** quando o servidor fica pronto.
- **Encerrar:** botão vermelho **Desligar** no topo do app, ou feche o terminal
  (`Ctrl+C`). Com o servidor desligado, nenhum aparelho consegue abrir o app.

---

## 6. Configuração inicial (primeiro uso)

Um roteiro de 5 minutos para deixar tudo pronto.

### Passo 1: seu perfil

Na primeira vez aparece a tela **"Quem está lendo?"** com um perfil chamado **Leitor**.

1. Clique em **Gerenciar perfis** → clique no perfil **Leitor**.
2. Troque o **nome** e escolha um **avatar** pronto, ou envie uma **foto** → **Salvar**.
3. Mora mais gente na casa? Em **Gerenciar perfis**, use **Adicionar perfil** para criar um
   perfil para cada pessoa. Cada um tem seu próprio progresso, fila, listas e notas.
4. Clique em **Concluído** e escolha o seu perfil.

> A tela "Quem está lendo?" aparece toda vez que você abre o app. Para trocar no meio do
> uso, toque no seu nome no **rodapé do menu lateral**.

### Passo 2: adicionar suas HQs

**Pasta do computador** (não precisa de nada do Google):
1. Clique em **Pastas** no topo → seção **Adicionar** → **Local**.
2. Navegue pelas unidades até a **pasta raiz** da coleção (ex.: `D:\HQs`) e clique em
   **Usar**. Opcional: digite um **Nome** antes (ex.: `Marvel`).
3. Repita para outras pastas. Elas aparecem em **Bibliotecas** no menu lateral.

**Pasta do Google Drive:** siga o **[guia do Google Drive](docs/GOOGLE_DRIVE.md)** (feito
uma vez só) e depois cole o link da pasta em **Pastas → Link ou ID do Google Drive → + Drive**.

> **Como organizar:** uma pasta por série/coleção, com os volumes dentro
> (`Marvel/Vingadores/Vingadores 001.cbz`). Assim a "faixa da série", o "próximo volume" e
> o "A seguir na série" funcionam melhor. Nomes com numeração (`001`, `002`) ordenam
> corretamente.

A primeira visita a uma pasta grande pode levar alguns segundos enquanto as capas são
geradas. Para adiantar, use **Configurações → Pré-gerar capas**.

### Passo 3: abrir no iPad/celular

1. No PC, role a tela **Início** até o rodapé: aparece **"Abrir em outro aparelho"** com o
   endereço (algo como `http://192.168.0.10:8000`) e um botão de copiar.
2. No iPad/celular, conectado à **mesma Wi-Fi**, abra esse endereço no navegador.
3. **Windows:** na primeira vez que o servidor sobe, o Firewall do Windows pergunta se o
   Python pode se comunicar na rede. **Permita em "Redes privadas"**. Se não apareceu ou
   você recusou, veja [Solução de problemas](#12-solução-de-problemas).
4. Para virar "app", veja [§8](#8-usar-no-ipadcelular).

### Passo 4: ajustes opcionais

- **Configurações → Baixar fila automaticamente**, por aparelho (ver limitação em §8).
- **Limite do cache** do Drive e outras opções: arquivo `.env` ([§10](#10-variáveis-de-ambiente-env)).
- **IP fixo:** reserve um IP para o PC no roteador (*DHCP reservation*), para o atalho do
  iPad nunca quebrar.

Pronto: abra **Bibliotecas**, toque numa capa e boa leitura. Dúvidas de uso? Botão **?** no
topo do app.

---

## 7. Google Drive

O guia completo, com o caminho de cada clique, problemas comuns e como revogar o acesso,
está em **[docs/GOOGLE_DRIVE.md](docs/GOOGLE_DRIVE.md)**. Resumo:

1. No [Google Cloud Console](https://console.cloud.google.com), crie um projeto e ative a
   **Google Drive API**.
2. Configure a **tela de consentimento** (tipo **Externo**) e **publique o app** (ou
   adicione seu e-mail como usuário de teste; nesse caso o login expira a cada 7 dias).
3. Crie um **ID do cliente OAuth** do tipo **App para computador (Desktop)** e baixe o JSON.
4. Salve-o como **`credentials/credentials.json`**.
5. **No PC**, em **Configurações → Google Drive → Conectar**, faça login e autorize a
   leitura.
6. Adicione pastas colando o link em **Pastas → + Drive**.

---

## 8. Usar no iPad/celular

**Instalar como app (tela de início):**
- **iPad/iPhone (Safari):** abra o endereço do PC → botão **Compartilhar** →
  **Adicionar à Tela de Início**. O app abre em tela cheia, sem barra do navegador.
- **Android (Chrome):** menu ⋮ → **Instalar app** / **Adicionar à tela inicial**.

**Lembre-se:**
- O PC precisa estar **ligado, com o Omnivault rodando**, e os dois na **mesma rede**.
- O login do Google Drive se faz **no PC** (o redirect é `localhost`). Feito uma vez, o
  Drive funciona em todos os aparelhos.
- Se o roteador trocar o IP do PC, o atalho para de abrir: pegue o endereço novo no rodapé
  da Início (no PC) e adicione de novo. O progresso fica salvo no PC; nada se perde.

> **Limitação conhecida, ler offline:** "Baixar no aparelho" usa Service Worker + Cache
> Storage, que os navegadores só liberam em **contexto seguro** (https ou `localhost`).
> Acessando pelo IP da rede (`http://192.168…`), como no iPad, o recurso fica
> indisponível. No próprio PC (localhost) funciona.

---

## 9. Como usar a interface

> O mesmo conteúdo, resumido, está no app: botão **?** do topo.

### Navegação
- **Menu lateral:** Início, Bibliotecas, Andamento, Lidas, Fila, Baixadas, Listas,
  Configurações e o **seu perfil** (toque para trocar). No iPad em pé/celular ele abre
  pelo botão ☰.
- Clique numa pasta para entrar; use a **trilha** (breadcrumb) para voltar.
- **Clique direito** (PC) ou **toque longo** (iPad/celular) numa HQ ou pasta abre o **menu**.
- No PC, parar o mouse sobre uma HQ mostra o **total de páginas** ou o progresso.

### Menu de contexto: HQ
| Opção | Ação |
|---|---|
| Abrir | Abre no leitor |
| Listas ▸ | Adiciona/remove de uma lista |
| Avaliar | Nota de 1 a 5 estrelas |
| Adicionar à Fila / Remover da Fila | "Ler a seguir" |
| Marcar como Lida | Move para "Lidas" |
| Baixar no aparelho | Guarda para ler offline (ver §8) |
| Remover Progresso | Zera a leitura |

### Menu de contexto: pasta
| Opção | Ação |
|---|---|
| Atualizar capa | Regenera a capa automática (busca mais fundo) |
| Alterar capa | Escolhe uma imagem sua |
| Marcar pasta como lida / não lida | Todas as HQs da pasta (recursivo) |
| Baixar pasta no aparelho | Baixa todas para offline |
| Listas ▸ | Adiciona/remove a pasta de uma lista |

### Leitor
| Ação | PC (mouse/teclado) | iPad/celular (toque) |
|---|---|---|
| Próxima página | clique à **direita** · `→` `↓` `Espaço` | toque à direita · arrastar para a esquerda |
| Página anterior | clique à **esquerda** · `←` `↑` | toque à esquerda · arrastar para a direita |
| Mostrar/ocultar barras | clique no **centro** · `F` | toque no centro |
| Zoom | rodinha · duplo clique · `+` `-` | pinça · duplo toque |
| Tirar o zoom | `0` · botão | duplo toque |
| Página dupla | `D` · botão | botão |
| Modo mangá (D→E) | `M` · botão | botão |
| Brilho/contraste | `B` · botão | botão |
| Tela cheia | `T` · botão | botão |
| Voltar à biblioteca | `Esc` · botão | botão |

No toque, a página acompanha o dedo; solte depois de ~¼ da tela (ou com um peteleco) para
virar. A barra de progresso embaixo pode ser arrastada para pular de página.

### Perfis
- **Gerenciar perfis** (na tela "Quem está lendo?") cria, renomeia, troca o avatar (pronto
  ou foto) e exclui.
- Excluir um perfil **não apaga** os dados: eles vão para `data/profiles/_excluidos/`.

### Configurações
- **Google Drive**: conectar/desconectar.
- **Cache**: tamanho usado, **Limpar** e **Pré-gerar capas**.
- **Baixar fila automaticamente** (por aparelho).
- **Backup**: **Exportar** (`.json`) e **Importar** (substitui o estado do perfil atual).

### Atalhos no PC
`?` ajuda · `/` ou `Ctrl+K` pesquisar · `Esc` fechar.

---

## 10. Variáveis de ambiente (`.env`)

Todas são **opcionais**. Para usar, copie `.env.example` para `.env` (na raiz do projeto),
edite e reinicie o servidor.

```env
CACHE_MAX_GB=15     # Tamanho máximo do cache de HQs baixadas do Drive (GB)
HOST=0.0.0.0        # 0.0.0.0 = acessível na rede (PC + iPad); 127.0.0.1 = só esta máquina
PORT=8000           # Porta do servidor (também define o redirect do OAuth)
EXTRACT_WORKERS=4   # Extrações pesadas simultâneas (7-Zip/PyMuPDF); diminua em PCs fracos
# OMNIVAULT_HOME=D:\OmnivaultDados  # onde ficam data/, cache/ e credentials/ (padrão: pasta do projeto)
NO_BROWSER=0        # 1 = não abrir o navegador ao iniciar
# CORS_ORIGINS=     # Origens extras que podem chamar a API (o app NÃO precisa; ver §13)
# OAUTH_REDIRECT=http://localhost:8000/auth/callback  # derivado de PORT por padrão
# DRIVE_FOLDERS=Nome:ID,Nome:ID   # legado: pastas do Drive na 1ª execução
```

> Prefira manter a porta **8000**. Se trocar a `PORT`, o redirect do OAuth passa a ser
> `http://localhost:<PORT>/auth/callback`: reconecte o Drive e, se o Google recusar o
> redirect, confira a credencial no Cloud Console.

---

## 11. Backup, atualização e desinstalação

**O que guardar.** Tudo que é seu fica em três lugares:

| Pasta | Conteúdo | Precisa de backup? |
|---|---|---|
| `data/` | perfis, fotos, progresso, notas, listas, pastas configuradas, capas personalizadas | **sim** |
| `credentials/` | `credentials.json` e `token.json` do Google | sim (ou refaça o guia) |
| `cache/` | capas, páginas e HQs baixadas do Drive | não (é regenerado) |

Copiar a pasta `data/` com o servidor desligado é o backup completo. Para um perfil só, use
**Configurações → Backup → Exportar**.

**Atualizar** (com o servidor desligado):
```bash
git pull                                   # ou baixe o ZIP novo e copie por cima,
pip install -r backend/requirements.txt    # mantendo data/, cache/ e credentials/
```
No iPad, feche e abra o app para pegar a versão nova.

**Desinstalar:** apague a pasta do projeto. Se usou o Drive, revogue o acesso em
<https://myaccount.google.com/permissions>.

---

## 12. Solução de problemas

**`python` não é reconhecido / `setup.bat` diz que o Python não foi encontrado**
→ Reinstale o Python marcando **"Add python.exe to PATH"**, ou reabra o terminal após instalar.

**Erro ao instalar dependências (Pillow/PyMuPDF compilando, `wheel` falhando)**
→ Use Python **3.11, 3.12 ou 3.13** (64-bit). Versões mais novas podem ainda não ter
pacote pronto dessas bibliotecas.

**O iPad/celular não abre o endereço**
→ Confira, nessa ordem:
1. PC e iPad estão na **mesma Wi-Fi** (não na rede de convidados).
2. O servidor está rodando e `HOST` é `0.0.0.0`.
3. **Firewall do Windows:** *Segurança do Windows → Firewall e proteção de rede → Permitir
   um aplicativo pelo firewall → Alterar configurações*, e marque **Python** em
   **Privada**. A rede Wi-Fi do PC deve estar como **Privada** (Configurações → Rede →
   propriedades da Wi-Fi).
4. O IP do PC mudou: veja o rodapé da Início no PC.

**CBR não abre / capa de CBR não aparece**
→ Instale o **[7-Zip](https://www.7-zip.org)** (Windows) ou `p7zip`/`unrar`. O terminal
avisa na inicialização se não achar nenhuma ferramenta RAR.

**Capa de pasta errada ou faltando**
→ Botão direito / toque longo na pasta → **Atualizar capa**; se persistir, **Alterar capa**.

**Mudanças na interface não aparecem (após atualizar)**
→ O app fica em cache no navegador. No PC, `Ctrl+Shift+R`; no iPad, feche e abra o app.

**A porta 8000 está em uso**
→ Outro Omnivault (ou programa) já está rodando. Feche-o, ou troque a `PORT` no `.env`
(veja a observação sobre o OAuth em §10).

**Google Drive:** erros de login (`403 access_denied`, `redirect_uri_mismatch`,
desconexão semanal) estão em [docs/GOOGLE_DRIVE.md → Problemas comuns](docs/GOOGLE_DRIVE.md#10-problemas-comuns).

---

## 13. Privacidade e segurança

- Acesso ao Google Drive **somente leitura** (escopo `drive.readonly`). O Omnivault nunca
  altera nem apaga seus arquivos, locais ou do Drive.
- Credenciais, token, estado de leitura e cache ficam **só na sua máquina**. `.env`,
  `credentials/credentials.json`, `credentials/token.json`, `data/` e `cache/` estão no
  `.gitignore`: **nunca suba esses arquivos**.
- **Sites de terceiros não acessam a API:** o servidor recusa chamadas vindas de outra
  origem e não envia cabeçalhos CORS. Um site aberto no seu navegador não consegue ler suas
  pastas, seu histórico nem desligar o servidor. (O app em si, no PC ou no iPad, é sempre
  mesma origem e não é afetado.)
- **Não há login nem senha** no app: qualquer aparelho na sua rede consegue abrir. Perfis
  separam dados, não protegem acesso. Use em rede de confiança (casa), **não exponha a
  porta à internet** (nada de redirecionamento de porta no roteador) e, em rede
  compartilhada, use `HOST=127.0.0.1`.
- Toda gravação de estado é **atômica e com travas**: não há corrupção mesmo com PC e iPad
  gravando ao mesmo tempo.

---

## 14. Estrutura do projeto e documentação técnica

```
start.bat           inicia o servidor (Windows) · setup.bat instala · criar-atalho.bat cria o atalho
run.sh              inicia o servidor (Linux/macOS)
backend/            servidor FastAPI (main.py) + Drive, arquivos locais, extração, perfis, estado
static/             index.html (biblioteca), reader.html (leitor), sw.js, manifest, fontes, ícones
docs/               guias (Google Drive)
tests/              testes da API e da extração (pytest; rodam em CI no GitHub Actions)
credentials/        credentials.json + token.json (seus; ignorados pelo git)
data/               configuração, perfis e estado de leitura (gerado; ignorado pelo git)
cache/              capas, páginas e HQs do Drive (gerado; ignorado pelo git)
```

Arquitetura, endpoints, formatos de dados e decisões de design:
[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md).

---

## 15. Testes

```bash
pip install -r backend/requirements.txt -r requirements-dev.txt
pytest tests -q
```

Os testes criam uma instalação temporária isolada (`OMNIVAULT_HOME`) com uma biblioteca
de exemplo (CBZ, PDF e CB7, se houver 7-Zip): **nunca tocam** em `data/`, `cache/` ou
`credentials/`. A cada push, o GitHub Actions roda tudo em Windows e Linux com
Python 3.11–3.13 (e no macOS com 3.13) e ainda sobe o servidor de verdade (pelo `run.sh` no Linux/macOS).

Histórico de versões: [CHANGELOG.md](CHANGELOG.md).

## 16. Licença

[MIT](LICENSE). As fontes em `static/fonts/` (Syne e Karla) são distribuídas sob a
SIL Open Font License.
