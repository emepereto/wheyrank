"""
WHEYRANK — Scraper v10 (ML-like ranking)
========================================
- Replica lógica do Mercado Livre (ranking por score, não filtro rígido)
- Remove apenas vendedores MUITO ruins
- Prioriza reputação, FULL, frete grátis e preço
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

# ========================= TOKENS =========================

def carregar_tokens():
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/config",
            headers=HEADERS_SUPA,
            params={"select": "chave,valor"},
        )
        dados = {r["chave"]: r["valor"] for r in resp.json()}
        return dados.get("ml_access_token"), dados.get("ml_refresh_token")
    except:
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
        salvar_tokens(dados["access_token"], dados.get("refresh_token", refresh_token))
        return dados["access_token"], dados.get("refresh_token", refresh_token)
    return None, None

# ========================= DATA =========================

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
            "whey_id": whey_id,
            "plataforma": "mercadolivre",
            "preco": preco,
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

# ========================= REPUTAÇÃO =========================

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
            level = rep.get("level_id", "")
            total = rep.get("transactions", {}).get("total", 0)

            result = {"level": level, "total_vendas": total}
            _cache_reputacao[seller_id] = result
            return result
    except:
        pass

    return {"level": "", "total_vendas": 0}

# ========================= FILTRO =========================

def vendedor_aprovado(item, access_token):
    """
    Agora só remove vendedores MUITO ruins (igual ML)
    """
    seller_id = item.get("seller_id")
    rep = buscar_reputacao(seller_id, access_token)

    if rep["level"] in ("1_red", "2_orange"):
        return False, "reputacao_ruim"

    return True, "ok"

# ========================= SCORE =========================

def calcular_score(item, reputacao):
    score = 0
    tags  = item.get("tags", [])
    ship  = item.get("shipping", {})

    level = reputacao["level"]
    total = reputacao["total_vendas"]

    # 🔥 REPUTAÇÃO (mais importante)
    if level == "5_green":         score += 100
    elif level == "4_light_green": score += 80
    elif level == "3_yellow":      score += 40
    else:                          score -= 50

    # 📦 FULL
    if ship.get("logistic_type") == "fulfillment":
        score += 70

    # 🚚 Frete grátis
    if ship.get("free_shipping"):
        score += 40

    # 🏪 Loja oficial
    if item.get("official_store_id"):
        score += 50

    # 📊 Volume de vendas (SEM BLOQUEIO)
    if total > 1000: score += 40
    elif total > 100: score += 20
    elif total > 10: score += 10

    # 🏷️ Qualidade
    if "good_quality_thumbnail" in tags: score += 5
    if "good_quality_picture" in tags:   score += 5

    return score

# ========================= BUSCA =========================

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

        resultados = resp.json().get("results", [])
        if not resultados:
            return None, False, "sem_resultados"

        avaliados = []

        for item in resultados:
            ok, _ = vendedor_aprovado(item, access_token)
            if not ok:
                continue

            rep = buscar_reputacao(item["seller_id"], access_token)
            score = calcular_score(item, rep)

            item["_score"] = score
            avaliados.append(item)

            time.sleep(0.03)

        if not avaliados:
            avaliados = resultados

        # 🔥 ORDENA POR SCORE (igual ML)
        avaliados.sort(key=lambda x: -x["_score"])

        # 🔥 PEGA TOP TERÇO
        top_n = max(1, len(avaliados) // 3)
        top   = avaliados[:top_n]

        # 🔥 MENOR PREÇO ENTRE OS MELHORES
        item = min(top, key=lambda x: x["price"])

        preco = float(item["price"])

        print(f"    R${preco:.2f} | score={item['_score']}")

        return preco, True, "ok"

    except Exception as e:
        return None, False, f"erro: {e}"

# ========================= MAIN =========================

def main():
    print(f"\nIniciando: {datetime.now()}")
    print("=" * 50)

    access_token, refresh_token = carregar_tokens()
    if not access_token:
        print("Sem token")
        return

    if refresh_token:
        novo, refresh_token = renovar_token(refresh_token)
        if novo:
            access_token = novo

    wheys = buscar_wheys()

    for w in wheys:
        print(f">> {w['nome']}")

        preco, disponivel, motivo = buscar_preco_ml(w["ml_item_id"], access_token)

        if disponivel and preco:
            url = f"https://www.mercadolivre.com.br/p/{w['ml_item_id']}"
            salvar_preco(w["id"], preco, url)
            marcar_disponibilidade(w["id"], True)
            print(f"  OK R${preco:.2f}")
        else:
            marcar_disponibilidade(w["id"], False)
            print(f"  Falha: {motivo}")

        time.sleep(1)

    print("\nFinalizado\n")


if __name__ == "__main__":
    main()
