"""
WHEYRANK — Scraper v5
======================
- Usa /products/{MLB_ID}/items para listar todos os vendedores
- Filtra pelo anúncio da loja oficial (official_store_id != null)
- Salva o item_id da loja oficial no banco para o link direto
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


# ─── Tokens ───────────────────────────────────────────────────

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
        print(f"  ⚠️  Erro ao carregar tokens: {e}")
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
    print("🔄 Renovando access token...")
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
        print("  ✅ Token renovado")
        return novo_access, novo_refresh
    print(f"  ❌ Erro ao renovar: {resp.text}")
    return None, None


# ─── Supabase ─────────────────────────────────────────────────

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


# ─── API ML ───────────────────────────────────────────────────

def buscar_preco_ml(mlb_produto_id, access_token):
    """
    Busca o preço da loja oficial usando o ID de produto.
    Endpoint: /products/{id}/items
    Retorna (preco, item_id, disponivel, motivo)
    """
    try:
        url  = f"https://api.mercadolibre.com/products/{mlb_produto_id}/items"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )

        if resp.status_code == 401:
            return None, None, False, "token_expirado"
        if resp.status_code == 404:
            return None, None, False, "nao_encontrado"

        resp.raise_for_status()
        resultados = resp.json().get("results", [])

        if not resultados:
            return None, None, False, "sem_resultados"

        # Sempre pega o menor preço entre todos os vendedores
        # Assim o preço no site bate com o que o ML mostra ao clicar
        item    = min(resultados, key=lambda x: x["price"])
        preco   = float(item["price"])
        item_id = item["item_id"]

        print(f"    [menor_preco] {item_id} → R${preco:.2f}")
        return preco, item_id, True, "ok"

    except requests.exceptions.Timeout:
        return None, None, False, "timeout"
    except Exception as e:
        return None, None, False, f"erro: {e}"


# ─── Loop principal ────────────────────────────────────────────

def main():
    print(f"\n🕐 Iniciando coleta: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    access_token, refresh_token = carregar_tokens()
    if not access_token:
        print("❌ Tokens não encontrados no banco.")
        return

    wheys = buscar_wheys()
    print(f"📦 {len(wheys)} produto(s) para verificar\n")

    sucessos = sem_estoque = erros = 0
    token_renovado = False

    for w in wheys:
        whey_id = w["id"]
        mlb_id  = w["ml_item_id"]
        label   = f"{w['marca']} {w['nome']} {w.get('sabor','')}"

        print(f"🔍 {label} ({mlb_id})")

        preco, item_id, disponivel, motivo = buscar_preco_ml(mlb_id, access_token)

        # Token expirou — renova e tenta de novo
        if motivo == "token_expirado" and not token_renovado:
            access_token, refresh_token = renovar_token(refresh_token)
            token_renovado = True
            if access_token:
                preco, item_id, disponivel, motivo = buscar_preco_ml(mlb_id, access_token)
            else:
                print("  ❌ Não foi possível renovar o token.")
                break

        if disponivel and preco:
            # Usa link de afiliado da tabela wheys (cadastrado manualmente)
            url_produto = f"https://www.mercadolivre.com.br/p/{mlb_id}"
            ok = salvar_preco(whey_id, preco, url_produto)
            marcar_disponibilidade(whey_id, True)
            if ok:
                print(f"  ✅ R${preco:.2f} — salvo")
                sucessos += 1
            else:
                print(f"  ❌ Erro ao salvar no Supabase")
                erros += 1

        elif motivo in ("sem_resultados", "sem_estoque") or motivo.startswith("status_"):
            marcar_disponibilidade(whey_id, False)
            print(f"  ⚠️  {motivo} — removido do ranking temporariamente")
            sem_estoque += 1

        else:
            print(f"  ❌ Falha: {motivo}")
            erros += 1

        time.sleep(1)

    print("\n" + "=" * 52)
    print(f"✅ Atualizados: {sucessos}  |  ⚠️  Sem estoque: {sem_estoque}  |  ❌ Erros: {erros}")
    print(f"🏁 Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
