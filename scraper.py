"""
WHEYRANK — Scraper v2
======================
- Usa a API oficial do ML com o ml_item_id de cada whey
- Trata status: active/paused/closed
- Trata available_quantity (sem estoque = marca indisponível)
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
    """Retorna todos os wheys ativos com ml_item_id."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"select": "id,nome,marca,sabor,ml_item_id", "ativo": "eq.true"},
    )
    resp.raise_for_status()
    return [w for w in resp.json() if w.get("ml_item_id")]


def salvar_preco(whey_id, preco, url_produto):
    """Insere novo registro de preço."""
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
    """Atualiza o campo disponivel no whey."""
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/wheys",
        headers=HEADERS_SUPA,
        params={"id": f"eq.{whey_id}"},
        json={"disponivel": disponivel},
    )


# ─── API Mercado Livre ─────────────────────────────────────────

def buscar_preco_ml(mlb_id: str):
    """
    Chama a API do ML e retorna (preco, disponivel, motivo).
    
    Retornos possíveis:
      (129.90, True,  "ok")
      (None,   False, "sem_estoque")
      (None,   False, "pausado")
      (None,   False, "erro_api")
    """
    try:
        url = f"https://api.mercadolibre.com/items/{mlb_id}"
        resp = requests.get(url, timeout=15)

        if resp.status_code == 404:
            return None, False, "nao_encontrado"

        resp.raise_for_status()
        dados = resp.json()

        status = dados.get("status", "")
        qty    = dados.get("available_quantity", 0)
        preco  = dados.get("price")

        # Anúncio pausado ou fechado
        if status in ("paused", "closed", "inactive"):
            return None, False, f"status_{status}"

        # Sem estoque
        if qty == 0:
            return None, False, "sem_estoque"

        # Tudo ok
        if preco and preco > 0:
            return float(preco), True, "ok"

        return None, False, "preco_invalido"

    except requests.exceptions.Timeout:
        return None, False, "timeout"
    except Exception as e:
        return None, False, f"erro: {e}"


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

        preco, disponivel, motivo = buscar_preco_ml(mlb_id)

        if disponivel and preco:
            # Salva o preço
            url_produto = f"https://www.mercadolivre.com.br/p/{mlb_id}"
            ok = salvar_preco(whey_id, preco, url_produto)
            marcar_disponibilidade(whey_id, True)

            if ok:
                print(f"  ✅ R${preco:.2f} — salvo")
                sucessos += 1
            else:
                print(f"  ❌ R${preco:.2f} — erro ao salvar no Supabase")
                erros += 1

        elif motivo == "sem_estoque":
            marcar_disponibilidade(whey_id, False)
            print(f"  ⚠️  Sem estoque — removido do ranking temporariamente")
            sem_estoque += 1

        elif motivo.startswith("status_"):
            marcar_disponibilidade(whey_id, False)
            print(f"  ⚠️  Anúncio {motivo.replace('status_','')} — removido do ranking")
            sem_estoque += 1

        else:
            print(f"  ❌ Falha: {motivo}")
            erros += 1

        time.sleep(1)  # Respeita o rate limit da API do ML

    print("\n" + "=" * 52)
    print(f"✅ Atualizados: {sucessos}  |  ⚠️  Sem estoque: {sem_estoque}  |  ❌ Erros: {erros}")
    print(f"🏁 Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
