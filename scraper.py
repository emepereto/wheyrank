"""
WHEYRANK — Scraper v11
====================================
- Score composto replica ranking do ML
- Logs completos + renovação de token no meio da execução
- Sleep seguro para evitar rate limit
- Coleta nota (rating) do produto no ML
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

_cache_reputacao = {}

# ── Tokens ──────────────────────────────────────────────────

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
        print(f"  Erro ao carregar tokens: {e}")
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
    print("  Renovando token...")
    try:
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
            novo_access  = dados["access_token"]
            novo_refresh = dados.get("refresh_token", refresh_token)
            salvar_tokens(novo_access, novo_refresh)
            print("  Token renovado com sucesso")
            return novo_access, novo_refresh
        print(f"  Erro ao renovar token: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        print(f"  Erro ao renovar token: {e}")
    return None, None

# ── Supabase ─────────────────────────────────────────────────

def buscar_wheys():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"select": "id,nome,marca,sabor,ml_item_id", "ativo": "eq.true"},
    )
    resp.raise_for_status()
    return [w for w in resp.json() if w.get("ml_item_id")]


def salvar_preco(whey_id, preco, url_produto, nota=None):
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/precos",
        headers=HEADERS_SUPA,
        params={"whey_id": f"eq.{whey_id}"},
    )
    payload = {
        "whey_id":     whey_id,
        "plataforma":  "mercadolivre",
        "preco":       preco,
        "url_produto": url_produto,
        "coletado_em": datetime.utcnow().isoformat(),
    }
    if nota is not None:
        payload["nota"] = nota

    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/precos",
        headers=HEADERS_SUPA,
        json=payload,
    )
    return resp.status_code in (200, 201)


def marcar_disponibilidade(whey_id, disponivel):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"id": f"eq.{whey_id}"},
        json={"disponivel": disponivel},
    )

# ── Reputação ────────────────────────────────────────────────



def buscar_reputacao(seller_id, access_token):
    if seller_id in _cache_reputacao:
        return _cache_reputacao[seller_id]

    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/users/{seller_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            dados = resp.json()
            rep   = dados.get("seller_reputation", {})
            result = {
                "level":       rep.get("level_id", ""),
                "total_vendas": rep.get("transactions", {}).get("total", 0),
            }
            _cache_reputacao[seller_id] = result
            return result
    except Exception as e:
        print(f"    Erro reputação seller {seller_id}: {e}")

    result = {"level": "", "total_vendas": 0}
    _cache_reputacao[seller_id] = result
    return result

# ── Nota do produto ──────────────────────────────────────────

def buscar_nota_produto(item_id, mlb_produto_id, access_token):
    """
    Busca a nota/rating via endpoint de reviews do ML.
    Endpoint: GET /reviews/item/{item_id}?catalog_product_id={product_id}
    Retorna float com a nota (ex: 4.7) ou None se não disponível.
    """
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/reviews/item/{item_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"catalog_product_id": mlb_produto_id},
            timeout=10,
        )
        if resp.status_code == 200:
            dados = resp.json()
            nota  = dados.get("rating_average")
            total = dados.get("paging", {}).get("total", 0)
            if nota and total > 0:
                print(f"    Nota: {nota:.1f} ({total} avaliações)")
                return round(float(nota), 1)
            else:
                print(f"    Sem avaliações")
    except Exception as e:
        print(f"    Erro ao buscar nota: {e}")
    return None

# ── Score ────────────────────────────────────────────────────

def calcular_score(item, rep):
    score = 0
    tags  = item.get("tags", [])
    ship  = item.get("shipping", {})
    level = rep["level"]
    total = rep["total_vendas"]

    # Reputação (fator principal)
    if level == "5_green":         score += 100
    elif level == "4_light_green": score += 80
    elif level == "3_yellow":      score += 40
    else:                          score -= 50

    # Logística
    if ship.get("logistic_type") == "fulfillment": score += 70
    if ship.get("free_shipping"):                  score += 40
    if item.get("official_store_id"):              score += 50

    # Volume de vendas
    if total > 1000:   score += 40
    elif total > 100:  score += 20
    elif total > 10:   score += 10

    # Qualidade do anúncio
    if "good_quality_thumbnail" in tags: score += 5
    if "good_quality_picture"   in tags: score += 5

    return score

# ── Busca de preço ───────────────────────────────────────────

def buscar_preco_ml(mlb_produto_id, access_token):
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/products/{mlb_produto_id}/items",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": 30},
            timeout=15,
        )

        if resp.status_code == 401:
            return None, False, "token_expirado", None
        if resp.status_code != 200:
            return None, False, f"erro_{resp.status_code}", None

        resultados = resp.json().get("results", [])
        if not resultados:
            return None, False, "sem_resultados", None

        # Pré-filtra os 15 mais baratos antes de buscar reputação
        candidatos = sorted(resultados, key=lambda x: x["price"])[:15]

        avaliados = []
        for item in candidatos:
            rep = buscar_reputacao(item["seller_id"], access_token)
            if rep["level"] in ("1_red", "2_orange"):
                continue
            score          = calcular_score(item, rep)
            item["_score"] = score
            avaliados.append(item)

        # Fallback se todos foram filtrados
        if not avaliados:
            avaliados = candidatos
            for item in avaliados:
                item["_score"] = 0

        # Ordena por score, pega menor preço entre top terço
        avaliados.sort(key=lambda x: -x["_score"])
        top_n = max(1, len(avaliados) // 3)
        top   = avaliados[:top_n]
        item  = min(top, key=lambda x: x["price"])
        preco = float(item["price"])

        rep   = _cache_reputacao.get(item["seller_id"], {})
        ltype = item.get("shipping", {}).get("logistic_type", "?")
        print(f"    R${preco:.2f} | rep={rep.get('level','?')} | logistic={ltype} | score={item['_score']} | vendas={rep.get('total_vendas','?')}")

        # Descobrir o campo correto do item_id (pode ser "id", "item_id" ou "catalog_listing_id")
        item_id = item.get("item_id")

        # Busca nota do produto usando o item_id do melhor anúncio
        nota = buscar_nota_produto(item_id, mlb_produto_id, access_token) if item_id else None

        return preco, True, "ok", nota

    except Exception as e:
        return None, False, f"erro: {e}", None

# ── Main ─────────────────────────────────────────────────────

def main():
    print(f"\nIniciando: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    access_token, refresh_token = carregar_tokens()
    if not access_token:
        print("Tokens não encontrados.")
        return

    # Renova sempre antes de começar
    if refresh_token:
        novo, novo_r = renovar_token(refresh_token)
        if novo:
            access_token  = novo
            refresh_token = novo_r

    wheys = buscar_wheys()
    print(f"Produtos: {len(wheys)}\n")

    sucessos = erros = sem_estoque = 0

    for w in wheys:
        label = f"{w['marca']} {w.get('nome','')} {w.get('sabor','')}"
        print(f">> {label} ({w['ml_item_id']})")

        preco, disponivel, motivo, nota = buscar_preco_ml(w["ml_item_id"], access_token)

        # Tenta renovar token se expirou no meio
        if motivo == "token_expirado":
            access_token, refresh_token = renovar_token(refresh_token)
            if access_token:
                preco, disponivel, motivo, nota = buscar_preco_ml(w["ml_item_id"], access_token)

        if disponivel and preco:
            url = f"https://www.mercadolivre.com.br/p/{w['ml_item_id']}"
            ok  = salvar_preco(w["id"], preco, url, nota)
            marcar_disponibilidade(w["id"], True)
            nota_str = f" | nota={nota}" if nota else ""
            print(f"  {'OK' if ok else 'ERRO SUPABASE'} R${preco:.2f}{nota_str}")
            if ok: sucessos += 1
            else:  erros += 1
        elif motivo == "sem_resultados":
            marcar_disponibilidade(w["id"], False)
            print(f"  Sem resultados")
            sem_estoque += 1
        else:
            print(f"  Falha: {motivo}")
            erros += 1


    print("\n" + "=" * 52)
    print(f"Atualizados: {sucessos} | Sem estoque: {sem_estoque} | Erros: {erros}")
    print(f"Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
