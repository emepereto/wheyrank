"""
Debug v7 — requests simples com headers de navegador real
"""
import requests
import re
import json

def tentar_requests(url, session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    resp = session.get(url, headers=headers, timeout=20, allow_redirects=True)
    return resp

def extrair_preco(html):
    # Tenta vários padrões no HTML
    padroes = [
        # JSON embutido com price
        r'"price"\s*:\s*"?(\d+(?:\.\d+)?)"?',
        r'"amount"\s*:\s*"?(\d+(?:\.\d+)?)"?',
        r'"value"\s*:\s*"?(\d+(?:\.\d+)?)"?',
        # Formato brasileiro
        r'R\$\s*<[^>]*>(\d+)<[^>]*>,<[^>]*>(\d{2})',
        r'"selling_price"\s*:\s*(\d+(?:\.\d+)?)',
        r'"sale_price"\s*:\s*(\d+(?:\.\d+)?)',
        r'priceValue["\s:]+(\d+(?:[.,]\d+)?)',
        r'"currentPrice"\s*:\s*(\d+(?:\.\d+)?)',
        r'itemprop="price"\s+content="(\d+(?:\.\d+)?)"',
        r'content="(\d+(?:\.\d+)?)"[^>]*itemprop="price"',
    ]

    for i, padrao in enumerate(padroes):
        matches = re.findall(padrao, html)
        if matches:
            # Filtra valores plausíveis de preço
            for m in matches[:5]:
                try:
                    val = float(str(m).replace(",", ".")) if isinstance(m, str) else float(f"{m[0]}.{m[1]}")
                    if 10 < val < 10000:
                        print(f"  Padrao {i+1}: R${val:.2f}")
                        return val
                except Exception:
                    pass
    return None

def main():
    session = requests.Session()

    # Primeiro visita a home para pegar cookies
    print("Visitando home do ML para pegar cookies...")
    try:
        tentar_requests("https://www.mercadolivre.com.br/", session)
        print(f"  Cookies: {dict(session.cookies)}")
    except Exception as e:
        print(f"  Erro na home: {e}")

    # Agora tenta o produto
    url = "https://www.mercadolivre.com.br/p/MLB18995412"
    print(f"\nBuscando produto: {url}")

    try:
        resp = tentar_requests(url, session)
        print(f"  Status: {resp.status_code}")
        print(f"  URL final: {resp.url}")
        print(f"  Tamanho: {len(resp.text)} chars")

        html = resp.text
        print(f"\n=== Primeiros 500 chars ===")
        print(html[:500])

        print(f"\n=== Tentando extrair preco ===")
        preco = extrair_preco(html)
        if not preco:
            print("  Nenhum preco encontrado")

            # Mostra contexto em volta de "price" no HTML
            idx = html.lower().find("price")
            if idx > 0:
                print(f"\n=== Contexto 'price' pos {idx} ===")
                print(repr(html[max(0,idx-100):idx+300]))

    except Exception as e:
        print(f"  Erro: {e}")

if __name__ == "__main__":
    main()
