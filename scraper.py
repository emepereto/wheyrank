"""
Debug v2 — loga os primeiros 3000 chars do HTML para ver o que o ML retornou
"""

import os
import time
from playwright.sync_api import sync_playwright

def main():
    url = "https://www.mercadolivre.com.br/p/MLB18995412"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
            ]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
            extra_http_headers={
                "Accept-Language": "pt-BR,pt;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        # Remove o webdriver flag que delata o bot
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        page = context.new_page()

        print(f"Abrindo: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"Erro no goto: {e}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

        time.sleep(5)

        titulo = page.title()
        print(f"Titulo: '{titulo}'")

        html = page.content()
        print(f"Tamanho HTML: {len(html)} chars")
        print(f"\n=== Primeiros 2000 chars do HTML ===")
        print(html[:2000])

        print(f"\n=== Ultimos 1000 chars do HTML ===")
        print(html[-1000:])

        # Tenta achar qualquer numero parecido com preco no HTML
        import re
        precos = re.findall(r'(?:R\$|\"price\"|\"amount\"|priceValue)[^\d]*(\d{2,3}[.,]\d{2})', html)
        print(f"\n=== Possiveis precos encontrados no HTML ===")
        for p in precos[:20]:
            print(f"  {p}")

        browser.close()

if __name__ == "__main__":
    main()
