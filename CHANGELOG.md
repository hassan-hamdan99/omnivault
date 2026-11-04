# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Google Drive
- Enviar a credencial pelo próprio app: a página "Conectar o Google Drive" tem
  **Escolher arquivo** para o JSON baixado do Google Cloud (sem renomear/mover). O app
  confere se é do tipo Desktop, explica o erro se for do tipo Web e já abre o login.
  Aceito só no navegador do PC onde o servidor roda.

## [1.0.0] — 2026-11-04

Primeira versão pública.

### Biblioteca e leitura
- Fontes **Google Drive** (somente leitura, OAuth) e **pastas locais**; formatos CBZ, CBR,
  CB7, PDF, ZIP e RAR, inclusive arquivos do Drive sem extensão (detecção por tipo/bytes).
- Capas automáticas com leitura parcial (CBZ por Range, PDF pelos primeiros 2 MB); capa de
  pasta editável.
- Leitor para PC e toque: zoom, página que acompanha o dedo, modo mangá, página dupla,
  brilho/contraste, tela cheia, barra de progresso arrastável, retomada sincronizada,
  nota ao terminar e atalho para o próximo volume.
- Ordenar, filtrar, agrupar séries, seleção em lote, busca (Drive + local).

### Organização
- **Perfis** estilo Netflix ("Quem está lendo?"), com avatar pronto ou foto.
- Início com "Continuar lendo", prateleiras e mapa de atividade; Andamento, Lidas (por
  mês), Fila, Listas (coleções), notas e "marcar pasta como lida".
- Backup: exportar/importar estado do perfil (JSON).
- Ajuda dentro do app (botão **?** / tecla `?`).

### Plataforma
- PWA instalável (tela de início do iPad/celular); cache LRU de arquivos do Drive.
- Instalação guiada no Windows (`setup.bat`) com atalho na Área de Trabalho
  (`criar-atalho.bat`); `run.sh` para Linux (e macOS, experimental).
- Python 3.11, 3.12 e 3.13; testes automatizados (API + extração) em Windows e Linux via
  GitHub Actions. macOS: experimental (roda pelo `run.sh`, ainda fora do CI).

### Segurança
- API restrita à mesma origem: sem CORS por padrão e chamadas de outras origens recusadas
  com 403 (sites de terceiros não leem pastas/estado nem desligam o servidor).
- Dependências atualizadas (inclui correção de segurança do Pillow, CVE-2024-28219).
