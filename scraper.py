"""
WHEYRANK — Scraper v9
======================
- Filtra vendedores ruins consultando reputação via API
- Descarta "Nao oferece bom atendimento" e vendedores com poucas vendas
- Paginação já no scraper — pega menor preco entre vendedores confiaveis
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

# Cache de reputação de vendedores para não repetir chamadas
_cache_reputacao = {}


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


def buscar_reputacao(seller_id, access_token):
    """
    Consulta a reputação do vendedor via API.
    Retorna o level_id (1_red, 2_orange, 3_yellow, 4_light_green, 5_green)
    e o total de vendas. Usa cache para não repetir chamadas.
    """
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
            trans = rep.get("transactions", {})
            total = trans.get("total", 0)
            result = {"level": level, "total_vendas": total}
            _cache_reputacao[seller_id] = result
            return result
    except Exception:
        pass

    result = {"level": "", "total_vendas": 0}
    _cache_reputacao[seller_id] = result
    return result


def vendedor_aprovado(item, access_token):
    """
    Critérios de aprovação — replica o que o ML usa para destacar vendedores:

    REPROVADO se:
    - Reputação vermelha (1_red) ou laranja (2_orange) — "Nao oferece bom atendimento"
    - Menos de 10 vendas totais — vendedor novo sem histórico

    APROVADO se passar nos critérios acima e tiver:
    - Frete grátis OU fulfillment OU loja oficial
    """
    seller_id = item.get("seller_id")
    ship      = item.get("shipping", {})

    # Consulta reputação
    rep = buscar_reputacao(seller_id, access_token)
    level        = rep["level"]
    total_vendas = rep["total_vendas"]

    # Descarta reputação ruim
    if level in ("1_red", "2_orange"):
        return False, f"reputacao_{level}"

    # Descarta vendedores com menos de 10 vendas
    if total_vendas < 10 and level == "":
        return False, "poucas_vendas"

    # Exige pelo menos frete grátis, fulfillment ou loja oficial
    tem_frete      = ship.get("free_shipping", False)
    tem_fulfillment = ship.get("logistic_type") == "fulfillment"
    e_oficial      = item.get("official_store_id") is not None

    if not (tem_frete or tem_fulfillment or e_oficial):
        return False, "sem_frete_gratis"

    return True, "ok"


def calcular_score(item):
    """Score de prioridade — quanto maior, mais confiável."""
    score = 0
    tags  = item.get("tags", [])
    ship  = item.get("shipping", {})

    if ship.get("logistic_type") == "fulfillment": score += 50
    if item.get("official_store_id"):              score += 30
    if ship.get("free_shipping"):                  score += 20
    if "good_quality_thumbnail" in tags:           score += 5
    if "good_quality_picture"   in tags:           score += 5
    if "immediate_payment"      in tags:           score += 5
    if "cart_eligible"          in tags:           score += 5
    if "user_product_unify"     in tags:           score += 5

    return score


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

        # Filtra por qualidade consultando reputação
        aprovados = []
        for item in resultados:
            ok, motivo = vendedor_aprovado(item, access_token)
            if ok:
                aprovados.append(item)
            time.sleep(0.05)  # Evita rate limit nas chamadas de reputação

        # Se nenhum aprovado, relaxa o filtro e usa todos com frete grátis
        if not aprovados:
            print(f"    Nenhum aprovado — relaxando filtro")
            aprovados = [r for r in resultados if r.get("shipping", {}).get("free_shipping")]

        # Se ainda vazio, usa todos (último recurso)
        if not aprovados:
            aprovados = resultados

        # Ordena por score e pega menor preço entre os melhores
        aprovados.sort(key=lambda x: -calcular_score(x))
        top_n = max(1, len(aprovados) // 3)
        top   = aprovados[:top_n]
        item  = min(top, key=lambda x: x["price"])

        preco = float(item["price"])
        level = _cache_reputacao.get(item.get("seller_id"), {}).get("level", "?")
        ltype = item.get("shipping", {}).get("logistic_type", "?")
        print(f"    R${preco:.2f} | rep={level} | logistic={ltype} | score={calcular_score(item)}")
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
