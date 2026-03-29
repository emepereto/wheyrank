"""
Debug v6 — intercepta requisicoes de rede que a pagina do ML faz
para encontrar onde o preco real e carregado
"""
import time
import json
from playwright.sync_api import sync_playwright

precos_encontrados = []
urls_capturadas = []

def handle_response(response):
    url = response.url
    # Filtra so as chamadas de API do ML que podem ter preco
    if any(x in url for x in ["api.mercadolibre", "api.mercadopago", "/pdp/", "variations", "price", "product"]):
        try:
            if "json" in response.headers.get("content-type", ""):
                body = response.json()
                body_str = json.dumps(body)
                urls_capturadas.append({
                    "url": url[:120],
                    "body_preview": body_str[:300]
                })

                # Busca precos no JSON
                import re
                precos = re.findall(r'"(?:price|amount|value|sale_price)"\s*:\s*(\d+(?:\.\d+)?)', body_str)
                for p in precos:
                    val = float(p)
                    if 10 < val < 10000:
                        precos_encontrados.append({"url": url[:80], "preco": val})
        except Exception:
            pass

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

        # Intercepta todas as respostas
        page.on("response", handle_response)

        print(f"Abrindo {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print("Aguardando requisicoes assincronas...")
        time.sleep(8)

        print(f"\n=== URLs de API capturadas ({len(urls_capturadas)}) ===")
        for item in urls_capturadas[:15]:
            print(f"\nURL: {item['url']}")
            print(f"Body: {item['body_preview']}")

        print(f"\n=== Precos encontrados nas requisicoes ===")
        vistos = set()
        for item in precos_encontrados:
            chave = f"{item['preco']}"
            if chave not in vistos:
                vistos.add(chave)
                print(f"  R${item['preco']:.2f} <- {item['url']}")

        browser.close()
        print("\nFinalizado")

if __name__ == "__main__":
    main()
