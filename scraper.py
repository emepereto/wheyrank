"""
WHEYRANK — Scraper v2.1
======================
- Corrige erro 403 da API do ML (headers obrigatórios)
- Trata status: active/paused/closed
- Trata available_quantity
- Usa permalink correto do produto
- Roda no Railway a cada 6h via Cron: 0 */6 * * *
"""

import os
import time
import requests
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

HEADERS_SUPA = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


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


def marcar_disponibilidade(whey_id, disponivel: bool):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"id": f"eq.{whey_id}"},
        json={"disponivel": disponivel},
    )


# ─── API Mercado Livre ─────────────────────────────────────────

def buscar_preco_ml(mlb_id: str):
    try:
        url = f"https://api.mercadolibre.com/items/{mlb_id}"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }

        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 404:
            return None, False, "nao_encontrado"

        if resp.status_code == 403:
            return None, False, "bloqueado_403"

        resp.raise_for_status()
        dados = resp.json()

        status = dados.get("status", "")
        qty    = dados.get("available_quantity", 0)
        preco  = dados.get("price")
        link   = dados.get("permalink")

        # Status inválido
        if status in ("paused", "closed", "inactive"):
            return None, False, f"status_{status}"

        # Sem estoque
        if qty == 0:
            return None, False, "sem_estoque"

        # Preço válido
        if preco and preco > 0:
            if not link:
                link = f"https://produto.mercadolivre.com.br/{mlb_id}"
            return float(preco), True, "ok", link

        return None, False, "preco_invalido", None

    except requests.exceptions.Timeout:
        return None, False, "timeout", None
    except Exception as e:
        return None, False, f"erro: {e}", None


# ─── Loop principal ────────────────────────────────────────────

def main():
    print(f"\n🕐 Iniciando coleta: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    wheys = buscar_wheys()
    print(f"📦 {len(wheys)} produto(s) para verificar\n")

    sucessos = 0
    sem_estoque = 0
    erros = 0

    for w in wheys:
        whey_id  = w["id"]
        mlb_id   = w["ml_item_id"]
        label    = f"{w['marca']} {w['nome']} {w.get('sabor','')}"

        print(f"🔍 {label} ({mlb_id})")

        preco, disponivel, motivo, link = buscar_preco_ml(mlb_id)

        if motivo == "bloqueado_403":
            print("  ❌ Bloqueado pela API (403) — provável limitação do ML")
            erros += 1

        elif disponivel and preco:
            ok = salvar_preco(whey_id, preco, link)
            marcar_disponibilidade(whey_id, True)

            if ok:
                print(f"  ✅ R${preco:.2f} — salvo")
                sucessos += 1
            else:
                print(f"  ❌ R${preco:.2f} — erro ao salvar no Supabase")
                erros += 1

        elif motivo == "sem_estoque":
            marcar_disponibilidade(whey_id, False)
            print("  ⚠️  Sem estoque — removido do ranking")
            sem_estoque += 1

        elif motivo.startswith("status_"):
            marcar_disponibilidade(whey_id, False)
            print(f"  ⚠️  Anúncio {motivo.replace('status_','')} — removido")
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
