"use strict";

const $ = (id) => document.getElementById(id);
const caixa = $("mensagens");
const rapidas = $("rapidas");
const texto = $("texto");
const enviar = $("enviar");
const estado = $("estado");
const rotuloRapidas = $("rotulo-rapidas");
const ESPERA_MINIMA_MS = 650;

let GRUPOS = [{ tema: "Problemas comuns", problemas: [
  { texto: "Minha senha expirou e não consigo entrar", destaque: true },
  { texto: "A impressora não imprime", destaque: true },
  { texto: "A VPN não conecta de casa", destaque: true },
] }];
const destaques = () => GRUPOS.flatMap((g) => g.problemas.filter((p) => p.destaque).map((p) => p.texto));
const notas = () => [1, 2, 3, 4, 5].map((n) => t(`chat.nota.${n}`));
const CONSULTAR_TECNICO_MS = 2500;

let sessao = null;
let ocupado = false;
let tecnico = null;
let ultimaMensagem = 0;
const mostradas = new Set();
let bolhaTecnico = null;
let avisoDigitando = 0;


function el(tag, atributos = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(atributos)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) if (f != null && f !== false) e.append(f);
  return e;
}

function escapar(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function formatar(md) {
  return escapar(md).split(/\n{2,}/).map((bloco) => {
    const html = [];
    let lista = null;
    for (const l of bloco.split("\n")) {
      const ul = l.match(/^- (.*)/), ol = l.match(/^\d+\. (.*)/);
      const tipo = ul ? "ul" : ol ? "ol" : null;
      if (tipo !== lista) { if (lista) html.push(`</${lista}>`); if (tipo) html.push(`<${tipo}>`); lista = tipo; }
      html.push(tipo ? `<li>${(ul || ol)[1]}</li>` : `<p>${l}</p>`);
    }
    if (lista) html.push(`</${lista}>`);
    return html.join("");
  }).join("").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function rolar() { caixa.scrollTop = caixa.scrollHeight; }

function definirEstado(chave, rotulo) { estado.dataset.estado = chave; estado.textContent = rotulo; }


function mensagemPessoa(conteudo) {
  caixa.append(el("div", { class: "msg pessoa entrando" }, el("div", { class: "balao" }, conteudo)));
  rolar();
}

function mensagemBot(conteudo, animar = true) {
  const m = el("div", { class: `msg bot${animar ? " entrando" : ""}` },
    el("div", { class: "avatar", "aria-hidden": "true" }, "TI"),
    el("div", { class: "conteudo" }, conteudo));
  caixa.append(m);
  rolar();
  return m;
}

function textoBot(md) {
  const d = el("div", { class: "texto-bot balao-bot" });
  d.innerHTML = formatar(md);
  return d;
}

function situacaoConta(linha) {
  if (/expirou|\bbloqueada\b|desabilitada|não encontrado|falhou/i.test(linha)) return "alerta";
  if (/sucesso|válida|não expira|não está bloqueada|desbloqueada/i.test(linha)) return "ok";
  return "";
}

const avisosPendentes = new Map();
function avisarPassos(titulo, feitos) {
  clearTimeout(avisosPendentes.get(titulo));
  avisosPendentes.set(titulo, setTimeout(() => {
    avisosPendentes.delete(titulo);
    if (!sessao) return;
    fetch("/chat/passos", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessao, titulo, feitos }) }).catch(() => {});
  }, 600));
}

function blocoPassos(passos) {
  const total = passos.itens.length;
  const progresso = el("p", { class: "progresso", "aria-live": "polite" }, t("chat.passos_feitos", { f: 0, t: total }));
  const atualizar = (lista) => {
    const caixas = [...lista.querySelectorAll("input")];
    const feitos = caixas.filter((c) => c.checked).length;
    progresso.textContent = feitos === total ? t("chat.todos_feitos") : t("chat.passos_feitos", { f: feitos, t: total });
    avisarPassos(passos.titulo, caixas.flatMap((c, i) => (c.checked ? [i] : [])));
  };
  const lista = el("ol", { class: "passos" }, passos.itens.map((p) =>
    el("li", {}, el("label", {},
      el("input", { type: "checkbox", onchange: () => atualizar(lista) }),
      el("span", { class: "marcador", "aria-hidden": "true" }),
      el("span", { class: "texto-passo" }, p)))));
  return el("section", { class: "os-secao" }, el("h3", {}, passos.titulo), lista, progresso);
}

function acoesResolveu() {
  const botoes = [
    el("button", { class: "botao-pri", type: "button", onclick: () => mandar("Resolveu", t("chat.resolveu")) }, t("chat.resolveu")),
    el("button", { class: "botao-sec", type: "button", onclick: () => mandar("Não resolveu", t("chat.nao_resolveu")) }, t("chat.nao_resolveu")),
  ];
  return el("footer", { class: "os-acoes" }, el("span", { class: "pergunta" }, t("chat.isso_resolveu")), botoes);
}

function blocoPrevisao(p) {
  if (!p) {
    return el("div", { class: "previsao falhou" },
      el("strong", {}, t("chat.nao_gravou")), t("chat.nao_gravou_2"));
  }
  const icone = el("span", { class: "previsao-icone", "aria-hidden": "true" });
  icone.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  return el("div", { class: "previsao" }, icone,
    el("div", {},
      el("span", { class: "previsao-rotulo" }, t("chat.previsao_rotulo")),
      el("strong", { class: "previsao-tempo" }, t("chat.cerca_de", { t: p.texto })),
      el("span", { class: "previsao-detalhe" },
        t("chat.ate_as", { h: p.ate }) + " · " + (p.na_frente ? t("chat.na_frente", { n: p.na_frente }) : t("chat.proximo_fila"))
        + (p.tecnico ? " · " + t("chat.tecnico_x", { n: p.tecnico }) : ""))));
}

function ordemDeServico(d) {
  const urgClasse = { "Alta": "alta", "Crítica": "critica" }[d.urgencia] || "";
  const partes = [
    el("header", { class: "os-topo" },
      el("div", {},
        el("h2", { class: "os-cat" }, tValor(d.categoria)),
        el("span", { class: `urg ${urgClasse}` }, t("chat.urgencia", { u: String(tValor(d.urgencia)).toLowerCase() }))),
      el("span", { class: "etiqueta", title: t("comum.protocolo") }, d.protocolo)),
  ];
  const correcoes = Object.entries(d.correcoes || {});
  if (correcoes.length) {
    partes.push(el("p", { class: "correcao" },
      t("chat.entendi", { lista: correcoes.map(([de, para]) => t("chat.como", { de, para })).join(", ") })));
  }
  if (d.conta && d.conta.length) {
    partes.push(el("section", { class: "os-secao" }, el("h3", {}, t("chat.verifiquei")),
      el("ul", { class: "conta" }, d.conta.map((l) => el("li", { class: situacaoConta(l) }, l)))));
  }
  if (d.passos) partes.push(blocoPassos(d.passos));
  if (d.outros && d.outros.length) {
    partes.push(el("section", { class: "os-secao" }, el("h3", {}, t("chat.veja_tambem")),
      el("div", { class: "outros" }, d.outros.map((o) =>
        el("button", { type: "button", onclick: () => mandar(String(o.numero)) }, o.titulo)))));
  }
  if (d.encaminhado) {
    partes.push(el("div", { class: "os-encaminhado" },
      el("strong", {}, t("chat.registrado")), t("chat.motivo", { m: d.motivo })));
    if ("previsao" in d) partes.push(blocoPrevisao(d.previsao));
  } else {
    partes.push(acoesResolveu());
  }
  return el("article", { class: "os" }, partes);
}


const ESTRELA = '<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path d="M12 3.2l2.6 5.5 6 .8-4.4 4.1 1.1 5.9L12 16.6l-5.3 2.9 1.1-5.9-4.4-4.1 6-.8z" stroke-linejoin="round"/></svg>';

function estrelas(nota, aoEscolher) {
  const grupo = el("div", { class: "estrelas", role: aoEscolher ? "radiogroup" : "img",
    "aria-label": aoEscolher ? t("chat.nota_1_5") : t("chat.nota_x", { n: nota }) });
  const pintar = (n) => grupo.querySelectorAll(".estrela").forEach((b, i) => b.classList.toggle("acesa", i < n));
  notas().forEach((rotulo, i) => {
    const b = el(aoEscolher ? "button" : "span", { class: "estrela", title: aoEscolher ? `${i + 1} - ${rotulo}` : false });
    b.innerHTML = ESTRELA;
    if (aoEscolher) {
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-label", t("chat.nota_rotulo", { n: i + 1, r: rotulo }));
      b.setAttribute("aria-checked", "false");
      b.addEventListener("click", () => {
        grupo.querySelectorAll(".estrela").forEach((x, j) => x.setAttribute("aria-checked", String(j === i)));
        grupo.dataset.nota = String(i + 1);
        pintar(i + 1);
        aoEscolher(i + 1);
      });
      b.addEventListener("mouseenter", () => pintar(i + 1));
    }
    grupo.append(b);
  });
  if (aoEscolher) grupo.addEventListener("mouseleave", () => pintar(Number(grupo.dataset.nota || 0)));
  pintar(nota || 0);
  return grupo;
}

function cartaoAvaliacao(d) {
  const rotulo = el("span", { class: "nota-rotulo", "aria-live": "polite" }, t("chat.escolha_estrelas"));
  const comentario = el("textarea", { class: "comentario", rows: "2", maxlength: "500", "aria-label": t("chat.comentario"),
    placeholder: t("chat.comentario_ph") });
  const erro = el("p", { class: "erro-avaliacao", hidden: true });
  let nota = 0;
  const enviarNota = el("button", { class: "botao-pri", type: "button", disabled: true }, t("chat.enviar_avaliacao"));
  const pular = el("button", { class: "botao-sec", type: "button" }, t("chat.agora_nao"));
  const grupo = estrelas(0, (n) => { nota = n; rotulo.textContent = notas()[n - 1]; enviarNota.disabled = false; });

  const cartao = el("article", { class: "os avaliacao" },
    el("header", { class: "os-topo" },
      el("div", {}, el("h2", { class: "os-cat" }, t("chat.problema_resolvido")),
        el("span", { class: "urg ok" }, tValor(d.categoria) || t("chat.atendimento_concluido"))),
      d.protocolo ? el("span", { class: "etiqueta", title: t("comum.protocolo") }, d.protocolo) : null),
    el("section", { class: "os-secao" },
      el("h3", {}, t("chat.como_foi")),
      el("div", { class: "linha-estrelas" }, grupo, rotulo),
      comentario, erro),
    el("footer", { class: "os-acoes" }, el("span", { class: "pergunta" }, t("chat.opiniao")),
      pular, enviarNota));

  const concluir = (conteudo) => cartao.querySelectorAll(".os-secao, .os-acoes").forEach((n, i) =>
    i === 0 ? n.replaceWith(conteudo) : n.remove());

  pular.addEventListener("click", () => concluir(el("p", { class: "os-secao nota-final" },
    t("chat.tudo_bem"))));
  cartao.fecharComNota = (n) => concluir(el("section", { class: "os-secao avaliado" },
    el("div", { class: "linha-estrelas" }, estrelas(n), el("span", { class: "nota-rotulo" }, t("chat.avaliacao_registrada")))));

  enviarNota.addEventListener("click", async () => {
    enviarNota.disabled = pular.disabled = true;
    erro.hidden = true;
    try {
      const resp = await fetch("/avaliacao", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessao, protocolo: d.protocolo, nota, comentario: comentario.value }),
      });
      if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || t("comum.erro", { n: resp.status }));
      const r = await resp.json();
      const texto = comentario.value.trim();
      concluir(el("section", { class: "os-secao avaliado" },
        el("div", { class: "linha-estrelas" }, estrelas(nota), el("span", { class: "nota-rotulo" }, notas()[nota - 1])),
        texto ? el("blockquote", { class: "comentario-enviado" }, texto) : null,
        el("p", { class: "nota-final" }, r.texto)));
      rolar();
    } catch (e) {
      erro.textContent = t("chat.nao_registrou", { e: e.message });
      erro.hidden = false;
      enviarNota.disabled = pular.disabled = false;
    }
  });
  return cartao;
}

function desenharResposta(r) {
  const d = r.detalhes || {};
  if (d.tipo === "resolvido") return mensagemBot(cartaoAvaliacao(d));
  if (d.tipo === "avaliado") {
    const abertos = [...caixa.querySelectorAll(".avaliacao")].filter((c) => c.querySelector(".comentario"));
    if (abertos.length) abertos[abertos.length - 1].fecharComNota(d.nota);
    return mensagemBot(el("div", { class: "balao-bot avaliado-texto" },
      el("div", { class: "linha-estrelas" }, estrelas(d.nota), el("span", { class: "nota-rotulo" }, d.rotulo)),
      textoBot(r.texto)));
  }
  if (d.tipo === "atendimento") return mensagemBot(ordemDeServico(d));
  if (d.tipo === "artigo") {
    return mensagemBot(el("article", { class: "os" }, blocoPassos(d.passos), acoesResolveu()));
  }
  if (d.tipo === "encaminhado") {
    return mensagemBot(el("article", { class: "os" },
      el("header", { class: "os-topo" },
        el("div", {}, el("h2", { class: "os-cat" }, t("chat.chamado_registrado")),
          el("span", { class: "urg" }, d.categoria ? t("chat.cat_urgencia", { c: tValor(d.categoria), u: String(tValor(d.urgencia)).toLowerCase() }) : t("chat.equipe_tecnica"))),
        el("span", { class: "etiqueta", title: t("comum.protocolo") }, d.protocolo)),
      el("div", { class: "os-encaminhado" }, t("chat.vai_contato"), el("strong", {}, t("chat.motivo", { m: d.motivo }))),
      blocoPrevisao(d.previsao)));
  }
  return mensagemBot(textoBot(r.texto));
}

function mostrarRapidas(rotulo, opcoes) {
  rotuloRapidas.textContent = rotulo;
  rapidas.parentElement.hidden = opcoes.length === 0;
  rapidas.replaceChildren(...opcoes.map(([valor, dica, rotulo]) =>
    el("button", { type: "button", title: dica || false, onclick: () => mandar(valor, rotulo) },
      rotulo || valor, dica ? el("span", { class: "dica-rapida" }, dica) : null)));
  rapidas.scrollLeft = 0;
  rolar();
}

function problemasComuns(rotulo = t("chat.problemas_comuns"), antes = []) {
  if (tecnico) { mostrarRapidas("", []); return; }
  mostrarRapidas(rotulo, [...antes, ...destaques().map((a) => [a])]);
  rapidas.append(el("button", { class: "mais", type: "button", "aria-expanded": "false", "aria-controls": "todos-problemas",
    onclick: (e) => alternarTodos(e.currentTarget) }, t("chat.mais_problemas", { n: GRUPOS.flatMap((g) => g.problemas).length })));
}

function desenharGrupos() {
  $("grupos").replaceChildren(...GRUPOS.map((g) => el("section", { class: "grupo" },
    el("h3", {}, g.tema),
    g.problemas.map((p) => el("button", { type: "button", onclick: () => { fecharTodos(); mandar(p.texto); } }, p.texto)))));
}

function alternarTodos(botao) {
  const painel = $("todos-problemas");
  painel.hidden = !painel.hidden;
  if (botao) botao.setAttribute("aria-expanded", String(!painel.hidden));
  if (!painel.hidden) painel.querySelector(".grupo button")?.focus();
}
function fecharTodos() {
  $("todos-problemas").hidden = true;
  rapidas.querySelector(".mais")?.setAttribute("aria-expanded", "false");
}
$("fechar-todos").addEventListener("click", () => { fecharTodos(); texto.focus(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("todos-problemas").hidden) { fecharTodos(); texto.focus(); } });

async function carregarProblemas() {
  try {
    const r = await (await fetch("/chat/problemas-comuns")).json();
    if (r.grupos && r.grupos.length) GRUPOS = r.grupos;
  } catch (e) { }
  desenharGrupos();
}

function sugestoes(r) {
  const d = r.detalhes || {};
  if (d.tipo === "pedir_email" || d.tipo === "para_tecnico") mostrarRapidas("", []);
  else if (d.encaminhado || d.tipo === "encaminhado") problemasComuns(t("chat.proximo_passo"), [["Outro problema", null, t("chat.outro_problema")]]);
  else problemasComuns();
}

const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));


async function falar(mensagem) {
  const resp = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessao, mensagem }),
  });
  if (resp.status === 401) { sairDoChat(); Acesso.mostrarLogin(); throw new Error(t("comum.sessao_terminou")); }
  if (!resp.ok) throw new Error(t("chat.servico_respondeu", { n: resp.status }));
  const dados = await resp.json();
  sessao = dados.sessao;
  return dados;
}

function falhaDeConexao() {
  definirEstado("erro", t("comum.sem_conexao"));
  mensagemBot(textoBot(t("chat.falha")));
}

async function mandar(mensagem, exibida = mensagem) {
  mensagem = mensagem.trim();
  if (!mensagem || ocupado) return;
  ocupado = true;
  enviar.disabled = true;
  caixa.querySelectorAll(".os:not(.avaliacao) .os-acoes button, .outros button").forEach((b) => { b.disabled = true; });
  rapidas.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  mensagemPessoa(exibida || mensagem);
  texto.value = "";
  ajustarAltura();
  fecharTodos();
  const aguarde = tecnico ? null : mensagemBot(el("div", { class: "balao-bot digitando", role: "status", "aria-label": t("comum.digitando_curto") },
    el("span"), el("span"), el("span")));
  try {
    const [r] = await Promise.all([falar(mensagem), esperar(tecnico ? 0 : ESPERA_MINIMA_MS)]);
    aguarde?.remove();
    definirEstado("pronto", t("comum.pronto"));
    if (r.detalhes?.tipo === "para_tecnico") mostradas.add(r.detalhes.mensagem.id);
    else desenharResposta(r);
    sugestoes(r);
    if (bolhaTecnico) caixa.append(bolhaTecnico);
  } catch (e) {
    aguarde?.remove();
    falhaDeConexao();
    problemasComuns();
  } finally {
    ocupado = false;
    enviar.disabled = false;
    texto.focus();
  }
}


const placeholderPadrao = () => (window.matchMedia("(max-width: 480px)").matches
  ? t("chat.placeholder_curto") : t("chat.placeholder"));
const iniciais = (nome) => String(nome || "?").split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
const hora = (data) => (String(data).split(" ")[1] || "");

function mensagemDoTecnico(m) {
  if (m.autor === "sistema") {
    caixa.append(el("div", { class: "msg-sistema entrando" }, m.texto));
  } else if (m.autor === "usuario") {
    mensagemPessoa(m.texto);
  } else {
    caixa.append(el("div", { class: "msg bot entrando" },
      el("div", { class: "avatar humano", "aria-hidden": "true" }, iniciais(m.nome)),
      el("div", { class: "conteudo" },
        el("span", { class: "autor" }, t("chat.tecnico_autor", { nome: m.nome }), el("span", { class: "hora" }, hora(m.data))),
        el("div", { class: "balao-bot" }, m.texto))));
  }
  rolar();
}

function bolhaDigitando(mostrar, nome) {
  if (!mostrar) { bolhaTecnico?.remove(); bolhaTecnico = null; return; }
  if (!bolhaTecnico) {
    bolhaTecnico = el("div", { class: "msg bot entrando" },
      el("div", { class: "avatar humano", "aria-hidden": "true" }, iniciais(nome)),
      el("div", { class: "conteudo" },
        el("span", { class: "autor" }, t("comum.digitando", { nome })),
        el("div", { class: "balao-bot digitando", role: "status", "aria-label": t("comum.digitando", { nome }) },
          el("span"), el("span"), el("span"))));
  }
  if (caixa.lastElementChild !== bolhaTecnico) { caixa.append(bolhaTecnico); rolar(); }
}

function atualizarConversa(c) {
  const antes = tecnico;
  tecnico = c;
  $("faixa-tecnico").hidden = !c;
  if (c) {
    $("texto-tecnico").textContent = t("chat.tecnico_conversando", { nome: c.tecnico });
    $("avatar-tecnico").textContent = iniciais(c.tecnico);
    texto.placeholder = t("chat.escreva_para", { nome: c.tecnico });
    if (!antes) { fecharTodos(); mostrarRapidas("", []); }
  } else if (antes) {
    texto.placeholder = placeholderPadrao();
    bolhaDigitando(false);
    problemasComuns();
  }
}

async function consultarTecnico() {
  if (!sessao) return;
  try {
    const r = await (await fetch(`/chat/mensagens?sessao=${encodeURIComponent(sessao)}&desde=${ultimaMensagem}`)).json();
    for (const m of r.mensagens) {
      ultimaMensagem = Math.max(ultimaMensagem, m.id);
      if (mostradas.has(m.id)) continue;
      mostradas.add(m.id);
      bolhaDigitando(false);
      mensagemDoTecnico(m);
    }
    atualizarConversa(r.conversa);
    bolhaDigitando(Boolean(r.conversa && r.tecnico_digitando), r.conversa?.tecnico);
  } catch (e) { }
}

texto.addEventListener("input", () => {
  if (!tecnico || !sessao || Date.now() - avisoDigitando < 2000) return;
  avisoDigitando = Date.now();
  fetch("/chat/digitando", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessao }) }).catch(() => {});
});

async function iniciar() {
  sessao = null;
  caixa.replaceChildren();
  atualizarConversa(null);
  tecnico = null;
  ultimaMensagem = 0;
  mostradas.clear();
  problemasComuns();
  try {
    const r = await falar("");
    definirEstado("pronto", t("comum.pronto"));
    mensagemBot(textoBot(r.texto), false);
  } catch (e) {
    falhaDeConexao();
  }
}



const trilho = $("trilho");
const movimentoReduzido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function atualizarSetas() {
  const resto = rapidas.scrollWidth - rapidas.clientWidth - rapidas.scrollLeft;
  const esquerda = rapidas.scrollLeft > 4, direita = resto > 4;
  $("seta-esquerda").hidden = !esquerda;
  $("seta-direita").hidden = !direita;
  trilho.classList.toggle("tem-esquerda", esquerda);
  trilho.classList.toggle("tem-direita", direita);
}

function deslizar(direcao) {
  rapidas.scrollBy({ left: direcao * rapidas.clientWidth * 0.7, behavior: movimentoReduzido() ? "auto" : "smooth" });
}
$("seta-esquerda").addEventListener("click", () => deslizar(-1));
$("seta-direita").addEventListener("click", () => deslizar(1));

rapidas.addEventListener("wheel", (e) => {
  if (rapidas.scrollWidth <= rapidas.clientWidth) return;
  const passo = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
  if (!passo) return;
  e.preventDefault();
  rapidas.scrollLeft += passo * (e.deltaMode === 1 ? 40 : 1);
}, { passive: false });

let arraste = null;
rapidas.addEventListener("pointerdown", (e) => {
  if (e.pointerType !== "mouse" || e.button !== 0) return;
  arraste = { x: e.clientX, inicio: rapidas.scrollLeft, movendo: false, id: e.pointerId };
});
rapidas.addEventListener("pointermove", (e) => {
  if (!arraste || e.pointerId !== arraste.id) return;
  const dx = e.clientX - arraste.x;
  if (!arraste.movendo && Math.abs(dx) > 6) {
    arraste.movendo = true;
    rapidas.classList.add("arrastando");
    rapidas.setPointerCapture(e.pointerId);
  }
  if (arraste.movendo) rapidas.scrollLeft = arraste.inicio - dx;
});
function soltar(e) {
  if (!arraste || (e && e.pointerId !== arraste.id)) return;
  const arrastou = arraste.movendo;
  arraste = null;
  rapidas.classList.remove("arrastando");
  if (arrastou) {
    const bloquear = (c) => { c.stopPropagation(); c.preventDefault(); };
    rapidas.addEventListener("click", bloquear, { capture: true, once: true });
    setTimeout(() => rapidas.removeEventListener("click", bloquear, { capture: true }), 80);
  }
}
rapidas.addEventListener("pointerup", soltar);
rapidas.addEventListener("pointercancel", soltar);

rapidas.addEventListener("scroll", atualizarSetas, { passive: true });
window.addEventListener("resize", atualizarSetas);
new MutationObserver(() => requestAnimationFrame(atualizarSetas)).observe(rapidas, { childList: true });

function ajustarAltura() {
  texto.style.height = "auto";
  texto.style.height = Math.min(texto.scrollHeight, 160) + "px";
}

$("form").addEventListener("submit", (e) => { e.preventDefault(); mandar(texto.value); });
texto.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("form").requestSubmit(); }
});
texto.addEventListener("input", ajustarAltura);
$("nova").addEventListener("click", iniciar);


const STATUS_CLASSE = { "Aberto": "aberto", "Em atendimento": "andamento", "Concluído": "concluido" };

function cartaoMeuChamado(c) {
  const dado = (rotulo, valor) => el("div", {}, el("dt", {}, rotulo), el("dd", {}, valor || "-"));
  const mensagens = c.mensagens.length
    ? el("div", { class: "mensagens-meus" }, c.mensagens.map((m) => (m.autor === "sistema"
      ? el("div", { class: "msg-sistema" }, m.texto)
      : m.autor === "usuario"
        ? el("div", { class: "msg pessoa" }, el("div", { class: "conteudo" },
          el("span", { class: "autor" }, t("meus.voce"), el("span", { class: "hora" }, hora(m.data))),
          el("div", { class: "balao" }, m.texto)))
        : el("div", { class: "msg bot" },
          el("div", { class: "avatar humano", "aria-hidden": "true" }, iniciais(m.nome)),
          el("div", { class: "conteudo" },
            el("span", { class: "autor" }, t("chat.tecnico_autor", { nome: m.nome }), el("span", { class: "hora" }, hora(m.data))),
            el("div", { class: "balao-bot" }, m.texto))))))
    : el("p", { class: "sem-mensagens" }, t("meus.sem_mensagens"));
  return el("article", { class: `meu-chamado st-${STATUS_CLASSE[c.status] || "aberto"}` },
    el("header", { class: "meu-topo" },
      el("span", { class: "etiqueta" }, c.protocolo),
      el("span", { class: `pilula status ${STATUS_CLASSE[c.status] || "aberto"}` }, tValor(c.status)),
      el("span", { class: "categoria-meu" }, tValor(c.categoria))),
    el("p", { class: "descricao-meu" }, c.descricao),
    el("dl", { class: "dados-meu" },
      dado(t("meus.aberto_em"), c.data),
      dado(t("meus.responsavel"), c.tecnico || t("meus.ninguem")),
      c.status !== "Concluído" ? dado(t("meus.previsao"), c.previsao) : null,
      dado(t("meus.atualizado"), c.atualizado_em)),
    c.motivo ? el("p", { class: "motivo-meu" }, el("strong", {}, `${t("meus.motivo")}: `), c.motivo) : null,
    el("details", { class: "conversa-meu", open: c.conversa_ativa || false },
      el("summary", {}, `${t("meus.mensagens")} (${c.mensagens.filter((m) => m.autor !== "sistema").length})`),
      mensagens,
      c.conversa_ativa ? el("p", { class: "nota-meu" }, t("meus.conversa_ativa")) : null));
}

async function carregarMeus(desenharLista = true) {
  try {
    const resp = await fetch("/chat/meus-chamados", { headers: { "X-Consulta-Automatica": desenharLista ? "0" : "1" } });
    if (resp.status === 401) return;
    const { chamados } = await resp.json();
    const abertos = chamados.filter((c) => c.status !== "Concluído").length;
    $("contador-meus").textContent = String(abertos);
    $("contador-meus").hidden = !abertos;
    $("contador-meus").title = t("meus.abertos", { n: abertos });
    if (!desenharLista) return;
    $("lista-meus").replaceChildren(...(chamados.length ? chamados.map(cartaoMeuChamado)
      : [el("p", { class: "vazio-meus" }, t("meus.vazio"))]));
  } catch (e) {
    if (desenharLista) $("lista-meus").replaceChildren(el("p", { class: "vazio-meus" }, t("meus.erro", { e: e.message })));
  }
}

function abrirMeus() {
  $("painel-meus").hidden = $("veu-meus").hidden = false;
  $("lista-meus").replaceChildren(el("p", { class: "vazio-meus" }, t("comum.carregando")));
  carregarMeus();
  $("fechar-meus").focus();
}
function fecharMeus() {
  $("painel-meus").hidden = $("veu-meus").hidden = true;
  $("meus-chamados").focus();
}
$("meus-chamados").addEventListener("click", abrirMeus);
$("fechar-meus").addEventListener("click", fecharMeus);
$("veu-meus").addEventListener("click", fecharMeus);
$("atualizar-meus").addEventListener("click", () => carregarMeus());
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("painel-meus").hidden) fecharMeus(); });


let relogioTecnico = null, relogioMeus = null;

function entrarNoChat(perfil) {
  $("nome-usuario").textContent = perfil.nome.split(/\s+/)[0];
  $("avatar").textContent = iniciais(perfil.nome);
  for (const id of ["conversa", "usuario", "meus-chamados", "nova", "estado"]) $(id).hidden = false;
  $("config-anonimo").hidden = true;
  texto.placeholder = placeholderPadrao();
  carregarProblemas().then(() => { if (!tecnico) problemasComuns(); });
  iniciar();
  carregarMeus(false);
  relogioTecnico = relogioTecnico || setInterval(consultarTecnico, CONSULTAR_TECNICO_MS);
  relogioMeus = relogioMeus || setInterval(() => carregarMeus(!$("painel-meus").hidden), 30000);
  texto.focus();
}

function sairDoChat() {
  clearInterval(relogioTecnico); clearInterval(relogioMeus);
  relogioTecnico = relogioMeus = null;
  sessao = null;
  for (const id of ["conversa", "usuario", "meus-chamados", "nova", "estado"]) $(id).hidden = true;
  $("painel-meus").hidden = $("veu-meus").hidden = true;
  $("config-anonimo").hidden = false;
}

$("usuario").addEventListener("click", () => Conta.abrir("conta"));
$("config-anonimo").addEventListener("click", () => Conta.abrir("config"));

window.addEventListener("idioma-mudou", () => {
  texto.placeholder = tecnico ? t("chat.escreva_para", { nome: tecnico.tecnico }) : placeholderPadrao();
  if (tecnico) $("texto-tecnico").textContent = t("chat.tecnico_conversando", { nome: tecnico.tecnico });
  else if (!$("conversa").hidden) problemasComuns();
  desenharGrupos();
  if (estado.dataset.estado === "pronto") definirEstado("pronto", t("comum.pronto"));
  if (!$("painel-meus").hidden) carregarMeus();
});

traduzirPagina();
Conta.iniciar({ area: "/chat", aoSair: sairDoChat });
Acesso.iniciar({
  area: "/chat", titulo: t("acesso.entrar_chat"), explica: t("acesso.explica_chat"),
  aoEntrar: entrarNoChat, aoMostrarAcesso: sairDoChat,
});
