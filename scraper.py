"""
WHEYRANK — Scraper v4
======================
- Usa o access_token diretamente da variável de ambiente ML_TOKEN
- Quando o token expirar (6h), o Railway basta atualizar a variável
- Solução simples e robusta sem depender de refresh_token
- Roda no Railway a cada 6h via Cron: 0 */6 * * *
"""
 
import os
import time
import requests
from datetime import datetime
 
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ML_TOKEN     = os.environ.get("ML_TOKEN", "")
 
HEADERS_SUPA = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
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
        resp = requests.get(
            f"https://api.mercadolibre.com/items/{mlb_id}",
            headers={"Authorization": f"Bearer {ML_TOKEN}"},
            timeout=15,
        )
 
        if resp.status_code == 401:
            return None, False, "token_expirado"
        if resp.status_code == 404:
            return None, False, "nao_encontrado"
        if resp.status_code == 403:
            return None, False, "forbidden"
 
        resp.raise_for_status()
        dados = resp.json()
 
        status = dados.get("status", "")
        qty    = dados.get("available_quantity", 0)
        preco  = dados.get("price")
 
        if status in ("paused", "closed", "inactive"):
            return None, False, f"status_{status}"
        if qty == 0:
            return None, False, "sem_estoque"
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
 
    if not ML_TOKEN:
        print("❌ ML_TOKEN não configurado nas variáveis do Railway.")
        return
 
    wheys = buscar_wheys()
    print(f"📦 {len(wheys)} produto(s) para verificar\n")
 
    sucessos = sem_estoque = erros = token_expirado = 0
 
    for w in wheys:
        whey_id = w["id"]
        mlb_id  = w["ml_item_id"]
        label   = f"{w['marca']} {w['nome']} {w.get('sabor', '')}"
 
        print(f"🔍 {label} ({mlb_id})")
 
        preco, disponivel, motivo = buscar_preco_ml(mlb_id)
 
        if motivo == "token_expirado":
            print("  ❌ Token expirado — atualize ML_TOKEN nas variáveis do Railway")
            token_expirado += 1
            continue
 
        if disponivel and preco:
            url_produto = f"https://www.mercadolivre.com.br/p/{mlb_id}"
            ok = salvar_preco(whey_id, preco, url_produto)
            marcar_disponibilidade(whey_id, True)
            if ok:
                print(f"  ✅ R${preco:.2f} — salvo")
                sucessos += 1
            else:
                print(f"  ❌ Erro ao salvar no Supabase")
                erros += 1
 
        elif motivo in ("sem_estoque",) or motivo.startswith("status_"):
            marcar_disponibilidade(whey_id, False)
            print(f"  ⚠️  {motivo} — removido do ranking temporariamente")
            sem_estoque += 1
 
        else:
            print(f"  ❌ Falha: {motivo}")
            erros += 1
 
        time.sleep(1)
 
    print("\n" + "=" * 52)
    if token_expirado > 0:
        print(f"⚠️  TOKEN EXPIRADO — Atualize ML_TOKEN no Railway:")
        print(f"   1. Gere novo code em: https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=4315621679445724&redirect_uri=https://wheyrank-tau.vercel.app/")
        print(f"   2. Troque por token em: reqbin.com/curl")
        print(f"   3. Atualize ML_TOKEN em Railway → Variables")
    print(f"✅ Atualizados: {sucessos}  |  ⚠️  Sem estoque: {sem_estoque}  |  ❌ Erros: {erros}")
    print(f"🏁 Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")
 
 
if __name__ == "__main__":
    main()
