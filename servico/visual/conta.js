"use strict";
(() => {
  const t = (...a) => window.t(...a);
  let opcoes = { area: null, aoSair: null };
  let janela = null, veu = null, voltarFoco = null;

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

  const iniciais = (nome) => String(nome || "?").split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();


  function grupoDeOpcoes(nome, titulo, itens, atual, aoEscolher, classe = "") {
    return el("fieldset", { class: `grupo-config ${classe}` },
      el("legend", {}, titulo),
      el("div", { class: "opcoes-config" }, itens.map(([valor, rotulo, extra]) =>
        el("label", { class: "opcao-config" },
          el("input", { type: "radio", name: `config-${nome}`, value: valor, checked: valor === atual,
            onchange: () => aoEscolher(valor) }),
          el("span", { class: "cartao-opcao" }, extra || null, el("span", { class: "rotulo-opcao" }, rotulo))))));
  }

  function painelConfig() {
    const p = window.Preferencias.ler();
    const salvar = (mudanca) => window.Preferencias.salvar(mudanca);
    const amostraTema = (tema) => el("span", { class: `amostra-tema tema-${tema}`, "aria-hidden": "true" },
      el("span", {}), el("span", {}), el("span", {}));
    return el("div", { class: "painel-config", role: "tabpanel", id: "aba-config" },
      grupoDeOpcoes("tema", t("conta.tema"), [
        ["auto", t("conta.tema_auto"), amostraTema("auto")],
        ["claro", t("conta.tema_claro"), amostraTema("claro")],
        ["escuro", t("conta.tema_escuro"), amostraTema("escuro")],
      ], p.tema, (tema) => salvar({ tema }), "temas"),
      grupoDeOpcoes("fonte", t("conta.fonte"), [
        ["plex", t("conta.fonte_plex"), el("span", { class: "amostra-fonte fonte-plex", "aria-hidden": "true" }, "Aa")],
        ["sistema", t("conta.fonte_sistema"), el("span", { class: "amostra-fonte fonte-sistema", "aria-hidden": "true" }, "Aa")],
        ["legivel", t("conta.fonte_legivel"), el("span", { class: "amostra-fonte fonte-legivel", "aria-hidden": "true" }, "Aa")],
        ["serifa", t("conta.fonte_serifa"), el("span", { class: "amostra-fonte fonte-serifa", "aria-hidden": "true" }, "Aa")],
      ], p.fonte, (fonte) => salvar({ fonte }), "fontes"),
      grupoDeOpcoes("tamanho", t("conta.tamanho"), [
        ["pequeno", t("conta.tam_pequeno")], ["normal", t("conta.tam_normal")],
        ["grande", t("conta.tam_grande")], ["enorme", t("conta.tam_enorme")],
      ], p.tamanho, (tamanho) => salvar({ tamanho }), "segmentado"),
      grupoDeOpcoes("idioma", t("conta.idioma"), [
        ["pt", "Português"], ["es", "Español"], ["en", "English"],
      ], p.idioma, (idioma) => {
        salvar({ idioma });
        window.traduzirPagina();
        window.dispatchEvent(new CustomEvent("idioma-mudou"));
        abrir("config");
      }, "segmentado"),
      el("p", { class: "nota-config" }, t("conta.idioma_nota")),
      el("p", { class: "nota-config" }, t("conta.salvo_local")));
  }


  function painelConta() {
    const corpo = el("div", { class: "painel-conta", role: "tabpanel", id: "aba-conta" },
      el("p", { class: "carregando-conta" }, t("comum.carregando")));
    (async () => {
      try {
        const perfil = await window.Acesso.pedir("GET", `${opcoes.area}/eu`);
        const dado = (rotulo, valor) => el("div", {}, el("dt", {}, rotulo), el("dd", {}, valor || "-"));
        const aviso = el("p", { class: "aviso-ok", role: "status", hidden: true }, t("conta.senha_trocada"));
        corpo.replaceChildren(
          el("div", { class: "cabeca-conta" },
            el("span", { class: "avatar-usuario grande", "aria-hidden": "true" }, iniciais(perfil.nome)),
            el("div", {}, el("strong", {}, perfil.nome), el("span", {}, perfil.email))),
          el("h3", {}, t("conta.dados")),
          el("dl", { class: "dados-conta" },
            dado(t("conta.nome"), perfil.nome), dado(t("acesso.email"), perfil.email),
            dado(t("conta.papel"), window.tValor(perfil.papel)),
            dado(t("conta.senha_alterada"), perfil.senha_alterada_em),
            dado(t("conta.login_anterior"), perfil.login_anterior || t("conta.primeiro_acesso"))),
          el("h3", {}, t("conta.trocar_senha")),
          window.Acesso.formularioSenha({ primeiroAcesso: false, aoTrocar: () => { aviso.hidden = false; } }),
          aviso,
          el("div", { class: "rodape-conta" },
            el("button", { class: "botao-sec sair-conta", type: "button", onclick: async () => {
              fechar();
              await window.Acesso.sair();
              opcoes.aoSair?.();
            } }, t("conta.sair"))));
      } catch (e) {
        corpo.replaceChildren(el("p", { class: "carregando-conta" }, t("conta.sem_login")));
      }
    })();
    return corpo;
  }


  function abas(ativa) {
    if (!opcoes.area) return null;
    const aba = (id, rotulo) => el("button", { type: "button", role: "tab", "aria-selected": String(id === ativa),
      "aria-controls": `aba-${id}`, onclick: () => abrir(id) }, rotulo);
    return el("div", { class: "abas-conta", role: "tablist" }, aba("conta", t("conta.aba_conta")), aba("config", t("conta.aba_config")));
  }

  function fechar() {
    if (!janela) return;
    janela.remove(); veu.remove();
    janela = veu = null;
    document.removeEventListener("keydown", teclas);
    voltarFoco?.focus();
  }

  function teclas(e) {
    if (e.key === "Escape") { fechar(); return; }
    if (e.key !== "Tab" || !janela) return;
    const focaveis = [...janela.querySelectorAll("button, input, select, textarea, [tabindex]:not([tabindex='-1'])")]
      .filter((x) => !x.disabled && x.offsetParent !== null);
    if (!focaveis.length) return;
    const [primeiro, ultimo] = [focaveis[0], focaveis[focaveis.length - 1]];
    if (e.shiftKey && document.activeElement === primeiro) { e.preventDefault(); ultimo.focus(); }
    else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primeiro.focus(); }
  }

  function abrir(aba = opcoes.area ? "conta" : "config") {
    const jaAberta = Boolean(janela);
    if (!jaAberta) voltarFoco = document.activeElement;
    janela?.remove(); veu?.remove();
    veu = el("div", { class: "veu-modal", onclick: fechar });
    janela = el("div", { class: "modal-conta", role: "dialog", "aria-modal": "true", "aria-labelledby": "titulo-conta" },
      el("header", { class: "topo-modal" },
        el("h2", { id: "titulo-conta" }, opcoes.area ? t("comum.conta_config") : t("comum.configuracoes")),
        el("button", { class: "fechar", type: "button", "aria-label": t("comum.fechar"), onclick: fechar }, "×")),
      abas(aba),
      el("div", { class: "corpo-modal" }, aba === "conta" && opcoes.area ? painelConta() : painelConfig()));
    if (jaAberta) janela.classList.add("sem-animacao");
    document.body.append(veu, janela);
    document.addEventListener("keydown", teclas);
    (janela.querySelector('[aria-selected="true"]') || janela.querySelector("input:checked") || janela.querySelector(".fechar")).focus();
  }

  function iniciar(config) { opcoes = { ...opcoes, ...config }; }

  window.Conta = { iniciar, abrir, fechar };
})();
