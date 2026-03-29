"""
WHEYRANK — Scraper v7
======================
- Busca todos os vendedores via /products/{id}/items
- Para cada anuncio, busca o preco exato via /items/{id}/sale_price
- Pega o menor preco real entre todos os vendedores
- Renova token automaticamente
- Roda no Railway a cada 6h: 0 */6 * * *
"""

import os
import time
import requests
from datetime import datetime

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


# --- API ML ---

def buscar_preco_real(item_id, headers_ml):
    """
    Busca o preco exato de venda de um anuncio especifico.
    Endpoint: /items/{id}/sale_price?context=channel_marketplace
    Retorna o preco que o ML efetivamente cobra do comprador.
    """
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/items/{item_id}/sale_price",
            headers=headers_ml,
            params={"context": "channel_marketplace"},
            timeout=10,
        )
        if resp.status_code == 200:
            dados = resp.json()
            preco = dados.get("amount")
            if preco and float(preco) > 0:
                return float(preco)
    except Exception:
        pass

    # Fallback: preco direto do item
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/items/{item_id}",
            headers=headers_ml,
            timeout=10,
        )
        if resp.status_code == 200:
            preco = resp.json().get("price")
            if preco and float(preco) > 0:
                return float(preco)
    except Exception:
        pass

    return None


def buscar_preco_ml(mlb_produto_id, access_token):
    """
    1. Lista todos os vendedores via /products/{id}/items
    2. Para cada um busca o preco real via /items/{id}/sale_price
    3. Retorna o menor preco real encontrado
    """
    headers_ml = {"Authorization": f"Bearer {access_token}"}

    # Busca todos os anuncios do produto
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/products/{mlb_produto_id}/items",
            headers=headers_ml,
            params={"limit": 100},
            timeout=15,
        )

        if resp.status_code == 401:
            return None, False, "token_expirado"
        if resp.status_code != 200:
            return None, False, f"erro_{resp.status_code}"

        resultados = resp.json().get("results", [])
        if not resultados:
            return None, False, "sem_resultados"

    except Exception as e:
        return None, False, f"erro: {e}"

    # Busca o preco real de cada anuncio e pega o menor
    menor_preco = None
    menor_item  = None

    for item in resultados:
        item_id = item["item_id"]
        preco_real = buscar_preco_real(item_id, headers_ml)

        if preco_real:
            if menor_preco is None or preco_real < menor_preco:
                menor_preco = preco_real
                menor_item  = item_id

        time.sleep(0.1)  # Evita rate limit

    if menor_preco:
        print(f"    menor preco real: R${menor_preco:.2f} ({menor_item})")
        return menor_preco, True, "ok"

    # Fallback: preco da API sem sale_price
    item  = min(resultados, key=lambda x: x["price"])
    preco = float(item["price"])
    print(f"    fallback preco API: R${preco:.2f} ({item['item_id']})")
    return preco, True, "ok"


# --- Loop principal ---

def main():
    print(f"\nIniciando coleta: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    access_token, refresh_token = carregar_tokens()
    if not access_token:
        print("Tokens nao encontrados.")
        return

    wheys = buscar_wheys()
    print(f"Produtos: {len(wheys)}\n")

    sucessos = sem_estoque = erros = 0
    token_renovado = False

    for w in wheys:
        whey_id = w["id"]
        mlb_id  = w["ml_item_id"]
        label   = f"{w['marca']} {w['nome']} {w.get('sabor', '')}"

        print(f">> {label} ({mlb_id})")

        preco, disponivel, motivo = buscar_preco_ml(mlb_id, access_token)

        if motivo == "token_expirado" and not token_renovado:
            access_token, refresh_token = renovar_token(refresh_token)
            token_renovado = True
            if access_token:
                preco, disponivel, motivo = buscar_preco_ml(mlb_id, access_token)
            else:
                print("  Nao foi possivel renovar o token.")
                break

        if disponivel and preco:
            url_produto = f"https://www.mercadolivre.com.br/p/{mlb_id}"
            ok = salvar_preco(whey_id, preco, url_produto)
            marcar_disponibilidade(whey_id, True)
            print(f"  {'OK' if ok else 'ERRO SUPABASE'} R${preco:.2f}")
            if ok:
                sucessos += 1
            else:
                erros += 1

        elif motivo == "sem_resultados":
            marcar_disponibilidade(whey_id, False)
            print(f"  Sem resultados")
            sem_estoque += 1

        else:
            print(f"  Falha: {motivo}")
            erros += 1

        time.sleep(1)

    print("\n" + "=" * 52)
    print(f"Atualizados: {sucessos} | Sem estoque: {sem_estoque} | Erros: {erros}")
    print(f"Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
