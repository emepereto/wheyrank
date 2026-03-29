"""
Debug v3 — usa domcontentloaded e timeout menor
"""
import time
import re
from playwright.sync_api import sync_playwright

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

        print("Navegando...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print("Pagina carregada, aguardando 4s...")
        time.sleep(4)

        titulo = page.title()
        html   = page.content()
        print(f"Titulo: '{titulo}'")
        print(f"Tamanho: {len(html)} chars")
        print(f"\n--- HTML primeiros 1500 chars ---")
        print(html[:1500])

        precos = re.findall(r'(\d{2,3}[.,]\d{2})', html)
        print(f"\n--- Numeros no formato preco ---")
        print(precos[:30])

        browser.close()
        print("\nFinalizado")

if __name__ == "__main__":
    main()
