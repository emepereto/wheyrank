"""
Debug v5 — encontra 65,13 no HTML e mostra contexto
"""
import time
from playwright.sync_api import sync_playwright

def main():
    url = "https://www.mercadolivre.com.br/p/MLB18995412"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="pt-BR",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        html = page.content()

        # Mostra contexto em volta de cada ocorrencia de 65
        print("=== Contexto em volta de '65,13' ===")
        idx = 0
        count = 0
        while count < 3:
            idx = html.find("65,13", idx)
            if idx == -1:
                break
            print(f"\n--- Ocorrencia {count+1} (pos {idx}) ---")
            print(repr(html[max(0,idx-150):idx+150]))
            idx += 1
            count += 1

        # Mostra contexto em volta de "price"
        print("\n=== Primeiras 3 ocorrencias de 'price' ===")
        idx = 0
        count = 0
        while count < 3:
            idx = html.lower().find("price", idx)
            if idx == -1:
                break
            print(f"\n--- pos {idx} ---")
            print(repr(html[max(0,idx-100):idx+200]))
            idx += 5
            count += 1

        browser.close()
        print("\nFinalizado")

if __name__ == "__main__":
    main()
