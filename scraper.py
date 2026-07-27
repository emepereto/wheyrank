"""
WHEYRANK — Scraper v13
====================================
- Não depende mais da API autenticada do Mercado Livre para preço/nota
  (os endpoints de catálogo /products/{id} e /products/{id}/items
  retornam "access not granted by applications" para este app).
- Lê a página pública do produto e extrai preço/nota do JSON-LD
  (dados estruturados schema.org que o ML expõe para SEO/Google Shopping),
  com fallback via regex no HTML.
- Mantém a gravação no Supabase igual à versão anterior.
"""

import os
import re
import json
import time
import requests
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

HEADERS_SUPA = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}

HEADERS_PAGINA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

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

# ── Extração de dados da página pública ───────────────────────

def extrair_dados_ld_json(html):
    """
    Procura blocos <script type="application/ld+json"> com @type "Product"
    e extrai o preço (offers.price) e a nota média (aggregateRating.ratingValue).
    """
    preco = None
    nota = None

    blocos = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )

    for bloco in blocos:
        try:
            dados = json.loads(bloco.strip())
        except Exception:
            continue

        candidatos = dados if isinstance(dados, list) else [dados]
        for item in candidatos:
            if not isinstance(item, dict):
                continue

            tipo = item.get("@type", "")
            is_product = ("Product" in tipo) if isinstance(tipo, list) else (tipo == "Product")
            if not is_product:
                continue

            offers = item.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                p = offers.get("price")
                if p is not None:
                    try:
                        preco = float(p)
                    except (TypeError, ValueError):
                        pass

            rating = item.get("aggregateRating")
            if isinstance(rating, dict):
                rv = rating.get("ratingValue")
                if rv is not None:
                    try:
                        nota = round(float(rv), 1)
                    except (TypeError, ValueError):
                        pass

    return preco, nota


def extrair_preco_regex(html):
    """
    Fallback caso o JSON-LD não esteja presente na página.
    Tenta capturar o preço de dois jeitos diferentes usados pelo ML.
    """
    m = re.search(r'"price"\s*:\s*"?(\d+(?:\.\d+)?)"?', html)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    m = re.search(
        r'andes-money-amount__fraction["\'>]*>([\d.]+)<.*?andes-money-amount__cents["\'>]*>(\d+)<',
        html,
        re.DOTALL,
    )
    if m:
        inteiro = m.group(1).replace(".", "")
        centavos = m.group(2)
        try:
            return float(f"{inteiro}.{centavos}")
        except ValueError:
            pass

    return None


def pagina_indica_indisponivel(html):
    padroes = [
        r"produto sem estoque",
        r"sem estoque",
        r"compra indispon[íi]vel",
        r"anúncio pausado",
        r"este produto já foi vendido",
    ]
    for p in padroes:
        if re.search(p, html, re.IGNORECASE):
            return True
    return False

# ── Busca de preço (leitura da página pública) ────────────────

def buscar_preco_ml(mlb_produto_id):
    url = f"https://www.mercadolivre.com.br/p/{mlb_produto_id}"
    try:
        resp = requests.get(url, headers=HEADERS_PAGINA, timeout=20, allow_redirects=True)

        if resp.status_code == 404:
            return None, False, "sem_resultados", None
        if resp.status_code != 200:
            print(f"    [DEBUG] {resp.status_code} em {url}: {resp.text[:200]}")
            return None, False, f"erro_{resp.status_code}", None

        html = resp.text

        preco, nota = extrair_dados_ld_json(html)
        if preco is None:
            preco = extrair_preco_regex(html)

        if preco is None:
            if pagina_indica_indisponivel(html):
                return None, False, "sem_resultados", None
            return None, False, "preco_nao_encontrado", None

        nota_str = f" | nota={nota}" if nota else ""
        print(f"    R${preco:.2f}{nota_str}")

        return preco, True, "ok", nota

    except Exception as e:
        return None, False, f"erro: {e}", None

# ── Main ─────────────────────────────────────────────────────

def main():
    print(f"\nIniciando: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    wheys = buscar_wheys()
    print(f"Produtos: {len(wheys)}\n")

    sucessos = erros = sem_estoque = 0

    for w in wheys:
        label = f"{w['marca']} {w.get('nome','')} {w.get('sabor','')}"
        print(f">> {label} ({w['ml_item_id']})")

        preco, disponivel, motivo, nota = buscar_preco_ml(w["ml_item_id"])

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

        # Pequena pausa para reduzir risco de bloqueio/rate limit
        time.sleep(1.5)

    print("\n" + "=" * 52)
    print(f"Atualizados: {sucessos} | Sem estoque: {sem_estoque} | Erros: {erros}")
    print(f"Finalizado: {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
