"""
Debug v4 — extrai preco do JSON embutido no HTML
"""
import time
import re
import json
from playwright.sync_api import sync_playwright

def extrair_preco_html(html):
    """Tenta varios padroes para extrair o preco do HTML do ML."""

    # Padrao 1: JSON com "price" no script de dados da pagina
    matches = re.findall(r'"price"\s*:\s*(\d+(?:\.\d+)?)', html)
    if matches:
        precos = [float(m) for m in matches if 10 < float(m) < 10000]
        if precos:
            print(f"  Padrao 1 (json price): {sorted(precos)[:10]}")

    # Padrao 2: preco em formato brasileiro com virgula
    matches2 = re.findall(r'"amount"\s*:\s*(\d+(?:\.\d+)?)', html)
    if matches2:
        precos2 = [float(m) for m in matches2 if 10 < float(m) < 10000]
        if precos2:
            print(f"  Padrao 2 (json amount): {sorted(precos2)[:10]}")

    # Padrao 3: valor no formato R$ XX,XX
    matches3 = re.findall(r'R\$\s*(\d+),(\d{2})', html)
    if matches3:
        precos3 = [float(f"{a}.{b}") for a, b in matches3 if 10 < float(f"{a}.{b}") < 10000]
        if precos3:
            print(f"  Padrao 3 (R$ formato): {sorted(precos3)[:10]}")

    # Padrao 4: currentPrice ou salePrice
    matches4 = re.findall(r'(?:currentPrice|salePrice|sale_price|selling_price)["\s:]+(\d+(?:[.,]\d+)?)', html)
    if matches4:
        print(f"  Padrao 4 (currentPrice/salePrice): {matches4[:10]}")

    # Padrao 5: window.__PRELOADED_STATE__ ou similar
    match5 = re.search(r'__PRELOADED_STATE__\s*=\s*({.{100,500}})', html)
    if match5:
        print(f"  Padrao 5 (PRELOADED_STATE): {match5.group(1)[:200]}")

    # Padrao 6: dataLayer
    match6 = re.search(r'dataLayer\s*=\s*(\[.{50,500}\])', html)
    if match6:
        print(f"  Padrao 6 (dataLayer): {match6.group(1)[:200]}")

    # Padrao 7: "value" perto de "currency"
    matches7 = re.findall(r'"value"\s*:\s*(\d+(?:\.\d+)?)', html)
    if matches7:
        precos7 = [float(m) for m in matches7 if 10 < float(m) < 10000]
        if precos7:
            print(f"  Padrao 7 (value): {sorted(set(precos7))[:10]}")

def main():
    url = "https://www.mercadolivre.com.br/p/MLB18995412"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)

        html = page.content()
        print(f"HTML: {len(html)} chars")
        print(f"\n=== Testando padroes de extracao ===")
        extrair_preco_html(html)

        # Mostra trecho do HTML em volta de "price"
        idx = html.find('"price"')
        if idx > 0:
            print(f"\n=== Contexto em volta de 'price' ===")
            print(html[max(0,idx-50):idx+200])

        browser.close()

if __name__ == "__main__":
    main()
