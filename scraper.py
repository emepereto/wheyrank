"""
WHEY COMPARADOR — Scraper de Preços
====================================
Roda automaticamente no Railway a cada 6 horas.
Busca preços no Mercado Livre via API oficial + scraping de backup.

SETUP:
1. Crie um projeto no Railway (railway.app)
2. Suba este arquivo
3. Adicione as variáveis de ambiente (Settings > Variables):
   - SUPABASE_URL
   - SUPABASE_KEY
   - ML_ACCESS_TOKEN  (opcional — API oficial do ML)
4. Em Settings > Cron, configure: 0 */6 * * *  (a cada 6h)
"""

import os
import time
import json
import requests
from datetime import datetime

# ─── Configuração ─────────────────────────────────────────────
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")
ML_APP_ID     = os.environ.get("ML_APP_ID", "")      # Opcional
ML_SECRET     = os.environ.get("ML_SECRET", "")      # Opcional

HEADERS_SUPA = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


# ─── Funções Supabase ──────────────────────────────────────────

def buscar_wheys():
    """Retorna todos os wheys com suas URLs de produto para scraping."""
    url = f"{SUPABASE_URL}/rest/v1/precos"
    params = {
        "select": "whey_id,plataforma,url_produto",
        # Pega apenas 1 URL por whey/plataforma (a mais recente)
        "order": "coletado_em.desc",
    }
    resp = requests.get(url, headers=HEADERS_SUPA, params=params)
    resp.raise_for_status()

    # Deduplica: mantém apenas a primeira URL por (whey_id, plataforma)
    vistos = set()
    resultado = []
    for item in resp.json():
        chave = (item["whey_id"], item["plataforma"])
        if chave not in vistos and item.get("url_produto"):
            vistos.add(chave)
            resultado.append(item)
    return resultado


def salvar_preco(whey_id, plataforma, preco, url_produto):
    """Insere um novo registro de preço no Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/precos"
    payload = {
        "whey_id":     whey_id,
        "plataforma":  plataforma,
        "preco":       preco,
        "url_produto": url_produto,
        "coletado_em": datetime.utcnow().isoformat(),
    }
    resp = requests.post(url, headers=HEADERS_SUPA, json=payload)
    if resp.status_code in (200, 201):
        print(f"  ✅ Salvo: whey_id={whey_id} | {plataforma} | R${preco:.2f}")
    else:
        print(f"  ❌ Erro ao salvar: {resp.text}")


# ─── Scraper Mercado Livre (API oficial) ───────────────────────

def preco_mercadolivre_api(url_produto: str) -> float | None:
    """
    Tenta buscar o preço via API oficial do ML.
    A URL do produto tem o ID embutido: /MLB-1234567890
    """
    try:
        # Extrai o ID do produto da URL
        # Ex: https://www.mercadolivre.com.br/produto/p/MLB123 → MLB123
        partes = url_produto.rstrip("/").split("/")
        item_id = next(
            (p for p in reversed(partes) if p.upper().startswith("MLB")),
            None
        )
        if not item_id:
            return None

        api_url = f"https://api.mercadolibre.com/items/{item_id}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code == 200:
            dados = resp.json()
            return float(dados.get("price", 0)) or None
    except Exception as e:
        print(f"    API ML erro: {e}")
    return None


def preco_mercadolivre_scraping(url_produto: str) -> float | None:
    """
    Fallback: scraping simples via requests + busca no JSON embutido na página.
    Funciona enquanto o ML não bloquear — se bloquear, use Playwright.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        resp = requests.get(url_produto, headers=headers, timeout=15)
        html = resp.text

        # O ML embute os dados do produto em JSON dentro da página
        # Procura pelo padrão: "price":123.45
        import re
        match = re.search(r'"price"\s*:\s*(\d+(?:\.\d+)?)', html)
        if match:
            return float(match.group(1))
    except Exception as e:
        print(f"    Scraping ML erro: {e}")
    return None


def preco_shopee_scraping(url_produto: str) -> float | None:
    """
    Scraping básico da Shopee.
    ATENÇÃO: Shopee usa muito JavaScript — se não funcionar,
    precisará de Playwright (veja comentário no final do arquivo).
    """
    try:
        # Extrai IDs da URL da Shopee
        # Ex: shopee.com.br/produto-i.123456.987654321
        import re
        match = re.search(r'i\.(\d+)\.(\d+)', url_produto)
        if not match:
            return None

        shop_id, item_id = match.group(1), match.group(2)
        api_url = (
            f"https://shopee.com.br/api/v4/item/get?"
            f"itemid={item_id}&shopid={shop_id}"
        )
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://shopee.com.br/",
            "X-API-Source": "pc",
        }
        resp = requests.get(api_url, headers=headers, timeout=15)
        dados = resp.json()

        preco_centavos = (
            dados.get("data", {}).get("price") or
            dados.get("data", {}).get("price_min")
        )
        if preco_centavos:
            return float(preco_centavos) / 100000  # Shopee usa centésimos de centavo
    except Exception as e:
        print(f"    Shopee scraping erro: {e}")
    return None


def preco_amazon_scraping(url_produto: str) -> float | None:
    """Scraping básico da Amazon Brasil."""
    try:
        import re
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        resp = requests.get(url_produto, headers=headers, timeout=15)
        html = resp.text

        # Padrão do preço na Amazon BR
        # Ex: <span class="a-price-whole">129</span>
        match = re.search(
            r'<span class="a-price-whole">(\d+)</span>'
            r'.*?<span class="a-price-fraction">(\d+)</span>',
            html, re.DOTALL
        )
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")

        # Fallback: busca o padrão de preço em JSON embutido
        match2 = re.search(r'"buyingPrice"\s*:\s*(\d+(?:\.\d+)?)', html)
        if match2:
            return float(match2.group(1))
    except Exception as e:
        print(f"    Amazon scraping erro: {e}")
    return None


# ─── Dispatcher por plataforma ─────────────────────────────────

SCRAPERS = {
    "mercadolivre": lambda url: (
        preco_mercadolivre_api(url) or preco_mercadolivre_scraping(url)
    ),
    "shopee":  preco_shopee_scraping,
    "amazon":  preco_amazon_scraping,
}


# ─── Loop principal ────────────────────────────────────────────

def main():
    print(f"\n🕐 Iniciando coleta: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 50)

    produtos = buscar_wheys()
    print(f"📦 {len(produtos)} produto(s) para atualizar\n")

    sucessos = 0
    falhas   = 0

    for item in produtos:
        whey_id    = item["whey_id"]
        plataforma = item["plataforma"]
        url        = item["url_produto"]

        print(f"🔍 whey_id={whey_id} | {plataforma}")
        print(f"   {url[:70]}...")

        scraper = SCRAPERS.get(plataforma)
        if not scraper:
            print(f"   ⚠️  Plataforma desconhecida: {plataforma}")
            falhas += 1
            continue

        preco = scraper(url)

        if preco and preco > 0:
            salvar_preco(whey_id, plataforma, preco, url)
            sucessos += 1
        else:
            print(f"  ⚠️  Não encontrou preço para whey_id={whey_id}")
            falhas += 1

        # Pausa entre requisições para não ser bloqueado
        time.sleep(2)

    print("\n" + "=" * 50)
    print(f"✅ Sucesso: {sucessos}  |  ❌ Falha: {falhas}")
    print(f"🏁 Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()


# ─── NOTA: Se scraping simples for bloqueado ──────────────────
# Use Playwright para páginas com muito JavaScript:
#
# pip install playwright
# playwright install chromium
#
# from playwright.sync_api import sync_playwright
#
# def preco_com_playwright(url):
#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         page = browser.new_page()
#         page.goto(url, wait_until="networkidle")
#         # Shopee: aguarda o preço aparecer
#         preco_el = page.query_selector('[class*="price"]')
#         texto = preco_el.inner_text() if preco_el else ""
#         browser.close()
#         import re
#         match = re.search(r'[\d.,]+', texto.replace('.', '').replace(',', '.'))
#         return float(match.group()) if match else None
