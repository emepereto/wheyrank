// WheyRank — Scraper v13
// Lê o preço direto da página que o link de afiliado abre (o mesmo que o visitante vê ao clicar).
// Não usa mais a API/tokens do Mercado Livre: desde 23/11/2026 ela responde 403 para preços.
// Uso: SUPABASE_URL=... SUPABASE_KEY=... node scraper.mjs
import fs from 'node:fs';
import { precoPelaPagina } from './ml-pagina.mjs';

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_KEY;
if (!SUPABASE_URL || !SUPABASE_KEY) { console.error('Defina SUPABASE_URL e SUPABASE_KEY'); process.exit(1); }
const H = { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}`, 'Content-Type': 'application/json' };
const dormir = ms => new Promise(r => setTimeout(r, ms));

async function supa(caminho, opts = {}) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${caminho}`, { ...opts, headers: { ...H, ...(opts.headers || {}) } });
  if (!r.ok) throw new Error(`Supabase ${r.status} em ${caminho}: ${(await r.text()).slice(0, 200)}`);
  const t = await r.text();
  return t ? JSON.parse(t) : null;
}

async function ultimoPreco(id) {
  const d = await supa(`precos?select=preco,coletado_em&whey_id=eq.${id}&order=coletado_em.desc&limit=1`);
  return d?.[0] || null;
}

async function salvarPreco(w, r) {
  await supa(`precos?whey_id=eq.${w.id}`, { method: 'DELETE' });
  const payload = {
    whey_id: w.id, plataforma: 'mercadolivre', preco: r.preco,
    url_produto: `https://www.mercadolivre.com.br/p/${r.product_id}`,
    coletado_em: new Date().toISOString(),
  };
  if (r.nota) payload.nota = r.nota;
  await supa('precos', { method: 'POST', body: JSON.stringify(payload) });
  const patch = { disponivel: true };
  if (r.product_id && r.product_id !== w.ml_item_id) patch.ml_item_id = r.product_id; // alinha com o que o link mostra
  await supa(`wheys?id=eq.${w.id}`, { method: 'PATCH', body: JSON.stringify(patch) });
}

const wheys = (await supa('wheys?select=id,nome,marca,sabor,ml_item_id,link_ml&ativo=eq.true&order=id'))
  .filter(w => w.link_ml);
console.log(`Iniciando: ${new Date().toISOString()} | ${wheys.length} produtos\n`);

let ok = 0, bloqueios = 0;
const falhas = [], suspeitos = [];
for (const w of wheys) {
  const label = `${w.marca} ${w.nome} ${w.sabor || ''}`.trim();
  let r;
  try { r = await precoPelaPagina(w.link_ml, w.ml_item_id); }
  catch (e) { r = { status: 'erro_rede: ' + e.message }; }

  if (r.status === 'ok') {
    const ant = await ultimoPreco(w.id);
    const ratio = ant ? r.preco / Number(ant.preco) : 1;
    if (ratio < 0.6 || ratio > 1.7) {
      // Variação absurda: provavelmente o link caiu num kit/outro tamanho. Não salva, só avisa.
      suspeitos.push(`${label}: R$${r.preco} (antes R$${ant.preco}) — "${r.titulo}"`);
      console.log(`?? ${label}: R$${r.preco} vs R$${ant.preco} — ignorado`);
    } else {
      await salvarPreco(w, r);
      ok++;
      console.log(`OK ${label}: R$${r.preco.toFixed(2)}`);
    }
  } else {
    if (r.status === 'bloqueado_verificacao' || r.status.startsWith('http_4')) bloqueios++;
    falhas.push(`${label} (${w.ml_item_id}): ${r.status}`);
    console.log(`XX ${label}: ${r.status}`);
    const ant = await ultimoPreco(w.id);
    const dias = ant ? (Date.now() - new Date(ant.coletado_em + (ant.coletado_em.endsWith('Z') ? '' : 'Z'))) / 864e5 : 999;
    if (dias > 7) {
      await supa(`wheys?id=eq.${w.id}`, { method: 'PATCH', body: JSON.stringify({ disponivel: false }) });
      console.log('   preço com mais de 7 dias: fora do ranking');
    }
  }
  await dormir(1500);
}

// ── Creatinas (tabela própria, preço gravado direto na linha) ──
const creatinas = (await supa('creatinas?select=id,nome,marca,peso_g,ml_item_id,link_ml,preco_atual&ativo=eq.true&order=id'))
  .filter(c => c.link_ml);
let okCr = 0;
for (const c of creatinas) {
  const label = `${c.marca} ${c.nome} ${c.peso_g}g`;
  let r;
  try { r = await precoPelaPagina(c.link_ml, c.ml_item_id); }
  catch (e) { r = { status: 'erro_rede: ' + e.message }; }
  if (r.status === 'ok') {
    const ratio = c.preco_atual ? r.preco / Number(c.preco_atual) : 1;
    if (ratio < 0.6 || ratio > 1.7) {
      suspeitos.push(`${label}: R$${r.preco} (antes R$${c.preco_atual}) — "${r.titulo}"`);
    } else {
      const patch = { preco_atual: r.preco, preco_atualizado_em: new Date().toISOString(), disponivel: true };
      if (r.nota) patch.nota = r.nota;
      if (r.product_id && r.product_id !== c.ml_item_id) patch.ml_item_id = r.product_id;
      await supa(`creatinas?id=eq.${c.id}`, { method: 'PATCH', body: JSON.stringify(patch) });
      okCr++;
      console.log(`OK ${label}: R$${r.preco.toFixed(2)}`);
    }
  } else {
    if (r.status === 'bloqueado_verificacao' || r.status.startsWith('http_4')) bloqueios++;
    falhas.push(`${label} (${c.ml_item_id}): ${r.status}`);
    console.log(`XX ${label}: ${r.status}`);
  }
  await dormir(1500);
}

// Diagnóstico: tipo da chave usada (nunca a chave em si)
let tipoChave = 'desconhecido';
if (SUPABASE_KEY.startsWith('sb_secret_')) tipoChave = 'secret';
else if (SUPABASE_KEY.startsWith('sb_publishable_')) tipoChave = 'publishable (pública!)';
else { try { tipoChave = JSON.parse(Buffer.from(SUPABASE_KEY.split('.')[1], 'base64url').toString()).role; } catch {} }

const resumo = `### Scraper\nWheys: ${ok} de ${wheys.length} · Creatinas: ${okCr} de ${creatinas.length} · chave Supabase: **${tipoChave}**\n\n` +
  (falhas.length ? `**Falhas**\n${falhas.map(x => `- ${x}`).join('\n')}\n\n` : '') +
  (suspeitos.length ? `**Preço suspeito (não salvo)**\n${suspeitos.map(x => `- ${x}`).join('\n')}\n` : '');
console.log('\n' + resumo);
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, resumo);

// Se o ML bloqueou quase tudo, falha o job para aparecer em vermelho no GitHub
if (bloqueios > (wheys.length + creatinas.length) / 2) { console.error('Mercado Livre bloqueou a maioria das páginas.'); process.exit(2); }
