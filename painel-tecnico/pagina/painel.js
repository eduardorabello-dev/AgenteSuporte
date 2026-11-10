"use strict";

const $ = (id) => document.getElementById(id);
const lista = $("lista");
const aviso = $("aviso");
const estado = $("estado");
const ATUALIZAR_A_CADA_MS = 20000;
const ORDEM_URGENCIA = { "Crítica": 0, "Alta": 1, "Média": 2, "Baixa": 3 };
const ORDEM_STATUS = { "Em atendimento": 0, "Aberto": 1, "Concluído": 2 };
const SEGMENTOS = [["ativos", "painel.em_aberto"], ["Concluído", "painel.concluidos"], ["todos", "painel.todos"]];
const SEM_RESPONSAVEL = "__sem__";
const TODOS = "__todos__";

let eu = null;
let equipe = [];
let chamados = [];
let visao = null;
let segmento = "ativos";
let relogio = null;
const editando = new Set();


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

function data(texto) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2})/.exec(texto || "");
  return m ? new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]) : null;
}

function duracao(min) {
  min = Math.round(Math.abs(min));
  const h = Math.floor(min / 60), m = min % 60;
  if (h >= 24) return `${Math.floor(h / 24)} d ${h % 24} h`;
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
}

function prazo(c) {
  const limite = data(c.previsao);
  if (!limite || c.status === "Concluído") return null;
  const faltam = (limite - Date.now()) / 60000;
  return { atrasado: faltam < 0, texto: t(faltam < 0 ? "painel.atrasado" : "painel.faltam", { t: duracao(faltam) }) };
}

const nomeDe = (email) => (equipe.find((x) => x.email === email) || {}).nome || email;
const iniciais = (nome) => nome.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();

function definirEstado(chave, rotulo) { estado.dataset.estado = chave; estado.textContent = rotulo; }
function mostrarAviso(texto) { aviso.textContent = texto; aviso.hidden = !texto; }

async function api(metodo, caminho, corpo, automatica = false) {
  const cabecalhos = corpo ? { "Content-Type": "application/json" } : {};
  if (automatica) cabecalhos["X-Consulta-Automatica"] = "1";
  const resp = await fetch(caminho, {
    method: metodo, credentials: "same-origin",
    headers: cabecalhos,
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  const dados = await resp.json().catch(() => ({}));
  if (resp.status === 401) {
    sairDoPainel();
    Acesso.mostrarLogin();
    throw new Error(t("comum.sessao_terminou"));
  }
  if (!resp.ok) {
    const detalhe = Array.isArray(dados.detail) ? t("comum.dados_invalidos") : dados.detail;
    throw new Error(detalhe || t("comum.erro", { n: resp.status }));
  }
  return dados;
}


function entrarComo(perfil) {
  eu = perfil;
  equipe = perfil.equipe;
  $("nome-usuario").textContent = perfil.nome;
  $("papel-usuario").textContent = tValor(perfil.papel || "tecnico");
  $("avatar").textContent = iniciais(perfil.nome);
  $("usuario").hidden = false;
  $("config-anonimo").hidden = true;
  estado.hidden = false;
  if (!visao) visao = perfil.email;
  $("tela-painel").hidden = false;
  Admin.iniciar(perfil);
  carregar(true);
  if (!relogio) relogio = setInterval(() => carregar(), ATUALIZAR_A_CADA_MS);
}

function sairDoPainel() {
  if (relogio) { clearInterval(relogio); relogio = null; }
  fecharConversa();
  eu = null;
  visao = null;
  chamados = [];
  $("tela-painel").hidden = true;
  Admin.sair();
  $("usuario").hidden = true;
  $("config-anonimo").hidden = false;
  estado.hidden = true;
}

$("usuario").addEventListener("click", () => Conta.abrir("conta"));
$("config-anonimo").addEventListener("click", () => Conta.abrir("config"));

async function carregar(forcar = false) {
  if (!forcar && editando.size) return;
  try {
    const corpo = await api("GET", "/tecnico/chamados", undefined, !forcar);
    chamados = corpo.chamados;
    equipe = corpo.equipe;
    mostrarAviso("");
    definirEstado("pronto", t("painel.atualizado_as", { h: new Date().toLocaleTimeString(localeAtual(), { hour: "2-digit", minute: "2-digit" }) }));
    desenhar();
  } catch (e) {
    if (!$("tela-painel").hidden) {
      definirEstado("erro", t("comum.sem_conexao"));
      mostrarAviso(t("painel.nao_carregou", { e: e.message }));
    }
  }
}

async function atualizar(protocolo, mudancas, botao) {
  if (botao) botao.disabled = true;
  try {
    const corpo = await api("PATCH", `/tecnico/chamados/${encodeURIComponent(protocolo)}`, mudancas);
    editando.delete(protocolo);
    chamados = chamados.map((c) => (c.protocolo === protocolo ? corpo : c));
    mostrarAviso("");
    desenhar();
  } catch (e) {
    mostrarAviso(t("painel.nao_salvou", { p: protocolo, e: e.message }));
    if (botao) botao.disabled = false;
  }
}

async function distribuir(botao) {
  botao.disabled = true;
  try {
    const r = await api("POST", "/tecnico/distribuir");
    mostrarAviso("");
    await carregar(true);
    definirEstado("pronto", t("painel.distribuidos", { n: r.distribuidos }));
  } catch (e) {
    mostrarAviso(t("painel.nao_distribuiu", { e: e.message }));
    botao.disabled = false;
  }
}


const ativo = (c) => c.status !== "Concluído";
const doTime = (email) => equipe.some((x) => x.email === email);
const daVisao = (c, v) => v === TODOS || (v === SEM_RESPONSAVEL ? !doTime(c.tecnico) : c.tecnico === v);

function contar(v) {
  const meus = chamados.filter((c) => daVisao(c, v));
  return {
    fila: meus.filter((c) => c.status === "Aberto").length,
    andamento: meus.filter((c) => c.status === "Em atendimento").length,
    atrasados: meus.filter((c) => prazo(c)?.atrasado).length,
    concluidos: meus.filter((c) => c.status === "Concluído").length,
  };
}

function cartaoTecnico(v, nome, subtitulo, extra = null, sigla = "") {
  const n = contar(v);
  const selecionado = visao === v;
  const escolher = () => { visao = v; desenhar(); };
  return el("div", { class: `cartao-tecnico${selecionado ? " selecionado" : ""}${n.atrasados ? " com-atraso" : ""}`,
    role: "tab", tabindex: "0", "aria-selected": String(selecionado), onclick: escolher,
    onkeydown: (e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); escolher(); } } },
    el("span", { class: "linha-tecnico" },
      el("span", { class: `avatar-usuario${v === SEM_RESPONSAVEL ? " sem-dono" : v === TODOS ? " todos" : ""}`, "aria-hidden": "true" },
        v === SEM_RESPONSAVEL ? "?" : v === TODOS ? "∑" : sigla),
      el("span", { class: "nome-tecnico" }, el("strong", {}, nome), el("small", {}, subtitulo))),
    el("span", { class: "numeros" },
      el("span", {}, el("b", {}, String(n.fila)), t("painel.na_fila")),
      el("span", {}, el("b", {}, String(n.andamento)), t("painel.atendendo")),
      el("span", { class: n.atrasados ? "atraso" : "" }, el("b", {}, String(n.atrasados)), t("painel.atrasados"))),
    extra);
}

function desenharEquipe() {
  const ordem = [...equipe].sort((a, b) => (a.email === eu.email ? -1 : b.email === eu.email ? 1 : a.nome.localeCompare(b.nome)));
  const semDono = chamados.filter((c) => !doTime(c.tecnico) && ativo(c)).length;
  const cartoes = ordem.map((x) => cartaoTecnico(x.email, x.nome + (x.email === eu.email ? t("painel.voce_sufixo") : ""),
    tValor(x.papel === "admin" ? "admin" : "tecnico"), null, iniciais(x.nome)));
  const botaoDistribuir = semDono
    ? el("button", { class: "distribuir", type: "button",
      onclick: (e) => { e.stopPropagation(); distribuir(e.currentTarget); } }, t("painel.distribuir"))
    : null;
  cartoes.push(cartaoTecnico(SEM_RESPONSAVEL, t("painel.sem_responsavel"), semDono ? t("painel.esperando", { n: semDono }) : t("painel.nenhum_esperando"),
    botaoDistribuir));
  cartoes.push(cartaoTecnico(TODOS, t("painel.toda_equipe"), t("painel.total", { n: chamados.length })));
  $("equipe").replaceChildren(...cartoes);
}

function desenharSegmentos() {
  $("segmentos").replaceChildren(...SEGMENTOS.map(([chave, rotulo]) =>
    el("button", { type: "button", role: "radio", "aria-checked": String(chave === segmento),
      onclick: () => { segmento = chave; desenhar(); } }, t(rotulo))));
}

function filtrados() {
  const termo = $("busca").value.trim().toLowerCase();
  const urg = $("urgencia").value;
  return chamados
    .filter((c) => daVisao(c, visao))
    .filter((c) => segmento === "todos" || (segmento === "ativos" ? ativo(c) : c.status === "Concluído"))
    .filter((c) => !urg || c.urgencia === urg)
    .filter((c) => !termo || [c.protocolo, c.email, c.descricao, c.categoria, nomeDe(c.tecnico)]
      .some((v) => (v || "").toLowerCase().includes(termo)))
    .sort((a, b) => (ORDEM_STATUS[a.status] ?? 9) - (ORDEM_STATUS[b.status] ?? 9)
      || (ORDEM_URGENCIA[a.urgencia] ?? 9) - (ORDEM_URGENCIA[b.urgencia] ?? 9)
      || (data(a.data) - data(b.data)));
}

function seletorResponsavel(c) {
  const sel = el("select", { class: "responsavel", "aria-label": t("painel.responsavel_por", { p: c.protocolo }) },
    el("option", { value: "" }, t("painel.sem_responsavel")),
    equipe.map((x) => el("option", { value: x.email }, x.nome + (x.email === eu.email ? t("painel.voce_sufixo") : ""))),
    c.tecnico && !doTime(c.tecnico) ? el("option", { value: c.tecnico, disabled: true }, t("painel.fora_equipe", { n: c.tecnico })) : null);
  sel.value = c.tecnico || "";
  sel.addEventListener("change", () => atualizar(c.protocolo, { tecnico: sel.value }, sel));
  return sel;
}

function ficha(c) {
  const p = prazo(c);
  const meu = c.tecnico === eu.email;
  const urg = { "Crítica": "critica", "Alta": "alta", "Média": "media", "Baixa": "baixa" }[c.urgencia] || "media";
  const st = { "Aberto": "aberto", "Em atendimento": "andamento", "Concluído": "concluido" }[c.status] || "aberto";

  const observacao = el("textarea", { class: "observacao", rows: "2", maxlength: "1000", "aria-label": t("painel.observacao"),
    placeholder: t("painel.observacao_ph") });
  observacao.value = c.observacao || "";
  const salvarObs = el("button", { class: "botao-sec", type: "button", hidden: true }, t("painel.salvar_obs"));
  observacao.addEventListener("input", () => {
    const mudou = observacao.value !== (c.observacao || "");
    salvarObs.hidden = !mudou;
    if (mudou) editando.add(c.protocolo); else editando.delete(c.protocolo);
  });
  salvarObs.addEventListener("click", () => atualizar(c.protocolo, { observacao: observacao.value }, salvarObs));

  const botao = (rotulo, classe, mudancas) => el("button", { class: classe, type: "button",
    onclick: (e) => atualizar(c.protocolo, { ...mudancas, observacao: observacao.value }, e.currentTarget) }, rotulo);
  const acoes = [];
  if (c.status === "Aberto") {
    acoes.push(meu ? botao(t("painel.iniciar_atendimento"), "botao-pri", { status: "Em atendimento" })
      : botao(t("painel.assumir"), "botao-pri", { status: "Em atendimento", tecnico: eu.email }));
  } else if (c.status === "Em atendimento") {
    acoes.push(meu ? botao(t("painel.concluir"), "botao-pri", { status: "Concluído" })
      : botao(t("painel.assumir"), "botao-pri", { tecnico: eu.email }));
  } else {
    acoes.push(botao(t("painel.reabrir"), "botao-sec", { status: "Em atendimento", tecnico: c.tecnico || eu.email }));
  }

  const chat = c.chat || {};
  const naoLidas = chat.ultima_do_usuario > lidas(c.protocolo);
  const podeConversar = (c.status !== "Concluído" && chat.disponivel) || chat.total > 0;
  const botaoConversa = podeConversar
    ? el("button", { class: `botao-conversa${naoLidas ? " nova" : ""}`, type: "button",
      title: t(chat.online ? "painel.online" : "painel.offline"),
      onclick: () => abrirConversa(c) },
      el("span", { class: `ponto${chat.online ? " online" : ""}`, "aria-hidden": "true" }),
      t(chat.ativa ? "painel.abrir_conversa" : "painel.conversar"),
      naoLidas ? el("span", { class: "novas" }, t("painel.nova_msg")) : null)
    : null;

  const acoesExecutadas = (c.acoes_executadas || "").split(" | ").filter(Boolean);
  return el("article", { class: `ficha urg-${urg} st-${st}${meu ? " minha" : ""}` },
    el("header", { class: "ficha-topo" },
      el("span", { class: "etiqueta" }, c.protocolo),
      el("span", { class: `pilula urg ${urg}` }, tValor(c.urgencia) || t("painel.sem_urgencia")),
      el("span", { class: `pilula status ${st}` }, tValor(c.status)),
      el("span", { class: "categoria" }, tValor(c.categoria) || t("painel.sem_categoria")),
      p ? el("span", { class: `prazo${p.atrasado ? " atrasado" : ""}`, title: t("painel.previsao_de", { p: c.previsao }) }, p.texto) : null),
    el("p", { class: "descricao" }, c.descricao || t("painel.sem_descricao")),
    el("dl", { class: "dados" },
      el("div", {}, el("dt", {}, t("painel.solicitante")), el("dd", {}, c.email
        ? el("a", { href: `mailto:${c.email}?subject=${encodeURIComponent(t("painel.chamado_assunto", { p: c.protocolo }))}` }, c.email) : t("painel.nao_informado"))),
      el("div", {}, el("dt", {}, t("painel.aberto_em")), el("dd", {}, c.data || "-")),
      el("div", {}, el("dt", {}, t("painel.previsao")), el("dd", {}, c.previsao || "-")),
      el("div", {}, el("dt", {}, t("painel.responsavel")), el("dd", {}, c.status === "Concluído"
        ? (c.tecnico ? nomeDe(c.tecnico) : t("painel.ninguem")) : seletorResponsavel(c)))),
    el("p", { class: "motivo" }, el("strong", {}, t("painel.por_que")), c.motivo || "-"),
    secaoHistorico(c, acoesExecutadas),
    observacao,
    el("footer", { class: "ficha-acoes" }, botaoConversa, salvarObs, el("span", { class: "espaco" }),
      c.atualizado_em ? el("span", { class: "atualizado" },
        t("painel.atualizado_em", { d: c.atualizado_em }) + (c.atualizado_por && c.atualizado_por !== "chat" ? t("painel.por", { n: nomeDe(c.atualizado_por) }) : "")) : null,
      acoes));
}

const historicosAbertos = new Set();

function secaoHistorico(c, acoes) {
  const eventos = c.historico || [];
  const mensagens = eventos.filter((e) => e.tipo === "mensagem");
  const solucoes = eventos.filter((e) => e.tipo === "solucao");
  if (!acoes.length && !eventos.length) return null;

  const feitosTotal = solucoes.reduce((n, s) => n + (s.feitos || []).length, 0);
  const passosTotal = solucoes.reduce((n, s) => n + (s.passos || []).length, 0);
  const resumo = [
    acoes.length ? t("painel.hist_verif", { n: acoes.length }) : null,
    mensagens.length ? t("painel.hist_msgs", { n: mensagens.length }) : null,
    solucoes.length ? t("painel.hist_sol", { n: solucoes.length, f: feitosTotal, t: passosTotal }) : null,
  ].filter(Boolean).join(" · ");

  const linhaDoTempo = eventos.map((e) => {
    if (e.tipo === "mensagem") {
      return el("li", { class: "evento mensagem" },
        el("span", { class: "quando" }, e.hora || ""),
        el("div", {}, el("span", { class: "quem" }, t("painel.hist_escreveu")), el("q", {}, e.texto)));
    }
    const feitos = new Set(e.feitos || []);
    const total = (e.passos || []).length;
    return el("li", { class: "evento solucao" },
      el("span", { class: "quando" }, e.hora || ""),
      el("div", {},
        el("span", { class: "quem" }, t("painel.hist_sugeriu"), el("strong", {}, e.titulo),
          el("span", { class: `contagem-passos${feitos.size === total && total ? " completo" : feitos.size ? "" : " nenhum"}` },
            t("painel.hist_feitos", { f: feitos.size, t: total }))),
        el("ol", { class: "passos-feitos" }, (e.passos || []).map((p, i) => el("li", {
          class: feitos.has(i) ? "feito" : "", title: t(feitos.has(i) ? "painel.hist_marcou" : "painel.hist_nao_marcado"),
        }, el("span", { class: "marca-passo", "aria-label": t(feitos.has(i) ? "painel.hist_feito" : "painel.hist_nao_feito") }, feitos.has(i) ? "✓" : ""),
        p)))));
  });

  const detalhes = el("details", { class: "historico", open: historicosAbertos.has(c.protocolo) },
    el("summary", {}, el("strong", {}, t("painel.hist_titulo")),
      el("span", { class: "resumo-historico" }, resumo)),
    acoes.length ? el("div", { class: "bloco-historico" }, el("h4", {}, t("painel.hist_conta")),
      el("ul", { class: "verificacoes-conta" }, acoes.map((a) => el("li", {}, a)))) : null,
    eventos.length ? el("div", { class: "bloco-historico" }, el("h4", {}, t("painel.hist_ordem")),
      el("ol", { class: "linha-do-tempo" }, linhaDoTempo))
      : el("p", { class: "sem-historico" }, t("painel.hist_antigo")));
  detalhes.addEventListener("toggle", () => {
    if (detalhes.open) historicosAbertos.add(c.protocolo); else historicosAbertos.delete(c.protocolo);
  });
  return detalhes;
}

function tituloDaLista(qtd) {
  const quem = visao === TODOS ? t("painel.toda_equipe") : visao === SEM_RESPONSAVEL ? t("painel.sem_responsavel")
    : visao === eu.email ? t("painel.lista_meus") : t("painel.lista_de", { n: nomeDe(visao) });
  const situacao = { ativos: t("painel.lista_em_aberto"), "Concluído": t("painel.lista_concluidos"), todos: "" }[segmento];
  return `${quem}${situacao ? ` · ${situacao}` : ""} (${qtd})`;
}

function desenhar() {
  if (!eu) return;
  if (visao !== TODOS && visao !== SEM_RESPONSAVEL && !equipe.some((x) => x.email === visao)) visao = eu.email;
  desenharEquipe();
  desenharSegmentos();
  const itens = filtrados();
  $("titulo-lista").textContent = tituloDaLista(itens.length);
  if (!itens.length) {
    const vazio = chamados.length === 0 ? t("painel.vazio_total")
      : visao === eu.email && segmento === "ativos" ? t("painel.vazio_meus")
        : t("painel.vazio");
    lista.replaceChildren(el("div", { class: "vazio" }, vazio));
    return;
  }
  lista.replaceChildren(...itens.map(ficha));
}

$("busca").addEventListener("input", desenhar);
$("urgencia").addEventListener("change", desenhar);


const CONSULTAR_CONVERSA_MS = 2000;
let gaveta = null;
let avisoDigitando = 0;

function lidas(protocolo) {
  try { return Number(localStorage.getItem(`lidas-${protocolo}`) || 0); } catch (e) { return 0; }
}
function marcarLidas(protocolo, id) {
  try { if (id > lidas(protocolo)) localStorage.setItem(`lidas-${protocolo}`, String(id)); } catch (e) { }
}

const horaDe = (data) => (String(data).split(" ")[1] || "");
const rolarGaveta = () => { const m = $("gaveta-mensagens"); m.scrollTop = m.scrollHeight; };

function bolhaDaConversa(m) {
  if (m.autor === "sistema") return el("div", { class: "msg-sistema entrando" }, m.texto);
  if (m.autor === "tecnico") {
    return el("div", { class: "msg pessoa entrando" }, el("div", { class: "conteudo" },
      el("span", { class: "autor" }, m.nome, el("span", { class: "hora" }, horaDe(m.data))),
      el("div", { class: "balao" }, m.texto)));
  }
  return el("div", { class: "msg entrando" },
    el("div", { class: "avatar humano usuario", "aria-hidden": "true" }, iniciais(m.nome || "U")),
    el("div", { class: "conteudo" },
      el("span", { class: "autor" }, m.nome || t("gaveta.usuario"), el("span", { class: "hora" }, horaDe(m.data))),
      el("div", { class: "balao-bot" }, m.texto)));
}

function bolhaUsuarioDigitando(mostrar) {
  const caixaMsgs = $("gaveta-mensagens");
  if (!mostrar) { gaveta.bolha?.remove(); gaveta.bolha = null; return; }
  if (!gaveta.bolha) {
    gaveta.bolha = el("div", { class: "msg entrando" },
      el("div", { class: "avatar humano usuario", "aria-hidden": "true" }, iniciais(gaveta.nome)),
      el("div", { class: "conteudo" },
        el("span", { class: "autor" }, t("comum.digitando", { nome: gaveta.nome })),
        el("div", { class: "balao-bot digitando", role: "status", "aria-label": t("gaveta.usuario_digitando") },
          el("span"), el("span"), el("span"))));
  }
  if (caixaMsgs.lastElementChild !== gaveta.bolha) { caixaMsgs.append(gaveta.bolha); rolarGaveta(); }
}

function estadoDaGaveta(r) {
  const ativa = Boolean(r.tecnico);
  gaveta.ativa = ativa;
  const presenca = $("presenca");
  presenca.textContent = t(r.chat.online ? "gaveta.com_chat" : r.chat.disponivel ? "gaveta.sem_atividade" : "gaveta.fechado");
  presenca.classList.toggle("online", r.chat.online);
  $("gaveta-iniciar").hidden = ativa || !r.chat.disponivel;
  $("gaveta-form").hidden = !ativa;
  $("gaveta-acoes").hidden = !ativa;
  if (!ativa && !r.chat.disponivel) {
    $("gaveta-aviso").textContent = t("gaveta.saiu");
    $("gaveta-aviso").hidden = false;
  } else if ($("gaveta-aviso").dataset.fixo !== "1") {
    $("gaveta-aviso").hidden = true;
  }
}

function receber(r) {
  const caixaMsgs = $("gaveta-mensagens");
  for (const m of r.mensagens) {
    if (m.id <= gaveta.desde) continue;
    gaveta.desde = m.id;
    bolhaUsuarioDigitando(false);
    caixaMsgs.append(bolhaDaConversa(m));
    rolarGaveta();
  }
  marcarLidas(gaveta.protocolo, gaveta.desde);
  estadoDaGaveta(r);
  bolhaUsuarioDigitando(Boolean(r.usuario_digitando));
}

async function consultarConversa() {
  if (!gaveta) return;
  try {
    receber(await api("GET", `/tecnico/chamados/${encodeURIComponent(gaveta.protocolo)}/conversa?desde=${gaveta.desde}`,
      undefined, true));
  } catch (e) { }
}

function abrirConversa(c) {
  fecharConversa();
  if (fechandoGaveta) { clearTimeout(fechandoGaveta); fechandoGaveta = null; }
  $("gaveta").classList.remove("fechando");
  $("veu").classList.remove("fechando");
  gaveta = { protocolo: c.protocolo, desde: 0, relogio: null, ativa: false, bolha: null,
    nome: c.email ? c.email.split("@")[0] : t("gaveta.usuario") };
  $("gaveta-titulo").textContent = c.email || t("gaveta.sem_email");
  $("gaveta-avatar").textContent = iniciais(gaveta.nome);
  $("gaveta-protocolo").textContent = c.protocolo;
  $("gaveta-descricao").textContent = `“${c.descricao}”`;
  $("gaveta-mensagens").replaceChildren();
  $("gaveta-aviso").hidden = true;
  $("gaveta-aviso").dataset.fixo = "";
  $("gaveta").hidden = $("veu").hidden = false;
  document.body.classList.add("com-gaveta");
  consultarConversa().then(() => (gaveta?.ativa ? $("gaveta-texto") : $("iniciar-conversa")).focus());
  gaveta.relogio = setInterval(consultarConversa, CONSULTAR_CONVERSA_MS);
}

let fechandoGaveta = null;
function fecharConversa() {
  if (!gaveta) return;
  clearInterval(gaveta.relogio);
  gaveta = null;
  const rapido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  $("gaveta").classList.add("fechando");
  $("veu").classList.add("fechando");
  fechandoGaveta = setTimeout(() => {
    $("gaveta").hidden = $("veu").hidden = true;
    $("gaveta").classList.remove("fechando");
    $("veu").classList.remove("fechando");
    fechandoGaveta = null;
  }, rapido ? 0 : 170);
  document.body.classList.remove("com-gaveta");
  desenhar();
}

function avisoNaGaveta(texto) {
  $("gaveta-aviso").textContent = texto;
  $("gaveta-aviso").hidden = !texto;
  $("gaveta-aviso").dataset.fixo = texto ? "1" : "";
}

$("iniciar-conversa").addEventListener("click", async (e) => {
  const botao = e.currentTarget;
  botao.disabled = true;
  try {
    receber(await api("POST", `/tecnico/chamados/${encodeURIComponent(gaveta.protocolo)}/conversa`));
    avisoNaGaveta("");
    $("gaveta-texto").focus();
    carregar(true);
  } catch (err) {
    avisoNaGaveta(err.message);
  } finally { botao.disabled = false; }
});

$("gaveta-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const caixaTexto = $("gaveta-texto");
  const texto = caixaTexto.value.trim();
  if (!texto || !gaveta) return;
  caixaTexto.value = "";
  ajustarGaveta();
  try {
    await api("POST", `/tecnico/chamados/${encodeURIComponent(gaveta.protocolo)}/conversa/mensagem`, { texto });
    avisoNaGaveta("");
    await consultarConversa();
  } catch (err) {
    caixaTexto.value = texto;
    avisoNaGaveta(t("gaveta.nao_enviou", { e: err.message }));
  }
});

function ajustarGaveta() {
  const caixaTexto = $("gaveta-texto");
  caixaTexto.style.height = "auto";
  caixaTexto.style.height = Math.min(caixaTexto.scrollHeight, 140) + "px";
}
$("gaveta-texto").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("gaveta-form").requestSubmit(); }
});
$("gaveta-texto").addEventListener("input", () => {
  ajustarGaveta();
  if (!gaveta?.ativa || Date.now() - avisoDigitando < 2000) return;
  avisoDigitando = Date.now();
  api("POST", `/tecnico/chamados/${encodeURIComponent(gaveta.protocolo)}/conversa/digitando`).catch(() => {});
});

$("encerrar-conversa").addEventListener("click", async () => {
  if (!gaveta) return;
  try {
    receber(await api("POST", `/tecnico/chamados/${encodeURIComponent(gaveta.protocolo)}/conversa/encerrar`));
  } catch (err) { avisoNaGaveta(err.message); }
});

$("fechar-gaveta").addEventListener("click", fecharConversa);
$("veu").addEventListener("click", fecharConversa);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && gaveta) fecharConversa(); });


window.addEventListener("idioma-mudou", () => {
  if (!eu) return;
  $("papel-usuario").textContent = tValor(eu.papel || "tecnico");
  if (estado.dataset.estado === "pronto") {
    definirEstado("pronto", t("painel.atualizado_as", { h: new Date().toLocaleTimeString(localeAtual(), { hour: "2-digit", minute: "2-digit" }) }));
  }
  desenhar();
});

traduzirPagina();
Conta.iniciar({ area: "/tecnico", aoSair: sairDoPainel });
Acesso.iniciar({
  area: "/tecnico", titulo: t("acesso.entrar_painel"), explica: t("acesso.explica_painel"),
  aoEntrar: entrarComo, aoMostrarAcesso: sairDoPainel,
});
