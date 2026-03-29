"""
WHEYRANK — Scraper v6
======================
- Usa /products/{id} para pegar o preco exato que o ML exibe na pagina
- Renova o access_token automaticamente com o refresh_token
- Roda no Railway a cada 6h via Cron: 0 */6 * * *
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
        print("  Token renovado com sucesso")
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

def buscar_preco_ml(mlb_produto_id, access_token):
    """
    Tenta 3 estrategias em ordem para pegar o preco mais preciso:
    1. /products/{id} — preco destacado pelo ML na pagina do produto
    2. /products/{id}/items ordenado por preco — menor preco disponivel
    3. Fallback: primeiro resultado disponivel
    """
    headers_ml = {"Authorization": f"Bearer {access_token}"}

    # Estrategia 1: endpoint de produto direto
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/products/{mlb_produto_id}",
            headers=headers_ml,
            timeout=15,
        )

        if resp.status_code == 401:
            return None, False, "token_expirado"

        if resp.status_code == 200:
            dados = resp.json()
            # buy_box_winner e o preco que o ML destaca na pagina
            buy_box = dados.get("buy_box_winner", {})
            preco = buy_box.get("price") if buy_box else None

            if not preco:
                preco = dados.get("price")

            if preco and float(preco) > 0:
                print(f"    [produto] preco destacado ML: R${float(preco):.2f}")
                return float(preco), True, "ok"

    except Exception as e:
        print(f"    estrategia 1 falhou: {e}")

    # Estrategia 2: lista todos os itens e pega o menor
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/products/{mlb_produto_id}/items",
            headers=headers_ml,
            params={"limit": 100},
            timeout=15,
        )

        if resp.status_code == 401:
            return None, False, "token_expirado"

        if resp.status_code == 200:
            resultados = resp.json().get("results", [])
            if resultados:
                item  = min(resultados, key=lambda x: x["price"])
                preco = float(item["price"])
                print(f"    [items] menor preco: R${preco:.2f} ({item['item_id']})")
                return preco, True, "ok"

    except Exception as e:
        print(f"    estrategia 2 falhou: {e}")

    return None, False, "sem_resultados"


# --- Loop principal ---

def main():
    print(f"\n Iniciando coleta: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    access_token, refresh_token = carregar_tokens()
    if not access_token:
        print("Tokens nao encontrados no banco.")
        return

    wheys = buscar_wheys()
    print(f"Produtos para verificar: {len(wheys)}\n")

    sucessos = sem_estoque = erros = 0
    token_renovado = False

    for w in wheys:
        whey_id = w["id"]
        mlb_id  = w["ml_item_id"]
        label   = f"{w['marca']} {w['nome']} {w.get('sabor', '')}"

        print(f">> {label} ({mlb_id})")

        preco, disponivel, motivo = buscar_preco_ml(mlb_id, access_token)

        # Token expirou — renova e tenta de novo
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
            if ok:
                print(f"  OK R${preco:.2f} salvo")
                sucessos += 1
            else:
                print(f"  Erro ao salvar no Supabase")
                erros += 1

        elif motivo == "sem_resultados":
            marcar_disponibilidade(whey_id, False)
            print(f"  Sem resultados — removido do ranking")
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
