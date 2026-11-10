"use strict";
(() => {
  let perfil = null;
  let area = "chamados";
  let dias = 14;
  let tipoContas = "tecnico";
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";

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
  function svg(tag, atributos = {}, ...filhos) {
    const e = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(atributos)) if (v != null) e.setAttribute(k, v);
    for (const f of filhos.flat()) if (f) e.append(f);
    return e;
  }

  async function pedir(metodo, caminho, corpo) {
    const resp = await fetch(caminho, {
      method: metodo, credentials: "same-origin",
      headers: corpo ? { "Content-Type": "application/json" } : {},
      body: corpo ? JSON.stringify(corpo) : undefined,
    });
    const dados = await resp.json().catch(() => ({}));
    if (resp.status === 401) { window.Acesso.mostrarLogin(); throw new Error(t("comum.sessao_terminou")); }
    if (!resp.ok) throw new Error(Array.isArray(dados.detail) ? t("comum.dados_invalidos") : (dados.detail || t("comum.erro", { n: resp.status })));
    return dados;
  }

  const numero = (n, casas = 0) => new Intl.NumberFormat(localeAtual(), { minimumFractionDigits: casas, maximumFractionDigits: casas }).format(n);
  function duracao(min) {
    if (min == null) return "-";
    const h = Math.floor(min / 60), m = min % 60;
    if (h >= 24) return `${Math.floor(h / 24)} d ${h % 24} h`;
    return h ? `${h} h ${m} min` : `${m} min`;
  }


  function mostrar(qual) {
    area = qual;
    document.querySelectorAll("#abas-painel [data-area]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.area === qual)));
    $("tela-painel").hidden = qual !== "chamados";
    $("tela-indicadores").hidden = qual !== "indicadores";
    $("tela-contas").hidden = qual !== "contas";
    if (qual === "indicadores") carregarIndicadores();
    if (qual === "contas") carregarContas();
  }
  document.querySelectorAll("#abas-painel [data-area]").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.area)));


  function cabecalho(titulo, sub, extra) {
    return el("header", { class: "cabeca-admin" }, el("div", {}, el("h2", {}, titulo), el("p", {}, sub)), extra);
  }

  function tile(rotulo, valor, detalhe, aviso) {
    return el("article", { class: "tile" },
      el("span", { class: "tile-rotulo" }, rotulo),
      el("strong", { class: "tile-valor" }, valor),
      el("span", { class: "tile-detalhe" }, detalhe),
      aviso || null);
  }

  function comTooltip(caixa) {
    const dica = el("div", { class: "dica-grafico", role: "status", hidden: true });
    caixa.append(dica);
    return (alvo, texto) => {
      const mostrarDica = () => {
        dica.textContent = texto;
        dica.hidden = false;
        const c = caixa.getBoundingClientRect(), a = alvo.getBoundingClientRect();
        const x = Math.min(Math.max(a.left + a.width / 2 - c.left, 60), c.width - 60);
        dica.style.left = `${x}px`;
        dica.style.top = `${a.top - c.top - 8}px`;
      };
      alvo.addEventListener("mouseenter", mostrarDica);
      alvo.addEventListener("focus", mostrarDica);
      alvo.addEventListener("mouseleave", () => { dica.hidden = true; });
      alvo.addEventListener("blur", () => { dica.hidden = true; });
    };
  }

  function caminhoBarra(x, y, w, h, vertical) {
    const r = Math.min(4, vertical ? w / 2 : h / 2, vertical ? h : w);
    if (vertical) return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  function tabelaDados(cabecas, linhas) {
    return el("details", { class: "ver-tabela" }, el("summary", {}, t("admin.ver_tabela")),
      el("table", {}, el("thead", {}, el("tr", {}, cabecas.map((c) => el("th", { scope: "col" }, c)))),
        el("tbody", {}, linhas.map((l) => el("tr", {}, l.map((v) => el("td", {}, String(v))))))));
  }

  function graficoDias(atividade) {
    const L = 640, A = 200, m = { t: 16, r: 8, b: 26, l: 28 };
    const maximo = Math.max(1, ...atividade.map((d) => d.atendimentos));
    const passo = maximo <= 5 ? 1 : Math.ceil(maximo / 4);
    const topo = Math.ceil(maximo / passo) * passo;
    const largura = (L - m.l - m.r) / atividade.length;
    const y = (v) => m.t + (A - m.t - m.b) * (1 - v / topo);
    const caixa = el("div", { class: "grafico" });
    const dica = comTooltip(caixa);
    const linhasGrade = [];
    for (let v = 0; v <= topo; v += passo) {
      linhasGrade.push(svg("line", { x1: m.l, x2: L - m.r, y1: y(v), y2: y(v), class: v === 0 ? "eixo" : "grade" }),
        svg("text", { x: m.l - 6, y: y(v) + 4, class: "rotulo-eixo", "text-anchor": "end" }, document.createTextNode(String(v))));
    }
    const barras = atividade.map((d, i) => {
      const x = m.l + i * largura + 2, w = Math.max(2, largura - 4), h = y(0) - y(d.atendimentos);
      const g = svg("g", { class: "barra-alvo", tabindex: "0", role: "img",
        "aria-label": t("admin.tooltip_dia", { d: d.dia, n: d.atendimentos }) },
        svg("rect", { x: m.l + i * largura, y: m.t, width: largura, height: A - m.t - m.b, class: "area-alvo" }),
        d.atendimentos ? svg("path", { d: caminhoBarra(x, y(d.atendimentos), w, h, true), class: "barra" }) : null);
      dica(g, t("admin.tooltip_dia", { d: d.dia, n: d.atendimentos }));
      const mostrarRotulo = atividade.length <= 14 || i % Math.ceil(atividade.length / 10) === 0 || i === atividade.length - 1;
      return [g, mostrarRotulo ? svg("text", { x: m.l + i * largura + largura / 2, y: A - 8, class: "rotulo-eixo", "text-anchor": "middle" },
        document.createTextNode(d.dia)) : null];
    });
    caixa.prepend(svg("svg", { viewBox: `0 0 ${L} ${A}`, class: "svg-grafico", role: "group",
      "aria-label": t("admin.g_dia") }, linhasGrade, barras.flat()));
    return caixa;
  }

  function barrasHorizontais(itens) {
    const maximo = Math.max(1, ...itens.map((i) => i.valor));
    const caixa = el("div", { class: "grafico barras-h" });
    const dica = comTooltip(caixa);
    for (const item of itens) {
      const linha = el("div", { class: "linha-barra", tabindex: "0", "aria-label": `${item.rotulo}: ${item.valor}${item.nota ? ` · ${item.nota}` : ""}` },
        el("span", { class: "rotulo-barra" }, item.rotulo),
        el("span", { class: "trilho-barra" }, el("span", { class: "preenchimento", style: null })),
        el("span", { class: "valor-barra" }, numero(item.valor)),
        item.nota ? el("span", { class: "nota-barra" }, item.nota) : null);
      linha.querySelector(".preenchimento").style.width = item.valor ? `${(100 * item.valor) / maximo}%` : "0";
      dica(linha, `${item.rotulo}: ${numero(item.valor)}${item.nota ? ` · ${item.nota}` : ""}`);
      caixa.append(linha);
    }
    return caixa;
  }

  function cartaoGrafico(titulo, sub, conteudo, tabela) {
    return el("section", { class: "cartao-grafico" }, el("h3", {}, titulo), el("p", { class: "sub-grafico" }, sub), conteudo, tabela);
  }

  function desenharIndicadores(d) {
    const tela = $("tela-indicadores");
    const seletor = el("div", { class: "segmentos", role: "radiogroup", "aria-label": t("admin.periodo") },
      [7, 14, 30].map((n) => el("button", { type: "button", role: "radio", "aria-checked": String(n === dias),
        onclick: () => { dias = n; carregarIndicadores(); } }, t("admin.dias", { n }))));
    const fila = d.fila, chat = d.chat, av = d.avaliacoes;

    const tiles = el("div", { class: "tiles" },
      tile(t("admin.k_atendimentos"), numero(chat.atendimentos),
        t("admin.k_atendimentos_d", { r: chat.resolvidos, e: chat.encaminhados, s: chat.sem_desfecho })),
      tile(t("admin.k_resolucao"), chat.taxa_resolucao == null ? "-" : `${chat.taxa_resolucao}%`,
        chat.taxa_resolucao == null ? t("admin.sem_dados") : t("admin.k_resolucao_d", { n: chat.resolvidos + chat.encaminhados })),
      tile(t("admin.k_nota"), av.media == null ? "-" : `${numero(av.media, 1)} ★`,
        av.total ? t("admin.k_nota_d", { n: av.total }) : t("admin.sem_dados")),
      tile(t("admin.k_fila"), numero(fila.abertos + fila.em_atendimento),
        t("admin.k_fila_d", { a: fila.abertos, e: fila.em_atendimento }),
        el("span", { class: `selo-status ${fila.atrasados ? "critico" : "bom"}` },
          el("span", { "aria-hidden": "true" }, fila.atrasados ? "!" : "✓"),
          fila.atrasados ? t("admin.k_atrasados", { n: fila.atrasados }) : t("admin.k_em_dia"))),
      tile(t("admin.k_tempo"), duracao(fila.tempo_medio_minutos),
        fila.concluidos ? t("admin.k_tempo_d", { n: fila.concluidos }) : t("admin.sem_dados")));

    const categorias = d.categorias.map((c) => ({
      rotulo: tValor(c.categoria), valor: c.total,
      nota: `${t("admin.resolvido_pct", { p: c.resolvidos + c.encaminhados ? Math.round((100 * c.resolvidos) / (c.resolvidos + c.encaminhados)) : 0 })} · ${t("admin.encaminhados_n", { n: c.encaminhados })}`,
    }));
    const notas = [...av.distribuicao].reverse().map((n) => ({ rotulo: "★".repeat(n.nota), valor: n.quantidade }));

    const lista = (itens, vazio, item) => (itens.length ? el("ol", { class: "lista-admin" }, itens.map(item)) : el("p", { class: "vazio-admin" }, vazio));

    tela.replaceChildren(
      cabecalho(t("admin.ind_titulo"), t("admin.ind_sub"), seletor),
      tiles,
      el("div", { class: "grade-graficos" },
        cartaoGrafico(t("admin.g_dia"), t("admin.g_dia_sub", { n: dias }), graficoDias(d.atividade),
          tabelaDados([t("admin.dia"), t("admin.quantidade")], d.atividade.map((x) => [x.dia, x.atendimentos]))),
        cartaoGrafico(t("admin.g_notas"), t("admin.g_notas_sub"),
          av.total ? barrasHorizontais(notas) : el("p", { class: "vazio-admin" }, t("admin.sem_dados")),
          tabelaDados([t("admin.nota"), t("admin.quantidade")], av.distribuicao.map((x) => [x.nota, x.quantidade])))),
      cartaoGrafico(t("admin.g_categoria"), t("admin.g_categoria_sub"),
        categorias.length ? barrasHorizontais(categorias) : el("p", { class: "vazio-admin" }, t("admin.sem_dados")),
        tabelaDados([t("admin.categoria"), t("admin.total"), t("admin.resolvidos"), t("admin.encaminhados")],
          d.categorias.map((c) => [tValor(c.categoria), c.total, c.resolvidos, c.encaminhados]))),
      el("section", { class: "cartao-grafico" }, el("h3", {}, t("admin.t_tecnicos")),
        d.tecnicos.length ? el("table", { class: "tabela-admin" },
          el("thead", {}, el("tr", {}, [t("admin.tecnico"), t("admin.na_fila"), t("admin.atendendo"), t("admin.concluidos"), t("admin.atrasados")]
            .map((c, i) => el("th", { scope: "col", class: i ? "num" : "" }, c)))),
          el("tbody", {}, d.tecnicos.map((x) => el("tr", {},
            el("td", {}, x.nome), el("td", { class: "num" }, x.abertos), el("td", { class: "num" }, x.em_atendimento),
            el("td", { class: "num" }, x.concluidos), el("td", { class: `num${x.atrasados ? " atrasado" : ""}` }, x.atrasados)))))
          : el("p", { class: "vazio-admin" }, t("admin.sem_tecnicos"))),
      el("div", { class: "grade-graficos" },
        el("section", { class: "cartao-grafico" }, el("h3", {}, t("admin.t_nao_entendidas")),
          el("p", { class: "sub-grafico" }, t("admin.t_nao_entendidas_d")),
          lista(d.nao_entendidas, t("admin.nada_aqui"), (x) => el("li", {}, el("q", {}, x.texto), el("span", { class: "vezes" }, t("admin.vezes", { n: x.vezes }))))),
        el("section", { class: "cartao-grafico" }, el("h3", {}, t("admin.t_piores")),
          el("p", { class: "sub-grafico" }, t("admin.t_piores_d")),
          lista(av.piores_solucoes, t("admin.nada_aqui"), (x) => el("li", {}, el("span", {}, x.solucao),
            el("span", { class: "vezes" }, t("admin.media_de", { m: numero(x.media, 1), n: x.avaliacoes })))))));
  }

  async function carregarIndicadores() {
    const tela = $("tela-indicadores");
    if (!tela.childElementCount) tela.replaceChildren(el("p", { class: "vazio-admin" }, t("admin.carregando")));
    try {
      desenharIndicadores(await pedir("GET", `/tecnico/admin/indicadores?dias=${dias}`));
    } catch (e) {
      tela.replaceChildren(el("p", { class: "aviso" }, t("admin.erro", { e: e.message })));
    }
  }


  function avisoSenha(titulo, email, senha) {
    const copiar = el("button", { class: "botao-sec", type: "button" }, t("admin.c_copiar"));
    copiar.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(senha); copiar.textContent = t("admin.c_copiado"); } catch (e) { }
    });
    return el("div", { class: "senha-gerada", role: "status" },
      el("strong", {}, t(titulo, { e: email })), el("span", {}, t("admin.c_senha_uma_vez")),
      el("span", { class: "linha-senha" }, el("code", {}, senha), copiar));
  }

  function linhaConta(c, resultado) {
    const eu = tipoContas === "tecnico" && c.email === perfil.email;
    const iniciais = c.nome.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
    const acao = (rotulo, classe, fn) => el("button", { class: classe, type: "button", disabled: eu, onclick: fn }, rotulo);
    return el("li", { class: `conta-admin${c.ativo ? "" : " desativada"}` },
      el("span", { class: "avatar-usuario", "aria-hidden": "true" }, iniciais),
      el("div", { class: "quem-conta" },
        el("strong", {}, c.nome, eu ? el("small", {}, ` ${t("admin.c_voce")}`) : null),
        el("span", {}, c.email),
        el("span", { class: "etiquetas-conta" },
          el("span", { class: "pilula" }, tValor(c.papel)),
          el("span", { class: `pilula ${c.ativo ? "ativa" : "inativa"}` }, t(c.ativo ? "admin.c_ativa" : "admin.c_desativada")),
          c.senha_provisoria ? el("span", { class: "pilula provisoria" }, t("admin.c_provisoria")) : null),
        el("span", { class: "acesso-conta" }, c.ultimo_login ? t("admin.c_ultimo", { d: c.ultimo_login }) : t("admin.c_nunca"))),
      el("div", { class: "acoes-conta" },
        acao(t("admin.c_gerar"), "botao-sec", async () => {
          if (!confirm(t("admin.c_confirma_gerar", { e: c.email }))) return;
          try {
            const r = await pedir("POST", "/tecnico/admin/contas/redefinir", { tipo: tipoContas, email: c.email });
            await carregarContas();
            $("resultado-conta").replaceChildren(avisoSenha("admin.c_redefinida", r.email, r.senha_provisoria));
          } catch (e) { resultado.replaceChildren(el("p", { class: "erro-acesso" }, t("admin.c_erro", { e: e.message }))); }
        }),
        acao(t(c.ativo ? "admin.c_desativar" : "admin.c_reativar"), `botao-sec${c.ativo ? " perigo" : ""}`, async () => {
          if (c.ativo && !confirm(t("admin.c_confirma_desativar", { e: c.email }))) return;
          try {
            await pedir("POST", "/tecnico/admin/contas/ativo", { tipo: tipoContas, email: c.email, ativo: !c.ativo });
            await carregarContas();
          } catch (e) { resultado.replaceChildren(el("p", { class: "erro-acesso" }, t("admin.c_erro", { e: e.message }))); }
        })));
  }

  function desenharContas(dados) {
    const tela = $("tela-contas");
    const lista = tipoContas === "tecnico" ? dados.tecnicos : dados.colaboradores;
    const resultado = el("div", { id: "resultado-conta", "aria-live": "polite" });
    const form = el("form", { class: "form-conta", novalidate: true },
      el("h3", {}, t("admin.c_nova")),
      el("div", { class: "campos-conta" },
        el("label", { class: "campo-acesso" }, t("admin.c_nome"), el("input", { name: "nome", required: true, maxlength: "100", autocomplete: "off" })),
        el("label", { class: "campo-acesso" }, t("admin.c_email"), el("input", { name: "email", type: "email", required: true, maxlength: "200", autocomplete: "off" }))),
      tipoContas === "tecnico" ? el("label", { class: "marcar-admin" }, el("input", { type: "checkbox", name: "admin" }), t("admin.c_admin")) : null,
      el("button", { class: "botao-pri", type: "submit" }, t("admin.c_criar")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const dadosForm = new FormData(form);
      const botao = form.querySelector("button[type=submit]");
      botao.disabled = true;
      try {
        const r = await pedir("POST", "/tecnico/admin/contas", {
          tipo: tipoContas, nome: String(dadosForm.get("nome") || "").trim(), email: String(dadosForm.get("email") || "").trim(),
          admin: dadosForm.get("admin") === "on",
        });
        await carregarContas();
        $("resultado-conta").replaceChildren(avisoSenha("admin.c_criada", r.email, r.senha_provisoria));
      } catch (err) {
        resultado.replaceChildren(el("p", { class: "erro-acesso" }, t("admin.c_erro", { e: err.message })));
      } finally { botao.disabled = false; }
    });
    const seletor = el("div", { class: "segmentos", role: "radiogroup", "aria-label": t("admin.c_titulo") },
      [["tecnico", "admin.c_tecnicos", dados.tecnicos.length], ["colaborador", "admin.c_colaboradores", dados.colaboradores.length]]
        .map(([v, k, n]) => el("button", { type: "button", role: "radio", "aria-checked": String(v === tipoContas),
          onclick: () => { tipoContas = v; desenharContas(dados); } }, `${t(k)} (${n})`)));
    tela.replaceChildren(
      cabecalho(t("admin.c_titulo"), t("admin.c_sub"), seletor),
      el("div", { class: "grade-contas" },
        el("section", { class: "cartao-grafico" }, form, resultado),
        el("section", { class: "cartao-grafico" },
          lista.length ? el("ul", { class: "lista-contas" }, lista.map((c) => linhaConta(c, resultado)))
            : el("p", { class: "vazio-admin" }, t("admin.c_vazio")))));
  }

  async function carregarContas() {
    const tela = $("tela-contas");
    try {
      const dados = await pedir("GET", "/tecnico/admin/contas");
      const aviso = $("resultado-conta")?.firstChild;
      desenharContas(dados);
      if (aviso) $("resultado-conta").replaceChildren(aviso);
    } catch (e) {
      tela.replaceChildren(el("p", { class: "aviso" }, t("admin.c_erro", { e: e.message })));
    }
  }


  function iniciar(p) {
    perfil = p;
    const admin = p.papel === "admin";
    $("abas-painel").hidden = !admin;
    if (!admin && area !== "chamados") mostrar("chamados");
    else if (area !== "chamados") mostrar(area);
  }
  function sair() {
    perfil = null;
    $("abas-painel").hidden = true;
    $("tela-indicadores").hidden = $("tela-contas").hidden = true;
    $("tela-indicadores").replaceChildren();
    $("tela-contas").replaceChildren();
    area = "chamados";
    document.querySelectorAll("#abas-painel [data-area]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.area === "chamados")));
  }
  window.addEventListener("idioma-mudou", () => { if (perfil && area !== "chamados") mostrar(area); });

  window.Admin = { iniciar, sair, area: () => area };
})();
