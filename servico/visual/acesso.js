"use strict";
(() => {
  const t = (...a) => window.t(...a);
  let opcoes = null;

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

  async function pedir(metodo, caminho, corpo) {
    const resp = await fetch(caminho, {
      method: metodo, credentials: "same-origin",
      headers: corpo ? { "Content-Type": "application/json" } : {},
      body: corpo ? JSON.stringify(corpo) : undefined,
    });
    const dados = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const erro = new Error(Array.isArray(dados.detail) ? t("comum.dados_invalidos") : (dados.detail || t("comum.erro", { n: resp.status })));
      erro.status = resp.status;
      throw erro;
    }
    return dados;
  }

  function campo(rotulo, id, tipo, autocomplete) {
    return el("label", { class: "campo-acesso" }, rotulo,
      el("input", { type: tipo, id, autocomplete, required: true }));
  }


  function telaLogin() {
    const erro = el("p", { class: "erro-acesso", role: "alert", hidden: true });
    const form = el("form", { class: "cartao-acesso", novalidate: true },
      el("h2", {}, opcoes.titulo),
      el("p", { class: "explica" }, opcoes.explica),
      campo(t("acesso.email"), "acesso-email", "email", "username"),
      campo(t("acesso.senha"), "acesso-senha", "password", "current-password"),
      erro,
      el("button", { class: "botao-pri grande", type: "submit" }, t("acesso.entrar")),
      el("p", { class: "rodape-acesso" }, t("acesso.esqueceu")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const botao = form.querySelector("button[type=submit]");
      const email = form.querySelector("#acesso-email").value.trim();
      const senha = form.querySelector("#acesso-senha").value;
      erro.hidden = true;
      if (!email || !senha) { erro.textContent = t("acesso.preencha"); erro.hidden = false; return; }
      botao.disabled = true;
      try {
        const perfil = await pedir("POST", `${opcoes.area}/entrar`, { email, senha });
        decidir(perfil);
      } catch (err) {
        erro.textContent = err.message;
        erro.hidden = false;
        form.querySelector("#acesso-senha").select();
      } finally { botao.disabled = false; }
    });
    return form;
  }

  function formularioSenha({ primeiroAcesso, aoTrocar }) {
    const erro = el("p", { class: "erro-acesso", role: "alert", hidden: true });
    const regras = el("ul", { class: "regras" },
      el("li", { "data-regra": "tamanho" }, t("acesso.regra_tamanho")),
      el("li", { "data-regra": "mistura" }, t("acesso.regra_mistura")),
      el("li", { "data-regra": "igual" }, t("acesso.regra_igual")));
    const form = el("form", { class: primeiroAcesso ? "cartao-acesso" : "form-senha", novalidate: true },
      primeiroAcesso ? el("span", { class: "selo" }, t("acesso.primeiro")) : null,
      primeiroAcesso ? el("h2", {}, t("acesso.crie")) : null,
      primeiroAcesso ? el("p", { class: "explica" }, t("acesso.crie_explica")) : null,
      campo(t(primeiroAcesso ? "acesso.provisoria" : "acesso.atual"), "senha-atual", "password", "current-password"),
      campo(t("acesso.nova"), "senha-nova", "password", "new-password"),
      campo(t("acesso.repita"), "senha-repetida", "password", "new-password"),
      regras, erro,
      el("button", { class: `botao-pri${primeiroAcesso ? " grande" : ""}`, type: "submit" },
        t(primeiroAcesso ? "acesso.salvar_entrar" : "conta.trocar_senha")));
    const valor = (id) => form.querySelector(`#${id}`).value;
    const conferir = () => {
      const nova = valor("senha-nova"), repetida = valor("senha-repetida");
      const ok = { tamanho: nova.length >= 8, mistura: /[A-Za-z]/.test(nova) && /\d/.test(nova),
        igual: nova.length > 0 && nova === repetida };
      for (const [nome, certo] of Object.entries(ok)) regras.querySelector(`[data-regra="${nome}"]`).classList.toggle("ok", certo);
      return Object.values(ok).every(Boolean);
    };
    form.addEventListener("input", conferir);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      erro.hidden = true;
      if (!valor("senha-atual")) { erro.textContent = t("acesso.digite_provisoria"); erro.hidden = false; return; }
      if (!conferir()) { erro.textContent = t("acesso.nao_atende"); erro.hidden = false; return; }
      const botao = form.querySelector("button[type=submit]");
      botao.disabled = true;
      try {
        const perfil = await pedir("POST", `${opcoes.area}/senha`, { atual: valor("senha-atual"), nova: valor("senha-nova") });
        form.reset();
        conferir();
        aoTrocar(perfil);
      } catch (err) {
        erro.textContent = err.message;
        erro.hidden = false;
      } finally { botao.disabled = false; }
    });
    return form;
  }

  function mostrar(conteudo, foco) {
    const caixa = document.getElementById("acesso");
    caixa.replaceChildren(conteudo);
    caixa.hidden = false;
    opcoes.aoMostrarAcesso?.();
    setTimeout(() => caixa.querySelector(foco)?.focus(), 0);
  }

  function decidir(perfil) {
    if (perfil.trocar_senha) {
      mostrar(formularioSenha({ primeiroAcesso: true, aoTrocar: decidir }), "#senha-atual");
      return;
    }
    const caixa = document.getElementById("acesso");
    caixa.hidden = true;
    caixa.replaceChildren();
    opcoes.aoEntrar(perfil);
  }

  function mostrarLogin() { mostrar(telaLogin(), "#acesso-email"); }

  async function iniciar(config) {
    opcoes = config;
    try {
      decidir(await pedir("GET", `${opcoes.area}/eu`));
    } catch (e) {
      mostrarLogin();
    }
  }

  async function sair() {
    try { await pedir("POST", `${opcoes.area}/sair`); } catch (e) { }
    mostrarLogin();
  }

  window.Acesso = { iniciar, mostrarLogin, sair, pedir, formularioSenha, area: () => opcoes?.area };
})();
