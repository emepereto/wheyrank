"""
WHEYRANK — Scraper v8
======================
- Filtra vendedores por qualidade (fulfillment, frete gratis, reputacao)
- Pega o menor preco entre vendedores confiaveis
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


def buscar_wheys():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"select": "id,nome,marca,sabor,ml_item_id", "ativo": "eq.true"},
    )
    resp.raise_for_status()
    return [w for w in resp.json() if w.get("ml_item_id")]


def salvar_preco(whey_id, preco, url_produto):
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/precos",
        headers=HEADERS_SUPA,
        params={"whey_id": f"eq.{whey_id}"},
    )
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


def calcular_score(item):
    """
    Calcula um score de qualidade do vendedor igual ao ML usa
    para destacar anúncios. Quanto maior, mais confiável.
    """
    score = 0
    tags  = item.get("tags", [])
    ship  = item.get("shipping", {})

    # Fulfillment (estoque no ML) — máxima confiança
    if ship.get("logistic_type") == "fulfillment":
        score += 50

    # Frete grátis
    if ship.get("free_shipping"):
        score += 20

    # Loja oficial
    if item.get("official_store_id"):
        score += 30

    # Tags de qualidade do ML
    if "good_quality_thumbnail"    in tags: score += 5
    if "good_quality_picture"      in tags: score += 5
    if "immediate_payment"         in tags: score += 5
    if "cart_eligible"             in tags: score += 5
    if "standard_price_by_channel" in tags: score += 5

    return score


def vendedor_confiavel(item):
    """
    Filtro mínimo de qualidade — descarta vendedores ruins.
    Aceita se tiver pelo menos UMA das condições abaixo.
    """
    ship = item.get("shipping", {})
    tags = item.get("tags", [])

    tem_fulfillment   = ship.get("logistic_type") == "fulfillment"
    tem_frete_gratis  = ship.get("free_shipping", False)
    e_loja_oficial    = item.get("official_store_id") is not None
    tem_cart_eligible = "cart_eligible" in tags

    # Exige pelo menos frete grátis ou fulfillment ou loja oficial
    return tem_fulfillment or tem_frete_gratis or e_loja_oficial


def buscar_preco_ml(mlb_produto_id, access_token):
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/products/{mlb_produto_id}/items",
            headers={"Authorization": f"Bearer {access_token}"},
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

        # Filtra vendedores confiáveis
        confiaveis = [r for r in resultados if vendedor_confiavel(r)]

        # Se não sobrar nenhum, usa todos (fallback)
        pool = confiaveis if confiaveis else resultados
        fonte = "confiavel" if confiaveis else "fallback_todos"

        # Ordena por score desc, depois por preço asc
        # Pega o melhor preço entre os top vendedores (score >= mediana)
        pool_com_score = [(calcular_score(r), r) for r in pool]
        pool_com_score.sort(key=lambda x: (-x[0], x[1]["price"]))

        # Considera os top 30% em score para pegar o menor preço entre os bons
        top_n = max(1, len(pool_com_score) // 3)
        top_vendedores = [r for _, r in pool_com_score[:top_n]]
        item  = min(top_vendedores, key=lambda x: x["price"])

        preco = float(item["price"])
        ltype = item.get("shipping", {}).get("logistic_type", "?")
        print(f"    [{fonte}] R${preco:.2f} | logistic={ltype} | score={calcular_score(item)} ({item['item_id']})")
        return preco, True, "ok"

    except Exception as e:
        return None, False, f"erro: {e}"


def main():
    print(f"\nIniciando coleta: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    access_token, refresh_token = carregar_tokens()
    if not access_token:
        print("Tokens nao encontrados.")
        return

    if refresh_token:
        novo, novo_r = renovar_token(refresh_token)
        if novo:
            access_token  = novo
            refresh_token = novo_r

    wheys = buscar_wheys()
    print(f"Produtos: {len(wheys)}\n")

    sucessos = sem_estoque = erros = 0

    for w in wheys:
        whey_id = w["id"]
        mlb_id  = w["ml_item_id"]
        label   = f"{w['marca']} {w['nome']} {w.get('sabor', '')}"
        print(f">> {label} ({mlb_id})")

        preco, disponivel, motivo = buscar_preco_ml(mlb_id, access_token)

        if motivo == "token_expirado":
            access_token, refresh_token = renovar_token(refresh_token)
            if access_token:
                preco, disponivel, motivo = buscar_preco_ml(mlb_id, access_token)

        if disponivel and preco:
            url = f"https://www.mercadolivre.com.br/p/{mlb_id}"
            ok  = salvar_preco(whey_id, preco, url)
            marcar_disponibilidade(whey_id, True)
            print(f"  {'OK' if ok else 'ERRO SUPABASE'} R${preco:.2f}")
            if ok: sucessos += 1
            else:  erros += 1
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
