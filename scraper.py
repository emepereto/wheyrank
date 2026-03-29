"""
Script de debug — roda uma vez e loga o HTML e screenshot da pagina do ML
para identificar os seletores corretos do preco.
"""

import os
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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        page = context.new_page()

        print(f"Abrindo: {url}")
        page.goto(url, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        # Loga o titulo da pagina
        print(f"Titulo: {page.title()}")

        # Busca todos os elementos com preco
        print("\n=== Elementos com 'price' no texto ===")
        elementos = page.query_selector_all("[class*='price']")
        for el in elementos[:20]:
            try:
                classe = el.get_attribute("class") or ""
                texto  = el.inner_text().strip()[:50]
                if texto:
                    print(f"  .{classe[:60]} => '{texto}'")
            except Exception:
                pass

        # Busca via JS o JSON-LD
        print("\n=== JSON-LD na pagina ===")
        preco_js = page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                const results = [];
                for (const s of scripts) {
                    try {
                        const d = JSON.parse(s.textContent);
                        results.push(JSON.stringify(d).substring(0, 200));
                    } catch(e) {}
                }
                return results;
            }
        """)
        for item in preco_js:
            print(f"  {item}")

        # Salva o HTML completo
        html = page.content()
        with open("/tmp/ml_page.html", "w") as f:
            f.write(html)
        print(f"\nHTML salvo em /tmp/ml_page.html ({len(html)} chars)")

        # Busca especificamente por fracoes de preco
        print("\n=== Busca direta por fracao de preco ===")
        seletores = [
            ".andes-money-amount__fraction",
            ".price-tag-fraction",
            "[class*='fraction']",
            "[class*='amount']",
            "span[itemprop='price']",
            "[data-testid*='price']",
        ]
        for s in seletores:
            try:
                el = page.query_selector(s)
                if el:
                    print(f"  ENCONTRADO '{s}' => '{el.inner_text().strip()}'")
                else:
                    print(f"  nao encontrado: '{s}'")
            except Exception as e:
                print(f"  erro em '{s}': {e}")

        browser.close()

if __name__ == "__main__":
    main()
