"""
WHEYRANK — Scraper v8 com Playwright
======================================
- Abre cada pagina de produto no ML via navegador headless
- Extrai o preco exato que o usuario veria na tela
- Fallback para API do ML se o scraping falhar
- Renova token automaticamente
- Roda no Railway a cada 6h: 0 */6 * * *
"""

import os
import time
import random
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ML_APP_ID    = os.environ.get("ML_APP_ID", "")
ML_SECRET    = os.environ.get("ML_SECRET", "")

HEADERS_SUPA = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}


# --- Tokens ---

def carregar_tokens():
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/config",
            headers=HEADERS_SUPA,
            params={"select": "chave,valor"},
        )
        dados = {r["chave"]: r["valor"] for r in resp.json()}
        return dados.get("ml_access_token"), dados.get("ml_refresh_token")
    except Exception as e:
        print(f"  erro ao carregar tokens: {e}")
        return None, None


def salvar_tokens(access_token, refresh_token):
    for chave, valor in [("ml_access_token", access_token), ("ml_refresh_token", refresh_token)]:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/config",
            headers=HEADERS_SUPA,
            params={"chave": f"eq.{chave}"},
            json={"valor": valor},
        )
        if not resp.json():
            requests.post(
                f"{SUPABASE_URL}/rest/v1/config",
                headers=HEADERS_SUPA,
                json={"chave": chave, "valor": valor},
            )


def renovar_token(refresh_token):
    print("Renovando access token...")
    resp = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type":    "refresh_token",
            "client_id":     ML_APP_ID,
            "client_secret": ML_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    if resp.status_code == 200:
        dados = resp.json()
        novo_access  = dados.get("access_token")
        novo_refresh = dados.get("refresh_token", refresh_token)
        salvar_tokens(novo_access, novo_refresh)
        print("  Token renovado")
        return novo_access, novo_refresh
    print(f"  Erro ao renovar: {resp.text}")
    return None, None


# --- Supabase ---

def buscar_wheys():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"select": "id,nome,marca,sabor,ml_item_id", "ativo": "eq.true"},
    )
    resp.raise_for_status()
    return [w for w in resp.json() if w.get("ml_item_id")]


def salvar_preco(whey_id, preco, url_produto):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/precos",
        headers=HEADERS_SUPA,
        json={
            "whey_id":     whey_id,
            "plataforma":  "mercadolivre",
            "preco":       preco,
            "url_produto": url_produto,
            "coletado_em": datetime.utcnow().isoformat(),
        },
    )
    return resp.status_code in (200, 201)


def marcar_disponibilidade(whey_id, disponivel):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"id": f"eq.{whey_id}"},
        json={"disponivel": disponivel},
    )


# --- Scraping com Playwright ---

def extrair_preco_pagina(page, url):
    """
    Abre a pagina do produto no ML e extrai o preco exato exibido.
    Tenta varios seletores CSS para ser resiliente a mudancas de layout.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Aguarda o preco aparecer
        time.sleep(2)

        # Seletores em ordem de prioridade — o ML usa classes diferentes
        seletores = [
            ".andes-money-amount__fraction",
            ".ui-pdp-price__second-line .andes-money-amount__fraction",
            "[class*='price-tag-fraction']",
            ".price-tag-fraction",
            "[class*='andes-money-amount__fraction']",
        ]

        for seletor in seletores:
            try:
                elemento = page.query_selector(seletor)
                if elemento:
                    texto = elemento.inner_text().strip()
                    # Remove pontos de milhar e converte
                    preco = float(texto.replace(".", "").replace(",", "."))
                    if preco > 0:
                        return preco
            except Exception:
                continue

        # Fallback: busca via JavaScript o preco no JSON da pagina
        preco_js = page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const d = JSON.parse(s.textContent);
                        if (d.offers && d.offers.price) return parseFloat(d.offers.price);
                        if (d.price) return parseFloat(d.price);
                    } catch(e) {}
                }
                return null;
            }
        """)
        if preco_js and float(preco_js) > 0:
            return float(preco_js)

    except PlaywrightTimeout:
        print(f"    timeout ao abrir pagina")
    except Exception as e:
        print(f"    erro no scraping: {e}")

    return None


def buscar_preco_api_fallback(mlb_produto_id, access_token):
    """Fallback: menor preco via API se o scraping falhar."""
    try:
        headers_ml = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(
            f"https://api.mercadolibre.com/products/{mlb_produto_id}/items",
            headers=headers_ml,
            params={"limit": 100},
            timeout=15,
        )
        if resp.status_code == 200:
            resultados = resp.json().get("results", [])
            if resultados:
                item = min(resultados, key=lambda x: x["price"])
                return float(item["price"])
    except Exception:
        pass
    return None


# --- Loop principal ---

def main():
    print(f"\nIniciando coleta: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    access_token, refresh_token = carregar_tokens()
    if not access_token:
        print("Tokens nao encontrados.")
        return

    # Renova token se necessario antes de comecar
    if refresh_token:
        novo_access, novo_refresh = renovar_token(refresh_token)
        if novo_access:
            access_token  = novo_access
            refresh_token = novo_refresh

    wheys = buscar_wheys()
    print(f"Produtos: {len(wheys)}\n")

    sucessos = sem_estoque = erros = 0

    with sync_playwright() as p:
        # Abre navegador headless simulando usuario real
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
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
        )
        page = context.new_page()

        for w in wheys:
            whey_id = w["id"]
            mlb_id  = w["ml_item_id"]
            label   = f"{w['marca']} {w['nome']} {w.get('sabor', '')}"

            print(f">> {label} ({mlb_id})")

            url = f"https://www.mercadolivre.com.br/p/{mlb_id}"
            preco = extrair_preco_pagina(page, url)

            if preco:
                print(f"    [scraping] R${preco:.2f}")
            else:
                # Fallback para API
                preco = buscar_preco_api_fallback(mlb_id, access_token)
                if preco:
                    print(f"    [api fallback] R${preco:.2f}")

            if preco and preco > 0:
                ok = salvar_preco(whey_id, preco, url)
                marcar_disponibilidade(whey_id, True)
                print(f"  {'OK' if ok else 'ERRO SUPABASE'} R${preco:.2f}")
                if ok:
                    sucessos += 1
                else:
                    erros += 1
            else:
                marcar_disponibilidade(whey_id, False)
                print(f"  Sem preco — removido do ranking")
                sem_estoque += 1

            # Delay aleatorio entre 3 e 7 segundos para nao ser bloqueado
            time.sleep(random.uniform(3, 7))

        browser.close()

    print("\n" + "=" * 52)
    print(f"Atualizados: {sucessos} | Sem estoque: {sem_estoque} | Erros: {erros}")
    print(f"Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
