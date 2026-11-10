"use strict";
(() => {
  const CHAVE = "suporte-preferencias";
  const PADRAO = { tema: "auto", fonte: "plex", tamanho: "normal", idioma: "pt" };
  const OPCOES = {
    tema: ["auto", "claro", "escuro"],
    fonte: ["plex", "sistema", "legivel", "serifa"],
    tamanho: ["pequeno", "normal", "grande", "enorme"],
    idioma: ["pt", "es", "en"],
  };

  function ler() {
    let salvas = {};
    try { salvas = JSON.parse(localStorage.getItem(CHAVE) || "{}") || {}; } catch (e) { salvas = {}; }
    const prefs = { ...PADRAO };
    for (const [k, valores] of Object.entries(OPCOES)) if (valores.includes(salvas[k])) prefs[k] = salvas[k];
    return prefs;
  }

  function aplicar(prefs) {
    const raiz = document.documentElement;
    if (prefs.tema === "auto") delete raiz.dataset.tema; else raiz.dataset.tema = prefs.tema;
    raiz.dataset.fonte = prefs.fonte;
    raiz.dataset.tamanho = prefs.tamanho;
    raiz.lang = { pt: "pt-BR", es: "es", en: "en" }[prefs.idioma];
  }

  function salvar(mudancas) {
    const prefs = { ...ler(), ...mudancas };
    try { localStorage.setItem(CHAVE, JSON.stringify(prefs)); } catch (e) { }
    aplicar(prefs);
    return prefs;
  }

  window.Preferencias = { ler, salvar, aplicar, OPCOES };
  aplicar(ler());
})();
