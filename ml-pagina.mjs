// Lê o preço direto da página que o link de afiliado abre (o mesmo que o visitante vê).
// A API do Mercado Livre bloqueou /products/{id}/items, /items e o buy box para apps de terceiros
// (403 PolicyAgent desde 23/11/2026), então a fonte confiável passou a ser a própria página.

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';

// Extrai o array JSON que começa logo após `chave` (ex.: '"polycards":'), respeitando strings.
function extrairJSON(html, chave, inicio = 0) {
  const k = html.indexOf(chave, inicio);
  if (k < 0) return null;
  const s = k + chave.length;
  let d = 0;
  for (let i = s; i < html.length; i++) {
    const c = html[i];
    if (c === '"') { i++; while (i < html.length && html[i] !== '"') { if (html[i] === '\\') i++; i++; } continue; }
    if (c === '[' || c === '{') d++;
    else if (c === ']' || c === '}') { d--; if (d === 0) { try { return { valor: JSON.parse(html.slice(s, i + 1)), fim: i }; } catch { return null; } } }
  }
  return null;
}

function precoDoCard(card) {
  const p = card.components?.find(x => x.type === 'price')?.price;
  const v = p?.current_price?.value;
  return typeof v === 'number' ? v : null;
}

/**
 * @returns {Promise<{preco:number, item_id:string, titulo:string, nota:number|null, status:string}>}
 */
export async function precoPelaPagina(linkAfiliado, productId) {
  const r = await fetch(linkAfiliado, { headers: { 'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9' }, redirect: 'follow' });
  if (!r.ok) return { status: `http_${r.status}` };
  if (r.url.includes('account-verification')) return { status: 'bloqueado_verificacao' };
  if (r.url.includes('/lists')) return { status: 'link_quebrado' }; // link de afiliado expirado/produto removido
  const html = await r.text();

  // O produto que o link realmente compartilha manda (pode diferir do ml_item_id salvo no banco)
  const compartilhado = html.match(/"shared_item":\{"id":"(MLB[U]?\d+)"/)?.[1];
  if (compartilhado) productId = compartilhado;

  // Procura em todos os blocos "polycards" o card do produto do link
  let pos = 0, achado = null, primeiro = null;
  for (let n = 0; n < 20; n++) {
    const bloco = extrairJSON(html, '"polycards":', pos);
    if (!bloco) break;
    pos = bloco.fim;
    for (const card of bloco.valor || []) {
      primeiro ||= card;
      const m = card.metadata || {};
      if (productId && (m.product_id === productId || m.id === productId || m.user_product_id === productId)) { achado = card; break; }
    }
    if (achado) break;
  }
  if (!achado) return { status: primeiro ? 'produto_nao_encontrado_na_pagina' : 'sem_cards' };

  const preco = precoDoCard(achado);
  if (!preco) return { status: 'sem_preco_no_card' };
  const rev = achado.components?.find(x => x.type === 'reviews')?.reviews;
  return {
    status: 'ok',
    preco,
    product_id: productId,
    item_id: achado.metadata?.id,
    titulo: achado.components?.find(x => x.type === 'title')?.title?.text,
    nota: typeof rev?.rating_average === 'number' ? Math.round(rev.rating_average * 10) / 10 : null,
  };
}
