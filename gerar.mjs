// WheyRank — gerador de páginas estáticas (roda no GitHub Actions após o scraper)
// - Escreve o ranking direto no HTML da home (Google passa a "ver" os produtos)
// - Injeta "Top 3 hoje" com links de afiliado nos artigos
// - Gera páginas por marca, por faixa de preço e comparativos em /whey/<slug>
// - Regenera o sitemap.xml
// Uso: SUPABASE_URL=... SUPABASE_KEY=... node gerar.mjs
import fs from 'node:fs';
import path from 'node:path';

const SITE = 'https://www.wheyrank.com.br';
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_KEY;
const META = 24;              // g de proteína usados no cálculo padrão (igual à home)
const DIAS_FRESCO = 30;       // produtos com preço mais velho que isso ficam fora das páginas geradas
const FAIXA = 150;            // página "melhor whey até R$X"
const COMPARATIVOS = [
  ['Black Skull', 'Max Titanium'],
  ['Max Titanium', 'Growth Supplements'],
  ['Black Skull', 'Growth Supplements'],
  ['Integralmedica', 'Black Skull'],
  ['Integralmedica', 'Max Titanium'],
  ['Optimum Nutrition', 'Max Titanium'],
  ['Dux Nutrition', 'Growth Supplements'],
  ['Vitafor', 'Max Titanium'],
  ['Probiótica', 'Integralmedica'],
];

if (!SUPABASE_URL || !SUPABASE_KEY) { console.error('Defina SUPABASE_URL e SUPABASE_KEY'); process.exit(1); }

// ── Helpers ────────────────────────────────────────────────
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const brl = n => 'R$' + Number(n).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const slug = s => String(s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const dataBR = d => new Date(d).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' });
const hoje = new Date();
const hojeISO = hoje.toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' });
const mesAno = hoje.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric', timeZone: 'America/Sao_Paulo' });
const MesAno = mesAno.charAt(0).toUpperCase() + mesAno.slice(1);
const nomeProd = w => `${w.nome} ${w.marca}${w.sabor ? ' ' + w.sabor : ''}`;

function substituir(html, marca, conteudo) {
  const ini = `<!-- GERADO:${marca} -->`, fim = `<!-- /GERADO:${marca} -->`;
  const a = html.indexOf(ini), b = html.indexOf(fim);
  if (a < 0 || b < 0) throw new Error(`Marcador ${marca} não encontrado`);
  return html.slice(0, a + ini.length) + '\n' + conteudo + '\n' + html.slice(b);
}

// ── Dados ──────────────────────────────────────────────────
const resp = await fetch(`${SUPABASE_URL}/rest/v1/ranking_wheys?select=*`, {
  headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` },
});
if (!resp.ok) { console.error('Supabase HTTP', resp.status); process.exit(1); }
const brutos = await resp.json();
if (!Array.isArray(brutos) || brutos.length < 5) { console.error('Poucos dados, abortando para não publicar página vazia'); process.exit(1); }

const todos = brutos
  .filter(w => w.preco_atual && w.prot_por_dose && w.num_doses)
  .map(w => {
    const preco = Number(w.preco_atual);
    const custo = (preco / w.num_doses) * (META / w.prot_por_dose);
    const idade = (hoje - new Date(w.preco_atualizado_em)) / 864e5;
    return { ...w, preco, custo, perc: Math.round((w.prot_por_dose / w.dose_g) * 100), fresco: w.disponivel !== false && idade <= DIAS_FRESCO };
  })
  .sort((a, b) => a.custo - b.custo);
const frescos = todos.filter(w => w.fresco);
const ultimaColeta = todos.map(w => w.preco_atualizado_em).filter(Boolean).sort().pop();

// ── Blocos reutilizáveis ───────────────────────────────────
const btnML = (w, txt = 'Ver no Mercado Livre →') => w.link_ml
  ? `<a href="${esc(w.link_ml)}" target="_blank" rel="sponsored noopener" class="btn-ml" data-produto="${esc(nomeProd(w))}">${txt}</a>`
  : '';

const SCRIPT_GA = `<script>
document.addEventListener('click',function(e){var b=e.target.closest('.btn-ml');if(!b||typeof gtag!=='function')return;
gtag('event','clique_mercado_livre',{event_category:'compra',event_label:b.dataset.produto||document.title,value:1});});
</script>`;

function tabela(lista, { mostrarPos = true } = {}) {
  return `<div class="tabela-wrap"><table class="tabela">
<thead><tr>${mostrarPos ? '<th>#</th>' : ''}<th>Produto</th><th>Pote</th><th>Proteína</th><th>Custo p/ ${META}g prot</th><th></th></tr></thead>
<tbody>
${lista.map((w, i) => `<tr>${mostrarPos ? `<td class="pos">${i + 1}º</td>` : ''}<td><strong>${esc(nomeProd(w))}</strong><br><small>${w.peso_g}g · ${w.prot_por_dose}g prot/dose de ${w.dose_g}g</small></td><td>${brl(w.preco)}</td><td>${w.perc}%</td><td class="custo">${brl(w.custo)}</td><td>${btnML(w, 'Comprar →')}</td></tr>`).join('\n')}
</tbody></table></div>
<p class="nota-tab">Preços do Mercado Livre coletados em ${dataBR(ultimaColeta)}; podem variar. Custo = preço do pote ÷ nº de doses × (${META}g ÷ proteína por dose).</p>`;
}

function top3Box(lista, titulo = `Top 3 custo-benefício hoje`) {
  const t = lista.slice(0, 3);
  const medalha = ['🥇', '🥈', '🥉'];
  return `<div class="top3" style="background:#18191d;border:1px solid rgba(200,241,53,.3);border-radius:12px;padding:16px 18px;margin:32px 0;">
  <div style="font-family:'Bebas Neue',sans-serif;font-size:20px;color:#c8f135;letter-spacing:.5px;margin-bottom:10px;">${titulo}</div>
  ${t.map((w, i) => `<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-top:${i ? '1px solid #2e2f35' : 'none'};flex-wrap:wrap;">
    <span style="font-size:20px;">${medalha[i]}</span>
    <span style="flex:1;min-width:160px;color:#e8e9ec;font-size:14px;font-weight:600;">${esc(nomeProd(w))}<br><span style="color:#7a7c84;font-size:12px;font-weight:400;">${brl(w.preco)} · ${brl(w.custo)} por ${META}g de proteína</span></span>
    ${w.link_ml ? `<a href="${esc(w.link_ml)}" target="_blank" rel="sponsored noopener" class="btn-ml" data-produto="${esc(nomeProd(w))}" style="background:#ffe600;color:#111;font-weight:700;font-size:12px;padding:8px 14px;border-radius:6px;text-decoration:none;white-space:nowrap;">Ver no Mercado Livre →</a>` : ''}
  </div>`).join('\n  ')}
  <div style="color:#7a7c84;font-size:11px;margin-top:8px;">Preços de ${dataBR(ultimaColeta)}. Links de afiliado: você paga o mesmo e apoia o site. <a href="/" style="color:#c8f135;">Ver ranking completo</a></div>
</div>
${SCRIPT_GA}`;
}

const faqHTML = faqs => `<h2>Perguntas frequentes</h2>\n${faqs.map(f => `<h3>${esc(f.q)}</h3>\n<p>${f.a}</p>`).join('\n')}`;
const faqLD = faqs => ({
  '@type': 'FAQPage',
  mainEntity: faqs.map(f => ({ '@type': 'Question', name: f.q, acceptedAnswer: { '@type': 'Answer', text: f.a.replace(/<[^>]+>/g, '') } })),
});
const itemListLD = (lista, nome) => ({
  '@type': 'ItemList', name: nome,
  itemListElement: lista.slice(0, 10).map((w, i) => ({
    '@type': 'ListItem', position: i + 1,
    item: {
      '@type': 'Product', name: nomeProd(w), brand: { '@type': 'Brand', name: w.marca },
      offers: { '@type': 'Offer', price: w.preco.toFixed(2), priceCurrency: 'BRL', availability: 'https://schema.org/InStock', url: w.url_atual || w.link_ml },
    },
  })),
});
const ldScript = objs => `<script type="application/ld+json">${JSON.stringify({ '@context': 'https://schema.org', '@graph': objs }).replace(/</g, '\\u003c')}</script>`;

// ── Template de página gerada ──────────────────────────────
const CSS = fs.readFileSync('artigos/como-escolher-whey-proteina-custo-beneficio.html', 'utf8').match(/<style>([\s\S]*?)<\/style>/)[1] + `
h3 { font-size: 15px; color: var(--text); margin: 18px 0 6px; }
.tabela-wrap { overflow-x: auto; margin: 16px 0 6px; }
.tabela { width: 100%; border-collapse: collapse; font-size: 13px; }
.tabela th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--border); }
.tabela td { padding: 9px 8px; border-bottom: 1px solid var(--border); color: var(--muted); vertical-align: middle; }
.tabela td strong { color: var(--text); }
.tabela td.pos { font-family: var(--font-display); font-size: 18px; color: var(--accent); }
.tabela td.custo { color: var(--accent); font-weight: 700; white-space: nowrap; }
.btn-ml { display: inline-block; font-size: 11px; font-weight: 700; padding: 6px 12px; border-radius: 6px; text-decoration: none; background: #ffe600; color: #111; white-space: nowrap; }
.nota-tab { font-size: 11px; }
.links-rel { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.links-rel a { font-size: 12px; color: var(--text); background: var(--bg2); border: 1px solid var(--border); border-radius: 20px; padding: 4px 12px; text-decoration: none; }
.links-rel a:hover { border-color: var(--accent); }`;

function pagina({ url, titulo, descricao, tag, h1, corpo, ld }) {
  return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<!-- Gerado automaticamente por gerar.mjs — não edite à mão -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-V90KSFVZ2G"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-V90KSFVZ2G');</script>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${esc(titulo)}</title>
<meta name="description" content="${esc(descricao)}">
<link rel="canonical" href="${SITE}${url}">
<link rel="icon" type="image/png" href="/favicon.png">
<meta property="og:title" content="${esc(titulo)}">
<meta property="og:description" content="${esc(descricao)}">
<meta property="og:type" content="article">
<meta property="og:url" content="${SITE}${url}">
<meta property="og:image" content="${SITE}/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>${CSS}</style>
${ldScript(ld)}
</head>
<body>
<header><a class="logo" href="/"><em>WHEY</em><span>RANK</span></a></header>
<div class="article-wrap">
  <div class="article-tag">${esc(tag)}</div>
  <h1>${h1}</h1>
  <div class="article-meta">Atualizado em ${dataBR(ultimaColeta)} com preços do Mercado Livre</div>
${corpo}
  <div class="cta-box">
    <h3>Compare com todas as marcas</h3>
    <p>O ranking completo calcula o custo real de cada whey para a sua meta de proteína.</p>
    <a href="/" class="cta-btn">Ver ranking completo →</a>
  </div>
</div>
<footer><p>Links de afiliado: ao comprar, você apoia o site sem pagar nada a mais.</p><a href="/">← Voltar ao WheyRank</a></footer>
${SCRIPT_GA}
</body>
</html>
`;
}

// ── Páginas geradas ────────────────────────────────────────
const geradas = []; // { url, titulo, curto }
const porMarca = {};
frescos.forEach(w => (porMarca[w.marca] ||= []).push(w));
const marcas = Object.keys(porMarca).sort();

const linksRelacionados = atual => `<h2>Veja também</h2><div class="links-rel">${geradas.filter(g => g.url !== atual).map(g => `<a href="${g.url}">${esc(g.curto)}</a>`).join('')}<a href="/artigos/como-escolher-whey-proteina-custo-beneficio">Como escolher whey</a></div>`;

const paginas = [];

// Por marca
for (const m of marcas) {
  const lista = porMarca[m];
  const melhor = lista[0];
  const barato = [...lista].sort((a, b) => a.preco - b.preco)[0];
  const posGeral = frescos.indexOf(melhor) + 1;
  const url = `/whey/${slug(m)}`;
  const faqs = [
    { q: `Qual o whey ${m} com melhor custo-benefício?`, a: `Hoje é o <strong>${esc(nomeProd(melhor))}</strong>: ${brl(melhor.preco)} o pote, o que dá ${brl(melhor.custo)} para cada ${META}g de proteína. Ele está em ${posGeral}º lugar no ranking geral do WheyRank.` },
    { q: `Qual o whey ${m} mais barato?`, a: `O pote mais barato da ${esc(m)} no Mercado Livre é o <strong>${esc(nomeProd(barato))}</strong>, por ${brl(barato.preco)} (${barato.peso_g}g), preço de ${dataBR(barato.preco_atualizado_em)}.` },
    { q: `Quanto de proteína tem o whey ${m}?`, a: lista.map(w => `${esc(nomeProd(w))}: ${w.prot_por_dose}g por dose de ${w.dose_g}g (${w.perc}%)`).join('; ') + '. Dados do rótulo.' },
  ];
  geradas.push({ url, curto: `Whey ${m}`, tipo: 'marca' });
  paginas.push(() => ({
    url,
    html: pagina({
      url, tag: 'Ranking por marca',
      titulo: `Whey ${m}: preço e custo-benefício (${MesAno})`,
      descricao: `Compare os wheys ${m}: preço atualizado no Mercado Livre, % de proteína e custo real por grama. Melhor opção hoje: ${nomeProd(melhor)} a ${brl(melhor.preco)}.`,
      h1: `Whey <em>${esc(m)}</em>: qual vale mais a pena?`,
      corpo: `  <p>Comparamos ${lista.length === 1 ? 'o whey' : `os ${lista.length} wheys`} da <strong>${esc(m)}</strong> pelo que realmente importa: <strong>quanto você paga por grama de proteína</strong>, e não só o preço do pote.</p>
  ${top3Box(lista, `Melhores ${esc(m)} hoje`)}
  <h2>Todos os wheys ${esc(m)} comparados</h2>
  ${tabela(lista)}
  <p>No ranking geral, o melhor ${esc(m)} está em <strong>${posGeral}º lugar</strong> entre ${frescos.length} wheys. ${posGeral > 1 ? `O líder geral hoje é o ${esc(nomeProd(frescos[0]))}, a ${brl(frescos[0].custo)} por ${META}g de proteína.` : 'Ou seja: é o melhor custo-benefício do site hoje.'}</p>
  ${faqHTML(faqs)}
  ${linksRelacionados(url)}`,
      ld: [faqLD(faqs), itemListLD(lista, `Wheys ${m}`)],
    }),
  }));
}

// Faixa de preço
{
  const lista = frescos.filter(w => w.preco <= FAIXA);
  if (lista.length >= 3) {
    const url = `/whey/ate-${FAIXA}-reais`;
    const faqs = [
      { q: `Qual o melhor whey até R$${FAIXA}?`, a: `Pelo custo por grama de proteína, hoje é o <strong>${esc(nomeProd(lista[0]))}</strong>: ${brl(lista[0].preco)}, ou ${brl(lista[0].custo)} para cada ${META}g de proteína.` },
      { q: `Whey barato é ruim?`, a: `Não necessariamente. O que importa é a proteína por dose e os ingredientes. Todos os produtos desta lista são 100% proteína do soro do leite, sem blend com soja, de marcas conhecidas.` },
    ];
    geradas.push({ url, curto: `Whey até R$${FAIXA}`, tipo: 'faixa' });
    paginas.push(() => ({
      url,
      html: pagina({
        url, tag: 'Faixa de preço',
        titulo: `Melhor whey até R$${FAIXA} (${MesAno}): ranking custo-benefício`,
        descricao: `${lista.length} wheys de até R$${FAIXA} ranqueados pelo custo real por grama de proteína. Preços atualizados do Mercado Livre.`,
        h1: `Melhor whey <em>até R$${FAIXA}</em>`,
        corpo: `  <p>Separamos os wheys que custam <strong>até R$${FAIXA}</strong> no Mercado Livre e ordenamos pelo custo real de proteína. Assim dá para gastar pouco sem cair em produto que entrega menos proteína.</p>
  ${top3Box(lista)}
  <h2>Ranking completo até R$${FAIXA}</h2>
  ${tabela(lista)}
  ${faqHTML(faqs)}
  ${linksRelacionados(url)}`,
        ld: [faqLD(faqs), itemListLD(lista, `Melhor whey até R$${FAIXA}`)],
      }),
    }));
  }
}

// Comparativos
for (const [a, b] of COMPARATIVOS) {
  if (!porMarca[a] || !porMarca[b]) continue;
  const A = porMarca[a][0], B = porMarca[b][0];
  const venc = A.custo <= B.custo ? A : B, perd = venc === A ? B : A;
  const dif = Math.round((1 - venc.custo / perd.custo) * 100);
  const url = `/whey/${slug(a)}-vs-${slug(b)}`;
  const lista = [...porMarca[a], ...porMarca[b]].sort((x, y) => x.custo - y.custo);
  const faqs = [
    { q: `${a} ou ${b}: qual whey é melhor?`, a: `No custo por proteína, hoje vence a <strong>${esc(venc.marca)}</strong> com o ${esc(nomeProd(venc))}: ${brl(venc.custo)} por ${META}g de proteína, contra ${brl(perd.custo)} do melhor ${esc(perd.marca)}${dif > 0 ? ` (${dif}% mais barato)` : ''}.` },
    { q: `Qual tem mais proteína por dose, ${a} ou ${b}?`, a: `${esc(nomeProd(A))}: ${A.prot_por_dose}g em ${A.dose_g}g (${A.perc}%). ${esc(nomeProd(B))}: ${B.prot_por_dose}g em ${B.dose_g}g (${B.perc}%).` },
  ];
  geradas.push({ url, curto: `${a} vs ${b}`, tipo: 'vs' });
  paginas.push(() => ({
    url,
    html: pagina({
      url, tag: 'Comparativo',
      titulo: `Whey ${a} ou ${b}: qual compensa mais? (${MesAno})`,
      descricao: `${a} vs ${b}: comparamos preço, % de proteína e custo real por grama com preços atuais do Mercado Livre. Vencedor hoje: ${venc.marca}.`,
      h1: `${esc(a)} <em>vs</em> ${esc(b)}`,
      corpo: `  <p>Duas das marcas mais buscadas, lado a lado. Comparamos o <strong>melhor whey de cada uma</strong> pelo custo real de proteína.</p>
  <div class="example-grid">
    ${[A, B].map(w => `<div class="example-card${w === venc ? ' winner' : ''}">
      <div class="example-card-label">${esc(w.marca)}${w === venc ? ' — melhor custo ✓' : ''}</div>
      <div style="font-size:13px;color:var(--muted);margin-bottom:10px;">${esc(nomeProd(w))} · ${brl(w.preco)} · ${w.perc}% proteína</div>
      <div class="example-card-price">${brl(w.custo)}</div>
      <div class="example-card-detail">por ${META}g de proteína</div>
      <div style="margin-top:10px;">${btnML(w)}</div>
    </div>`).join('\n    ')}
  </div>
  <p><strong>Resultado:</strong> hoje a ${esc(venc.marca)} entrega proteína ${dif > 0 ? `<strong>${dif}% mais barata</strong>` : 'pelo mesmo preço'} que a ${esc(perd.marca)}. Como os preços mudam toda semana, esta página é atualizada automaticamente.</p>
  <h2>Todos os produtos das duas marcas</h2>
  ${tabela(lista)}
  ${faqHTML(faqs)}
  ${linksRelacionados(url)}`,
      ld: [faqLD(faqs), itemListLD(lista, `${a} vs ${b}`)],
    }),
  }));
}

// Escreve páginas (limpa as antigas geradas)
fs.rmSync('whey', { recursive: true, force: true });
fs.mkdirSync('whey');
for (const p of paginas) {
  const { url, html } = p();
  fs.writeFileSync(path.join('whey', url.replace('/whey/', '') + '.html'), html);
}

// ── Home ───────────────────────────────────────────────────
{
  let html = fs.readFileSync('index.html', 'utf8');
  const top = todos.slice(0, 10);
  const cards = top.map((w, i) => {
    const pos = i + 1;
    const clase = pos <= 3 ? `pos-${pos}` : 'pos-other';
    const emoji = ['🥇', '🥈', '🥉'][i] || pos;
    return `<div class="card"><div class="card-pos ${clase}">${emoji}</div>
<div class="card-info"><div class="card-name">${esc(w.nome)} · ${esc(w.marca)}${w.sabor ? ' · ' + esc(w.sabor) : ''}</div>
<div class="card-pills"><span class="pill highlight">${w.perc}% prot</span><span class="pill">${w.prot_por_dose}g / ${w.dose_g}g dose</span><span class="pill">${w.num_doses} doses</span></div></div>
<div class="card-bottom-row"><div class="pote-block"><div class="pote-valor">${brl(w.preco)}</div><div class="pote-sub">pacote · ${w.peso_g}g</div></div>
<div class="meta-block"><div class="meta-label">p/ ${META}g prot</div><div class="meta-custo">${brl(w.custo)}</div></div>
${w.link_ml ? `<a href="${esc(w.link_ml)}" target="_blank" rel="noopener sponsored" class="btn-ml">Mercado Livre →</a>` : ''}</div></div>`;
  }).join('\n');
  html = substituir(html, 'RANKING', `<div class="skeleton-wrap" id="skeleton" style="display:none"></div>
<div id="ranking-list" style="display:flex">
${cards}
</div>`);

  const barato = [...frescos].sort((a, b) => a.preco - b.preco)[0];
  const faqs = [
    { q: 'Qual o whey com melhor custo-benefício hoje?', a: `Pelo custo real de proteína, hoje é o <strong>${esc(nomeProd(frescos[0]))}</strong>: ${brl(frescos[0].preco)} o pote, ${brl(frescos[0].custo)} para cada ${META}g de proteína. Em seguida vêm ${esc(nomeProd(frescos[1]))} e ${esc(nomeProd(frescos[2]))}.` },
    { q: 'Qual o whey protein mais barato?', a: `O pote mais barato do ranking é o <strong>${esc(nomeProd(barato))}</strong>, por ${brl(barato.preco)} (${barato.peso_g}g). Mas pote mais barato nem sempre é proteína mais barata: compare pelo custo por grama.` },
    { q: 'Como o ranking é calculado?', a: `Dividimos o preço do pote pelo número de doses e ajustamos pela proteína de cada dose, chegando no custo para ${META}g de proteína. Os preços vêm do Mercado Livre e são atualizados automaticamente várias vezes por dia.` },
    { q: 'Quais wheys entram no ranking?', a: 'Somente wheys 100% proteína do soro do leite, sem blend com soja, de marcas reconhecidas no mercado brasileiro.' },
  ];
  html = substituir(html, 'FAQ', `<div class="artigos-section faq-home">
  <div class="section-title">PERGUNTAS FREQUENTES</div>
  ${faqs.map(f => `<details class="edu-card" style="margin-bottom:6px;"><summary class="edu-titulo" style="cursor:pointer;">${esc(f.q)}</summary><p class="edu-texto" style="margin-top:8px;">${f.a}</p></details>`).join('\n  ')}
</div>`);

  const info = {
    marca: ['Marca', g => 'Melhor whey ' + g.curto.replace('Whey ', ''), 'Preço e custo real de cada sabor'],
    faixa: ['Faixa de preço', g => g.curto, 'Os melhores para gastar pouco'],
    vs: ['Comparativo', g => g.curto, 'Qual compensa mais hoje'],
  };
  html = substituir(html, 'LINKS', `<div class="artigos-section">
  <div class="section-title">COMPARE POR MARCA, PREÇO E MARCA VS MARCA</div>
  <div class="artigos-grid">
    ${geradas.map(g => `<a href="${g.url}" class="artigo-card"><div class="artigo-tag">${info[g.tipo][0]}</div><div class="artigo-titulo">${esc(info[g.tipo][1](g))}</div><div class="artigo-desc">${info[g.tipo][2]}</div></a>`).join('\n    ')}
  </div>
</div>`);

  html = substituir(html, 'LDJSON', ldScript([
    { '@type': 'WebSite', name: 'WheyRank', url: SITE + '/' },
    itemListLD(frescos, 'Ranking de whey protein por custo-benefício'),
    faqLD(faqs),
  ]));
  fs.writeFileSync('index.html', html);
}

// ── Artigos: Top 3 ─────────────────────────────────────────
const artigos = fs.readdirSync('artigos').filter(f => f.endsWith('.html'));
for (const f of artigos) {
  const p = path.join('artigos', f);
  let html = fs.readFileSync(p, 'utf8');
  if (!html.includes('<!-- GERADO:TOP3 -->')) html = html.replace('<div class="cta-box">', '<!-- GERADO:TOP3 -->\n<!-- /GERADO:TOP3 -->\n\n  <div class="cta-box">');
  html = substituir(html, 'TOP3', top3Box(frescos));
  fs.writeFileSync(p, html);
}

// ── Sitemap ────────────────────────────────────────────────
{
  const urls = [
    { loc: '/', freq: 'daily', pri: '1.0' },
    ...geradas.map(g => ({ loc: g.url, freq: 'daily', pri: '0.8' })),
    ...artigos.map(f => ({ loc: '/artigos/' + f.replace('.html', ''), freq: 'weekly', pri: '0.7' })),
  ];
  fs.writeFileSync('sitemap.xml', `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map(u => `  <url><loc>${SITE}${u.loc}</loc><lastmod>${hojeISO}</lastmod><changefreq>${u.freq}</changefreq><priority>${u.pri}</priority></url>`).join('\n')}
</urlset>
`);
}

console.log(`OK: ${todos.length} produtos (${frescos.length} com preço recente), ${paginas.length} páginas em /whey, ${artigos.length} artigos atualizados.`);
