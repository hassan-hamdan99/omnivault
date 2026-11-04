# Omnivault — Documentação Técnica

> Referência de arquitetura, módulos, endpoints, formatos de dados e decisões de
> design. Para instalação e uso, veja o [README](README.md).
> **Onde esta doc divergir do código, o código manda.**
>
> **Nota (offline no iPad):** o "Baixar no aparelho" usa Service Worker + Cache Storage,
> que só funcionam em **contexto seguro** (https ou localhost). Acessado no iPad via
> `http://IP-da-rede`, o recurso fica indisponível — é **limitação conhecida e aceita**
> (a tentativa de HTTPS local foi revertida por complexidade).

---

## Índice

1. [Visão geral da arquitetura](#1-visão-geral-da-arquitetura)
2. [Fluxos típicos](#2-fluxos-típicos)
3. [Sistema de IDs](#3-sistema-de-ids)
4. [Detecção de HQ (extensão · mimeType · assinatura)](#4-detecção-de-hq-extensão--mimetype--assinatura)
5. [Backend — `main.py`](#5-backend--mainpy)
6. [Backend — `drive_client.py`](#6-backend--drive_clientpy)
7. [Backend — `local_client.py`](#7-backend--local_clientpy)
8. [Backend — `extractor.py`](#8-backend--extractorpy)
9. [Backend — `config_manager` · `profiles` · `reading_manager` · `storage`](#9-backend--config_manager--profiles--reading_manager--storage)
10. [Persistência: gravação atômica + travas](#10-persistência-gravação-atômica--travas)
11. [Sistema de cache](#11-sistema-de-cache)
12. [Pipeline de capas](#12-pipeline-de-capas)
13. [Contagem de páginas](#13-contagem-de-páginas)
14. [Referência de endpoints](#14-referência-de-endpoints)
15. [Esquemas de dados (JSON)](#15-esquemas-de-dados-json)
16. [Variáveis de ambiente](#16-variáveis-de-ambiente)
17. [Frontend](#17-frontend)
18. [Decisões de design e armadilhas conhecidas](#18-decisões-de-design-e-armadilhas-conhecidas)

---

## 1. Visão geral da arquitetura

```
┌──────────────────────── NAVEGADOR (PC / celular) ────────────────────────┐
│  index.html (SPA)   reader.html (leitor)   sw.js (Service Worker / PWA)   │
│        │  fetch() / XHR                                                    │
└────────┼──────────────────────────────────────────────────────────────────┘
         │ HTTP  (host:porta, padrão 0.0.0.0:8000)
┌────────▼──────────────────────── FastAPI (main.py) ──────────────────────┐
│  Auth · Config de pastas · Listagem · Capas · Páginas · Leitura · Listas  │
│                                                                           │
│  drive_client.py        local_client.py        extractor.py              │
│  (OAuth 2.0 readonly)   (sistema de arquivos)  (CBZ/CBR/PDF; parcial)     │
│                                                                           │
│  config_manager.py   profiles.py           reading_manager.py            │
│  (data/config.json)  (data/profiles.json)  (estado POR perfil)           │
│  storage.py (gravação atômica)             page_counts.json (em main)    │
└───────────────────────────────────────────────────────────────────────────┘
         │ HTTPS                          │ leitura direta do disco
         ▼                                ▼
   Google Drive API v3              Pastas locais
```

- **Backend:** FastAPI + Uvicorn. Endpoints síncronos (rodam no threadpool do
  Starlette → **múltiplas threads**; daí a necessidade de travas na persistência).
- **Frontend:** HTML/CSS/JS puro, sem build nem dependências de runtime
  (fontes Syne/Karla empacotadas localmente em `static/fonts/`).
- **Sem banco de dados:** estado em arquivos JSON (ver §10 e §15).

---

## 2. Fluxos típicos

### Abrir uma pasta
1. Frontend: `GET /api/items?folder_id=<id>` (Drive) ou
   `GET /api/local/items?path=<path>` (local).
2. Resposta `{folders:[...], comics:[...]}`. Cada card de HQ pede a capa
   (`GET /api/comics/<id>/cover`) **só quando entra na viewport** (lazy, via
   `IntersectionObserver`).
3. Capa: servida do cache em disco se existir; senão é gerada (ver §12) e cacheada.

### Escolher perfil
1. `index.html` abre a tela "Quem está lendo?" (`GET /api/profiles`) no início de cada
   sessão (`sessionStorage cs_pf_ok`).
2. O perfil escolhido fica em `localStorage cs_profile`; `profile.js` embrulha o `fetch`
   e injeta o header `X-Profile` em toda chamada `/api/`.
3. Endpoints de estado/listas/stats sem perfil válido respondem **409** e o front reabre
   a escolha.

### Abrir uma HQ
1. `GET /api/comics/<id>/info` → `{name, pages, saved_page}`.
   - Para Drive, baixa o arquivo (cacheado em `cache/comics/`) e conta páginas.
   - Para local, conta por caminho (sem cópia).
2. O leitor retoma na página `max(localStorage, saved_page)`.
3. Cada página: `GET /api/comics/<id>/page/<n>` (cacheada como JPEG em
   `cache/covers/pages_<id>/<n>.jpg`); páginas seguintes são **pré-geradas** em
   background.

### Total de páginas no hover
`GET /api/comics/<id>/pages` — barato: usa cache persistente, contagem por caminho
(local) ou **contagem parcial** no Drive (PDF: 2 MB; CBZ: cauda) sem baixar o arquivo
inteiro (ver §13).

---

## 3. Sistema de IDs

Toda HQ/pasta é referenciada por um `id` string. Há três formas:

| Origem | Formato do `id` | Exemplo |
|---|---|---|
| Arquivo no Drive | ID nativo do Drive | `1AbCdEf...` |
| Arquivo local | `local_` + md5(path)[:16] | `local_f38ef5249adb58b9` |
| Pasta local | o **caminho completo** | `C:\Users\...\HQs\Marvel` |

- IDs locais são mapeados para o caminho real em `data/local_registry.json`
  (`local_client.path_to_id` / `id_to_path`).
- **Detecção local vs Drive** (`local_client.is_local`): começa com `local_`.
- **Detecção de pasta local** (em `main.py`, no endpoint de capa de pasta): o
  `folder_id` começa com `/` ou tem `:` na 2ª posição (caminho Windows `C:\...`).

---

## 4. Detecção de HQ (extensão · mimeType · assinatura)

Nem todo arquivo de HQ tem extensão no nome — no Drive é comum existir
`Capítulo 01` (sem `.pdf`) com `mimeType=application/pdf`. Por isso a detecção é em
**três camadas**:

1. **Por extensão do nome** — `COMIC_EXTS = {cbz, cbr, pdf, zip, rar, cb7}`.
2. **Por mimeType** (Drive) — `COMIC_MIMES` (application/pdf, application/zip,
   application/x-cbr, application/vnd.comicbook+zip, …). Usado quando o nome não tem
   extensão reconhecida. Função `drive_client._is_comic(name, mime)`.
3. **Por assinatura de bytes** (extração) — `extractor._sniff_ext(data)` lê os
   primeiros bytes: `%PDF`→pdf, `Rar!`→cbr, `7z\xBC\xAF`→cb7, `PK`→cbz/zip.
   Usada quando a extensão do nome é desconhecida, em `_effective_ext(filename, data)`.

> **Por que isso importa:** o índice de busca do Drive **não casa** `name contains
> '.cbz'` de forma confiável, e arquivos podem vir como `application/octet-stream`
> ou sem extensão. As três camadas garantem que a HQ apareça **e** abra corretamente
> independentemente do nome.

---

## 5. Backend — `main.py`

Ponto de entrada FastAPI. Destaques:

### Inicialização / configuração
- `load_dotenv()` carrega `.env`.
- **Mesma origem**: sem CORS por padrão; o middleware `_same_origin_only` responde
  **403** a chamadas `/api/*` e `/auth/*` cujo header `Origin` não bate com o `Host`
  (bloqueia sites de terceiros: CSRF em `/api/shutdown`, leitura de `/api/local/browse`,
  etc.). `CORS_ORIGINS` libera origens extras (e liga o `CORSMiddleware` para elas).
- **`OMNIVAULT_HOME`**: raiz de `data/`, `cache/` e `credentials/` (padrão: pasta do
  projeto). Os testes usam uma pasta temporária por aqui. `.env` e `static/` continuam
  na pasta do código.
- `APP_VERSION` (= versão do release, exposta no OpenAPI).
- `_EXTRACT_SEM = Semaphore(EXTRACT_WORKERS)` — limita extrações pesadas
  (7-Zip/PyMuPDF) simultâneas (padrão 4).
- `_INFO_CACHE` — cache em memória de `drive.get_file_info` (evita chamada à API do
  Drive a cada página virada).
- `_PAGE_COUNTS` + `_pc_set()` — cache **persistente** de contagem de páginas em
  `data/page_counts.json`, gravado com `storage.atomic_write` sob lock.
- `_evict()` — eviction LRU do cache `cache/comics` (ver §11). Chamado em background.
- `_pregen()` / `_bg_pregen()` — pré-geração de páginas em threads daemon.

### Acesso unificado a dados
- `_get_info(id)` — Drive (com cache) ou local.
- `_get_data(id, name)` — bytes do arquivo: download do Drive (cacheado) ou leitura
  local. Usado no caminho que precisa do arquivo inteiro.
- `_get_cover(id, name)` — capa: local via caminho, Drive via extração parcial.
- Locais usam funções `_path` do extractor (abrem por caminho, sem ler tudo em
  memória); Drive usa parcial/bytes.

### Onboarding
- `GET /auth/login` sem `credentials.json` (ou com um inválido, ex. cliente do tipo **Web**)
  → devolve uma **página HTML amigável** (`_ONBOARDING_HTML`) com os passos e um formulário
  de envio do JSON, em vez de um traceback.
- `POST /auth/credentials` (multipart `file`) recebe o JSON baixado do Google Cloud, valida
  (`_credentials_problem`: precisa de `installed.client_id`/`client_secret`; `web` é
  recusado com explicação; aceita BOM; máx. 64 KB) e grava com `atomic_write` em
  `credentials/credentials.json`, redirecionando (303) para `/auth/login`. **Só aceita
  cliente local** (`_is_local_client`: 127.0.0.1/::1), além do filtro de mesma origem:
  ninguém na rede troca a credencial.

(Todos os endpoints estão listados em §14.)

---

## 6. Backend — `drive_client.py`

Cliente OAuth 2.0 (escopo `drive.readonly`).

- **Auth:** `get_auth_url` (state aleatório + `prompt=consent` + `access_type=offline`),
  `exchange_code`, `_load_token`/`_save_token` (refresh automático se expirado no load),
  `logout`. `REDIRECT_URI` derivado de `PORT` (ou `OAUTH_REDIRECT`).
- `COMIC_EXTS`, `_EXT_Q` (query por nome, com variantes maiúsculas), `COMIC_MIMES`,
  `_is_comic(name, mime)`.
- **`list_items(folder_id)`** → `{folders, comics}`.
  - Subpastas: query por mimeType de pasta (campos `id, name, modifiedTime`).
  - **HQs:** lista **todos** os arquivos não-pasta/não-atalho e filtra por
    `_is_comic` no cliente (extensão **ou** mimeType). **Não** depende de
    `name contains '.cbz'` (que o índice do Drive não casa de forma confiável).
- **`search_comics(query)`** — busca por nome em todo o Drive, filtrando por
  `_is_comic` no cliente (pega também arquivos sem extensão).
- **`peek_folder_cover(folder_id, depth=5)`** — acha o 1º arquivo de HQ
  (recursivo): query por extensão → fallback por mimeType/sufixo → recursão nas
  subpastas.
- **`download_file(file_id, filename, skip_cache=False)`** — baixa via
  `MediaIoBaseDownload` (chunks de 10 MB). Cacheia em `cache/comics/{id}{ext}`
  (extensão do nome, ou `.cbz` se não houver). `skip_cache=True` não cacheia
  (usado p/ extrair capa de CBR sem guardar o arquivo).
- **`download_range(file_id, start, end)`** — HTTP Range direto (requests + token),
  base das extrações/contagens parciais.

---

## 7. Backend — `local_client.py`

- **Registro** (`data/local_registry.json`): `path_to_id` (md5 do caminho) e
  `id_to_path`. Leitura/escrita com **lock** e gravação **atômica** (`path_to_id`
  grava o registro só quando vê um ID novo).
- **`list_items(folder_path)`** → `{folders, comics}`. Cada comic traz `id, name,
  size, modified` (mtime); cada pasta traz `id, name, _local_folder_path, modified`.
- **`browse(path)`** — navegador de diretórios para o seletor de pasta local
  (lista drives no Windows; navega subpastas).
- **`peek_folder_cover(folder_path, depth=4)`** — 1º arquivo de HQ (recursivo);
  devolve o **caminho** (não o id) para evitar problemas de registro/encoding.
- `get_file_data` / `get_file_info` — leitura direta do disco.

---

## 8. Backend — `extractor.py`

Extrai capas e páginas de **CBZ/ZIP** (zipfile nativo), **CBR/RAR** (7-Zip via
subprocess, ou UnRAR) e **PDF** (PyMuPDF/fitz).

### Detecção de formato
- `_effective_ext(filename, data)` — usa a extensão do nome se conhecida; caso
  contrário **fareja os bytes** (`_sniff_ext`).
- As funções públicas que recebem **bytes** (`extract_cover`, `extract_page`,
  `get_page_count`) usam `_effective_ext` → funcionam com arquivos sem extensão.
- As funções `_path` (`extract_cover_path`, `extract_page_path`,
  `get_page_count_path`) abrem o arquivo **por caminho** (local) — PDF via
  `fitz.open(path)`, CBZ lê só a entrada necessária, CBR roda o 7-Zip sobre o
  arquivo original (sem copiar o archive inteiro para temporário).

### Extração parcial (Drive, sem baixar tudo)
- **`extract_cover_partial`** — CBZ via Range (lê EOCD + Central Directory + 1ª
  imagem); PDF via primeiros 2 MB; CBR baixa o arquivo (skip_cache) pois RAR não tem
  índice. Para arquivo sem extensão, cai no caminho de download completo + sniff.
- **Capa branca de PDF:** `_cover_pdf_partial` renderiza a 1ª página dos 2 MB; se
  `_is_blank_jpeg` (página renderizou em branco porque o conteúdo está além dos
  2 MB), **baixa o arquivo completo** (skip_cache) e renderiza de verdade.
- **`get_page_count_partial`** — PDF: `fitz.open(stream=2MB).page_count` (o PyMuPDF
  reconstrói a estrutura mesmo com o stream truncado); CBZ: conta as imagens lendo só
  o Central Directory na cauda; CBR/CB7: `None` (precisa de download completo).

### Ferramentas RAR
Detectadas no import (`_7Z`, `_UNRAR`) em caminhos padrão do Windows + PATH. Sem
nenhuma, CBR não abre (avisa no console).

---

## 9. Backend — `config_manager` · `profiles` · `reading_manager` · `storage`

- **`config_manager.py`** — `data/config.json` (lista de fontes). `_load` tenta vários
  encodings (auto-cura para UTF-8) e migra de `DRIVE_FOLDERS` (.env) na 1ª execução.
  Funções de escrita decoradas com `@_locked`; `_save` usa `atomic_write`.
- **`profiles.py`** — perfis estilo Netflix em `data/profiles.json`; cada perfil tem
  a pasta `data/profiles/<id>/` (`reading_state.json` + `avatar.jpg` opcional).
  `ensure()` roda no import do `main.py`: numa instalação nova cria o perfil inicial
  ("Leitor") e, se existir um `data/reading_state.json` de antes dos perfis, migra-o
  para esse perfil (o original vira `reading_state.pre-perfis.json`). Avatares prontos
  `p1..p12` (desenhados no front) ou foto enviada. Excluir move a pasta para
  `data/profiles/_excluidos/<id>-<ts>` (nunca apaga) e não deixa remover o último perfil.
- **`reading_manager.py`** — estado de leitura **por perfil** (toda função recebe
  `pid`): `in_progress`, `read`, `queue`, `lists`, `ratings` e `daily` (páginas por dia,
  base do mapa de atividade). Todas as funções que escrevem usam `@_locked` (RLock) e
  `_save` é atômico. Inclui `replace_state` (import de backup), `get_saved_page`
  (retomada sincronizada), `set_rating` e `get_stats`.
- **`storage.py`** — `atomic_write(path, text)`: escreve num `.tmp` no mesmo
  diretório e faz `os.replace` (atômico, inclusive Windows). Base de toda a
  persistência (ver §10).

---

## 10. Persistência: gravação atômica + travas

Como os endpoints rodam em múltiplas threads e há threads de pré-geração, escritas
concorrentes nos JSON poderiam **corromper** o arquivo ou **perder atualizações**.
Solução:

- **Gravação atômica** (`storage.atomic_write`): nunca existe um arquivo "pela
  metade" — ou está o conteúdo antigo, ou o novo. Elimina corrupção.
- **Trava por arquivo** (`threading.RLock`): cada operação de escrita faz
  *ler → modificar → gravar* dentro do lock (via decorador `@_locked`), eliminando
  perda de atualização concorrente. Leituras não travam (a escrita atômica garante
  leitura sempre completa).

Aplica-se a `profiles.json`, `profiles/<id>/reading_state.json`, `config.json`,
`local_registry.json` e `page_counts.json`.

---

## 11. Sistema de cache

| Pasta/arquivo | Conteúdo | Política |
|---|---|---|
| `cache/covers/{id}.jpg` | Capa de cada HQ (JPEG) | permanente |
| `cache/covers/pages_{id}/{n}.jpg` | Páginas renderizadas | removidas com o arquivo |
| `cache/main_covers/{id}.jpg` | Capa de pasta (Drive) | permanente |
| `cache/main_covers/lfolder_{md5}.jpg` | Capa de pasta (local) | permanente |
| `cache/comics/{id}{ext}` | Arquivo completo baixado do Drive | **LRU `CACHE_MAX_GB`** |
| `data/page_counts.json` | Contagem de páginas por id | permanente |

- **Eviction LRU** (`_evict`): se `cache/comics` passa de `CACHE_MAX_GB` (padrão 15),
  remove os arquivos menos recentemente acessados (por `atime`) até ~85% do limite;
  também apaga o `pages_{id}` correspondente.
- **Pré-geração**: ao abrir uma HQ e ao virar páginas, as próximas N são geradas em
  background (`_pregen`), respeitando o semáforo de extração.
- **Service Worker**: cache-first para capas/páginas de HQ (imutáveis), network-first
  para capas de pasta (mutáveis), API e shell. Ver §17.

---

## 12. Pipeline de capas

1. `GET /api/comics/{id}/cover` → se `cache/covers/{id}.jpg` existe, serve.
2. Senão gera via `_get_cover`:
   - **Local:** `extract_cover_path` (abre por caminho).
   - **Drive:** `extract_cover_partial` (CBZ Range / PDF 2 MB com fallback de página
     branca / CBR download).
3. **Capa de pasta** (`/api/folders/{id}/cover`): acha o 1º comic via
   `peek_folder_cover` e usa a capa dele; cacheada em `main_covers`. **Atualizar
   capa** (`/cover/refresh`) limpa o cache e busca com `depth=8`. **Alterar capa**
   (`/cover/upload`) aceita imagem do usuário (recorta para 2:3 e salva JPEG).

---

## 13. Contagem de páginas

- **Completa** (`get_page_count` / `get_page_count_path`): CBZ (conta imagens no zip),
  CBR (7-Zip lista), PDF (fitz). Usada no `/info` (ao abrir o leitor).
- **Parcial barata** (`get_page_count_partial`): PDF lê 2 MB, CBZ lê a cauda; sem
  baixar o arquivo inteiro. Usada no `/pages` (tooltip de hover) para Drive
  não-cacheado.
- **Persistência:** todo resultado é gravado em `page_counts.json` via `_pc_set`,
  ficando instantâneo nas próximas vezes. `/info` também persiste.
- **Ordem de resolução do `/pages`:** cache persistente → progresso salvo → local
  (caminho) → Drive já cacheado (sniff) → Drive parcial. CBR não-cacheado → `None`.

---

## 14. Referência de endpoints

### Autenticação / sistema
| Método | Rota | Descrição |
|---|---|---|
| GET | `/auth/status` | `{authenticated}` |
| GET | `/auth/login` | Redireciona ao OAuth (ou página de onboarding) |
| GET | `/auth/callback` | Troca `code`→token |
| POST | `/auth/logout` | Remove o token |
| POST | `/auth/credentials` | Envia o `credentials.json` (só no próprio PC) |
| GET | `/api/netinfo` | `{ip, port}` da LAN (rodapé da Início) |
| POST | `/api/shutdown` | Encerra o servidor |

### Perfis
| Método | Rota |
|---|---|
| GET | `/api/profiles` · POST `/api/profiles` `{name, avatar}` |
| PUT/DELETE | `/api/profiles/{pid}` |
| GET/POST/DELETE | `/api/profiles/{pid}/photo` (upload recortado em JPEG) |

> **Header `X-Profile`:** obrigatório nas rotas `/api/reading/*`, `/api/lists*` e
> `/api/stats`; sem perfil válido → **409**. `/info` e `/pages` aceitam sem perfil
> (`saved_page` só vem com perfil). Biblioteca, capas, cache e pastas são compartilhados.

### Configuração de pastas
| Método | Rota |
|---|---|
| GET | `/api/config/folders` |
| POST | `/api/config/folders/drive` `{name, link}` |
| POST | `/api/config/folders/local` `{name, path}` |
| PUT | `/api/config/folders/{id}` `{name}` (renomear) |
| DELETE | `/api/config/folders/{id}` |
| POST | `/api/config/folders/reorder` `{ids:[...]}` |

### Listagem / busca
| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/items?folder_id=` | Conteúdo de pasta do Drive |
| GET | `/api/local/items?path=` | Conteúdo de pasta local |
| GET | `/api/local/browse?path=` | Navegador de diretórios |
| GET | `/api/search?q=` | Busca no Drive |
| GET | `/api/local/search?path=&q=` | Busca local (recursiva) |

### Capas / páginas
| Método | Rota |
|---|---|
| GET | `/api/folders/{id}/cover` · POST `/cover/refresh` · POST `/cover/upload` |
| GET | `/api/comics/{id}/cover` |
| GET | `/api/comics/{id}/info` → `{name, pages, saved_page}` |
| GET | `/api/comics/{id}/pages` → `{pages}` (barato, p/ hover) |
| GET | `/api/comics/{id}/page/{n}` |

### Estado de leitura / listas / stats
| Método | Rota |
|---|---|
| GET | `/api/reading/state` |
| POST | `/api/reading/progress` `{file_id, name, page, pages}` |
| POST | `/api/reading/finish` `{file_id, name}` |
| DELETE | `/api/reading/progress/{id}` · `/api/reading/read/{id}` |
| POST | `/api/reading/queue` · DELETE `/api/reading/queue/{id}` |
| POST | `/api/reading/rate` `{file_id, name, stars, parent?}` (0 remove) |
| POST | `/api/reading/finish-folder?folder_id=` (marca pasta inteira, recursivo) |
| POST | `/api/reading/import` (backup) |
| GET | `/api/lists` · POST `/api/lists` · PUT/DELETE `/api/lists/{id}` |
| POST | `/api/lists/{id}/comics` · DELETE `/api/lists/{id}/comics/{file_id}` |
| GET | `/api/stats` |

### Cache
| Método | Rota |
|---|---|
| GET | `/api/cache/status` · POST `/api/cache/evict` · POST `/api/warmup` |

---

## 15. Esquemas de dados (JSON)

`data/config.json`
```json
{ "folders": [
  { "id":"42f6", "name":"Marvel", "type":"drive", "drive_id":"1wXs...", "order":0 },
  { "id":"19c5", "name":"HQs",    "type":"local", "local_path":"C:\\...\\HQs", "order":1 }
]}
```

`data/profiles.json`
```json
{ "profiles": [
  { "id":"principal", "name":"Leitor", "avatar":"p1", "photo_v":0, "created":1719 }
]}
```
(`photo_v` muda a cada foto nova e é usado como `?v=` para furar caches.)

`data/profiles/<id>/reading_state.json`
```json
{
  "in_progress": { "<id>": {"name":"...", "page":12, "pages":40, "ts":1719} },
  "read":        { "<id>": {"name":"...", "ts":1719} },
  "queue":       [ {"id":"<id>", "name":"...", "ts":1719} ],
  "lists":       { "<lid>": {"name":"Favoritos","created":1719,
                              "comics":[{"id":"<id>","name":"...","added":1719,
                                         "is_folder":true}]} },
  "ratings":     { "<id>": {"name":"...", "stars":4, "ts":1719, "parent":"<folder_id>"} },
  "daily":       { "2026-10-31": 57 }
}
```

`data/local_registry.json` → `{ "local_<md5>": "C:\\caminho\\arquivo.cbz" }`
`data/page_counts.json`    → `{ "<id>": 40 }`

---

## 16. Variáveis de ambiente

| Var | Padrão | Descrição |
|---|---|---|
| `HOST` | `0.0.0.0` | Interface de escuta (rede vs só local) |
| `PORT` | `8000` | Porta (também define o `OAUTH_REDIRECT`) |
| `CACHE_MAX_GB` | `15` | Limite do cache de arquivos completos |
| `EXTRACT_WORKERS` | `4` | Extrações pesadas simultâneas |
| `NO_BROWSER` | `0` | `1` = não abrir o navegador ao iniciar |
| `CORS_ORIGINS` | *(vazio)* | Origens extras autorizadas (lista separada por vírgula); `*` desliga o filtro de origem |
| `OMNIVAULT_HOME` | pasta do projeto | Onde ficam `data/`, `cache/` e `credentials/` |
| `OAUTH_REDIRECT` | `http://localhost:{PORT}/auth/callback` | Redirect do OAuth |
| `DRIVE_FOLDERS` | — | Migração legada de pastas Drive na 1ª execução |

---

## 17. Frontend

### `index.html` (SPA da biblioteca)
- **Estado global**: `roots`, `activeRoot`, `folderStack`, `allComics/allFolders`,
  `rState` (estado de leitura), `userLists`, `sortOrder`, `curView`, etc.
- **Delegação de eventos**: cards e itens usam `data-act` + `data-*`; um único
  listener (`dispatchAct`) despacha cliques **e** teclado (Enter/Espaço). Isso
  elimina `onclick` com dados interpolados (e o bug de nomes/paths com apóstrofo) e
  reduz a superfície de injeção.
- **Capas lazy**: `IntersectionObserver` (margem 300px) só pede a capa quando o card
  está perto da viewport; há também um teto de concorrência no loader de imagens.
- **Ordenação** (`sortC`): `Intl.Collator({numeric:true})` (natural), por
  nome/data (`modifiedTime`/`modified`)/tamanho (`size`). Aplicada também às pastas
  (que têm `modifiedTime`; por tamanho caem para nome).
- **Badge de tipo** (`badge`/`fileKind`): deriva o formato da extensão **ou** do
  `mimeType` (mostra `PDF` para arquivos sem extensão).
- **Tooltip de hover**: mostra nome + total de páginas (`/api/comics/{id}/pages`,
  com cache em `_pageCache`) ou o progresso (`X / Y · Z%`) para HQs em andamento.
  Só para HQs (cards `.card`), não para pastas.
- **Toasts e diálogos** (`toast`, `confirmDialog`, `promptDialog`, `pickList`):
  substituem `alert/confirm/prompt` nativos por componentes estilizados.
- **Ícones SVG** (`ICONS`, `ic()`, `hydrateIcons`): set próprio (estilo Feather),
  injetados em placeholders `data-ic` e inline nos templates. Sem emojis na UI.
- **Views** (`sw(v)`): Início (banner "Continuar lendo", prateleiras horizontais,
  atividade/heatmap), Bibliotecas (pastas + faixa da série `renderFolderStrip`),
  Andamento, Lidas (agrupadas por mês), Fila, Baixadas, Listas (coleções com mosaico) e
  Configurações. Item ativo do menu sempre no laranja da marca.
- **Perfis**: tela `#pf` ("Quem está lendo?"), editor `#pfeov`; trocar no meio da sessão
  recarrega a página. Ao voltar para o app (`visibilitychange` após >5 s) recarrega o
  estado para refletir leitura feita em outro aparelho.
- **Ajuda** (`HELP`, `openHelp`): botão **?** no topo e tecla `?` no PC; janela com abas
  (Primeiros passos, Biblioteca, Leitor, Sua leitura, Perfis, iPad e celular,
  Configurações).
- **Acabamento**: só `transform`/`opacity` nas animações, tudo desligado com
  `prefers-reduced-motion`; todo hover (PC) tem equivalente de toque (`:active`).

### `reader.html` (leitor)
- **Carregamento de páginas**: `pageCache` (Map de object URLs), pré-carrega N à
  frente e revoga as distantes (>8) para liberar memória.
- **Navegação**: clique (zonas esquerda/direita/centro), teclado (setas/espaço/F),
  toque (tap-zones, swipe), com desambiguação de duplo-clique/toque (zoom) e do
  "click sintético" do toque.
- **Zoom/pan**: scroll/pinça/duplo-clique; arrasto para mover; indicador de %.
- **Brilho/contraste**: salvos em `localStorage` e restaurados ao abrir.
- **Retomada sincronizada**: começa em `max(localStorage cs_pos, info.saved_page)`.
- **Salvar progresso**: `localStorage` imediato + `POST /api/reading/progress`
  (debounce 1,5 s). Sem rede, vai para a fila `cs_syncq` (cada item com o perfil `p`),
  despachada pelo index quando o servidor volta.
- **Deslize que acompanha o dedo**: `#peek-wrap` mostra a página vizinha; vira com
  >25% da largura ou flick >0,35 px/ms. Barra de progresso arrastável (`#prog-hit`).
- **Fim da HQ** (`#fp`): nota em estrelas + cartão do próximo volume da pasta.

### `profile.js`
Perfil ativo do aparelho (`localStorage cs_profile`) + wrapper de `fetch` que injeta
`X-Profile` em toda chamada `/api/`. Usado pelo index e pelo leitor.

### `sw.js` (Service Worker)
- Caches `cs-shell-v7`, `cs-images-v7`, `cs-api-v7` e `cs-offline-v1` (HQs baixadas).
- Cache-first para capas/páginas de HQ; network-first para capas de pasta, `/api/` e
  shell (mudanças no HTML chegam sem trocar a versão do SW).
- Rotas por perfil (`/api/reading/`, `/api/lists`, `/api/stats`) usam chave de cache
  `?__profile=<id>`, para um perfil nunca ver o cache de outro.
- **Offline exige contexto seguro** (https ou localhost); via `http://IP` no iPad o
  navegador não expõe Service Worker/Cache Storage. Limitação aceita.

---

## 18. Decisões de design e armadilhas conhecidas

- **Índice do Drive não casa extensão** (`name contains '.cbz'` falha): por isso a
  listagem/busca lista tudo e filtra por extensão **ou** mimeType no cliente.
- **Arquivos sem extensão no Drive** (ex.: `Capítulo 01` = PDF): resolvidos por
  mimeType (listagem) + sniff de bytes (extração). No cache do Drive eles viram
  `{id}.cbz` (default do `download_file`) — por isso o `/pages` passa nome vazio ao
  `get_page_count` para forçar o sniff.
- **page_count de PDF por 2 MB**: o PyMuPDF reconstrói a estrutura mesmo com o stream
  truncado, então a contagem parcial é confiável. Já a **capa** pode sair em branco
  (conteúdo além dos 2 MB) → fallback de download completo.
- **CBR não tem índice no início**: capa e contagem exigem o arquivo completo (sem
  caminho parcial barato).
- **PyMuPDF travado em 1.26.x**: a partir da 1.27 (MuPDF 1.27+) o PDF truncado dos
  2 MB iniciais é recusado ("Invalid number of pages") e capa/contagem do Drive caem no
  download COMPLETO. Medido com PDFs reais: 1.24–1.26.7 abrem, 1.27–2.1 recusam. Trava em
  `tests/test_extractor.py`.
- **CB7** passa pelo mesmo caminho do CBR (7-Zip abre os dois); requer 7-Zip (`7z`/`7zz`).
- **Token do Drive expira a cada ~1 h**: `is_authenticated()` renova sozinho com o
  refresh token (além do `_load_token` e antes de `download_range`), então aparelhos que
  abrem o app horas depois continuam conectados.
- **Concorrência**: persistência atômica + RLock (ver §10) — não há banco; para
  metadados ricos (ex.: `ComicInfo.xml`), SQLite seria o próximo passo natural.
- **Capas lazy**: cards fora da viewport não geram requisição até serem vistos —
  o silêncio nos logs ao parar de rolar é esperado, não travamento.
- **Bind `0.0.0.0` por padrão**: necessário para acesso pelo celular; restrinja com
  `HOST=127.0.0.1` em redes não confiáveis. Não há autenticação de usuário: perfis
  separam dados, não protegem acesso.
- **Encoding cp1252 × UTF-8 (Windows)**: os loaders de JSON tentam
  utf-8/utf-8-sig/cp1252/latin-1 e regravam em UTF-8. O 7-Zip roda com `-sccUTF-8` e
  há extração por posição como fallback para nomes acentuados.
