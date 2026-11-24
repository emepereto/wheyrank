# WheyRank — instruções para o Claude

## Economia de tokens (REGRA PRINCIPAL)
- Use SEMPRE o modelo mais barato que dá conta da demanda. Nunca use um modelo acima do necessário.
  - **Haiku**: tarefas simples — trocar texto, corrigir link, ajustar CSS, renomear arquivo, atualizar sitemap, buscas rápidas.
  - **Sonnet**: tarefas médias — criar artigo novo, nova página, refatorar um arquivo, ajustar o scraper.
  - **Opus**: só para tarefas complexas — mudança de arquitetura, debugging difícil que envolve várias partes, estratégia geral.
- Ao delegar para subagentes, passe `model: "haiku"` ou `"sonnet"` sempre que possível.
- Não spawnar subagentes/workflows sem necessidade. Respostas curtas e diretas. Não reler arquivos já lidos.

## O projeto
Site de afiliado (Mercado Livre) que ranqueia whey protein por **custo real por grama de proteína**.
- Domínio: https://www.wheyrank.com.br (Vercel). `wheyrank.com.br` sem www redireciona para www.
- `index.html`: página única; o ranking é carregado no navegador via Supabase (view `ranking_wheys`).
- `artigos/*.html`: artigos de SEO. Rota `/artigos/<slug>` → `artigos/<slug>.html` (ver `vercel.json`).
  O nome do arquivo TEM que bater com o link usado no index, no sitemap e no canonical.
- `scraper.mjs` (+ `ml-pagina.mjs`): roda via GitHub Actions (`.github/workflows/main.yml`), lê o preço da página que o link de afiliado abre (API do ML bloqueia preços desde 23/11/2026) e grava no Supabase; depois `gerar.mjs` gera as páginas e faz commit.
  Secrets: SUPABASE_URL, SUPABASE_KEY (service_role). ML_APP_ID/ML_SECRET não são mais usados. `keep-alive.yml` evita o GitHub desativar o cron.
- Links de afiliado ficam na coluna `link_ml` da tabela `wheys` (formato `mercadolivre.com.br/social/emepereto?...`).
- Railway/Procfile/nixpacks/runtime.txt são legado (não usados).

## Checklist ao criar/alterar páginas
- Atualizar `sitemap.xml` (lastmod) e o card no `index.html`.
- Canonical com `https://www.wheyrank.com.br/...`.
- Todo artigo deve ter links de afiliado (rel="sponsored noopener") e o evento GA `clique_mercado_livre`.
