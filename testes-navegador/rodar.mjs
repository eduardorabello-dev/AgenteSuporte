import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PYTHON = process.env.PYTHON || join(RAIZ, ".venv", "Scripts", "python.exe");
const PORTA_SITE = 5097, PORTA_CDP = 9297;
const BASE = `http://127.0.0.1:${PORTA_SITE}`;
const argumento = (nome) => { const i = process.argv.indexOf(nome); return i > 0 ? process.argv[i + 1] : null; };
const PRINTS = argumento("--prints") ? resolve(argumento("--prints")) : null;
const NAVEGADORES = [
  process.env.NAVEGADOR,
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);

const espera = (ms) => new Promise((r) => setTimeout(r, ms));
const resultados = [];
const errosNaPagina = [];


const pasta = mkdtempSync(join(tmpdir(), "suporte-e2e-"));
const ambiente = {
  ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONIOENCODING: "utf-8", DIRETORIO_MODO: "mock",
  TECNICOS: join(pasta, "tecnicos.json"), CONTAS_COLABORADORES: join(pasta, "colaboradores.json"),
  CHAMADOS_ENCAMINHADOS: join(pasta, "encaminhados.csv"), AVALIACOES: join(pasta, "avaliacoes.csv"),
  MENSAGENS_TECNICO: join(pasta, "mensagens.csv"), COLABORADORES: join(pasta, "colaboradores.csv"),
  ATENDIMENTOS: join(pasta, "atendimentos.csv"),
};
let servidor = null, navegador = null;

function encerrar(codigo) {
  try { navegador?.kill(); } catch { }
  try { servidor?.kill(); } catch { }
  setTimeout(() => { try { rmSync(pasta, { recursive: true, force: true }); } catch { } process.exit(codigo); }, 400);
}

function python(...args) {
  const r = spawnSync(PYTHON, args, { cwd: RAIZ, env: ambiente, encoding: "utf-8" });
  if (r.status !== 0) throw new Error(`python ${args.join(" ")} falhou:\n${r.stderr}`);
  return r.stdout;
}


async function abrirAba() {
  let alvo;
  for (let i = 0; i < 60 && !alvo; i++) {
    try { alvo = await (await fetch(`http://127.0.0.1:${PORTA_CDP}/json/new?about:blank`, { method: "PUT" })).json(); }
    catch { await espera(250); }
  }
  if (!alvo) throw new Error("O navegador não abriu o DevTools Protocol.");
  const ws = new WebSocket(alvo.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0;
  const pendentes = new Map();
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pendentes.has(m.id)) { pendentes.get(m.id)(m); pendentes.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown") errosNaPagina.push(m.params.exceptionDetails.exception?.description?.split("\n")[0]);
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error" && !/\b(401|422)\b/.test(m.params.entry.text)) {
      errosNaPagina.push(`${m.params.entry.text} ${m.params.entry.url || ""}`.trim());
    }
  });
  const cdp = (method, params = {}) => new Promise((r) => { const n = ++id; pendentes.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  await cdp("Page.enable"); await cdp("Runtime.enable"); await cdp("Log.enable");
  const aba = {
    cdp,
    async js(expr) {
      const r = await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
      if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description?.split("\n")[0]);
      return r.result?.result?.value;
    },
    async ate(expr, limiteMs = 6000) {
      const fim = Date.now() + limiteMs;
      while (Date.now() < fim) { if (await aba.js(`Boolean(${expr})`)) return true; await espera(150); }
      return false;
    },
    async ir(caminho, { largura = 1280, altura = 860, escuro = false } = {}) {
      await cdp("Emulation.setDeviceMetricsOverride", { width: largura, height: altura, deviceScaleFactor: 1, mobile: largura < 600 });
      await cdp("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: escuro ? "dark" : "light" }] });
      await cdp("Page.navigate", { url: BASE + caminho });
      await aba.ate("document.readyState === 'complete'");
      await espera(500);
    },
    digitar: (sel, valor) => aba.js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); e.value = ${JSON.stringify(valor)};
      e.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`),
    clicar: (sel) => aba.js(`(() => { document.querySelector(${JSON.stringify(sel)}).click(); return true; })()`),
    async print(nome, { inteira = false } = {}) {
      if (!PRINTS) return;
      await cdp("Page.bringToFront");
      await espera(250);
      const params = { format: "png" };
      if (inteira) {
        const m = await cdp("Page.getLayoutMetrics");
        params.clip = { x: 0, y: 0, width: m.result.cssLayoutViewport.clientWidth, height: Math.min(m.result.cssContentSize.height, 2400), scale: 1 };
        params.captureBeyondViewport = true;
      }
      const r = await cdp("Page.captureScreenshot", params);
      writeFileSync(join(PRINTS, nome), Buffer.from(r.result.data, "base64"));
    },
  };
  return aba;
}

async function entrarPrimeiraVez(aba, email, provisoria, nova) {
  await aba.ate("document.querySelector('#acesso-email')");
  await aba.digitar("#acesso-email", email);
  await aba.digitar("#acesso-senha", provisoria);
  await aba.js(`document.querySelector("#acesso form").requestSubmit(), true`);
  await aba.ate("document.querySelector('#senha-atual')");
  await aba.digitar("#senha-atual", provisoria);
  await aba.digitar("#senha-nova", nova);
  await aba.digitar("#senha-repetida", nova);
  await aba.js(`document.querySelector("#acesso form").requestSubmit(), true`);
}


async function cenario(nome, fn) {
  try {
    await fn();
    resultados.push([true, nome]);
    console.log(`  ✓ ${nome}`);
  } catch (e) {
    resultados.push([false, nome]);
    console.log(`  ✗ ${nome}\n      ${e.message}`);
  }
}
function confere(condicao, mensagem) { if (!condicao) throw new Error(mensagem); }

async function principal() {
  if (PRINTS) mkdirSync(PRINTS, { recursive: true });
  const senhas = JSON.parse(python("sistema/contas_demo.py", "--json"));
  if (PRINTS) python("testes-navegador/semear_demo.py");

  servidor = spawn(PYTHON, ["-m", "uvicorn", "suporte.main:app", "--factory", "--host", "127.0.0.1", "--port", String(PORTA_SITE)],
    { cwd: join(RAIZ, "servico"), env: ambiente, stdio: "ignore" });
  let no_ar = false;
  for (let i = 0; i < 60 && !no_ar; i++) { try { no_ar = (await fetch(`${BASE}/health`)).ok; } catch { await espera(250); } }
  if (!no_ar) throw new Error("O servidor de teste não subiu.");

  const exe = NAVEGADORES.find((c) => existsSync(c));
  if (!exe) throw new Error("Edge ou Chrome não encontrado. Informe o caminho em NAVEGADOR.");
  navegador = spawn(exe, ["--headless=new", `--remote-debugging-port=${PORTA_CDP}`, `--user-data-dir=${join(pasta, "perfil")}`,
    "--no-first-run", "--disable-gpu", "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "about:blank"],
    { stdio: "ignore" });

  const pessoa = await abrirAba();
  const tecnico = await abrirAba();
  console.log(`\nTestes no navegador (${exe.split(/[\\/]/).pop()})`);

  await cenario("Página inicial leva ao chat e ao painel", async () => {
    await pessoa.ir("/");
    confere(await pessoa.js(`!!document.querySelector('.escolha.colaborador[href="/chat"]') && !!document.querySelector('.escolha.tecnico[href="/tecnico"]')`),
      "os dois cartões de escolha não apareceram");
    await pessoa.print("inicio.png");
  });

  await cenario("Chat pede login e obriga a trocar a senha provisória", async () => {
    await pessoa.ir("/chat");
    confere(await pessoa.ate("!document.getElementById('acesso').hidden && document.getElementById('conversa').hidden"), "a tela de login não apareceu");
    await pessoa.print("login.png");
    await entrarPrimeiraVez(pessoa, "xxxxx1@teste.com", senhas["xxxxx1@teste.com"], "Chamado2026");
    confere(await pessoa.ate("!document.getElementById('conversa').hidden && document.querySelector('.msg.bot')"), "o chat não abriu depois do login");
    confere(await pessoa.ate("document.getElementById('mensagens').textContent.includes('Olá, XXXXX')"), "não cumprimentou pelo nome");
  });

  await cenario("Atende sem pedir e-mail e o colaborador marca os passos", async () => {
    await pessoa.js(`mandar("O Teams não abre e dá erro desde hoje cedo")`);
    confere(await pessoa.ate("document.querySelector('.os .passos')"), "a ordem de serviço com os passos não apareceu");
    confere(!(await pessoa.js(`document.getElementById("mensagens").textContent.includes("e-mail corporativo?")`)), "pediu e-mail mesmo com login");
    await pessoa.js(`(() => { const c = document.querySelectorAll(".passos input"); c[0].click(); c[1].click(); return true; })()`);
    confere(await pessoa.ate("document.querySelector('.progresso').textContent.startsWith('2 de')"), "a contagem de passos feitos não mudou");
    await espera(900);
    await pessoa.print("chat.png");
  });

  await cenario("Não resolveu: registra o chamado e aparece em Meus chamados", async () => {
    await pessoa.js(`mandar("Não resolveu", "Não resolveu")`);
    confere(await pessoa.ate("document.querySelector('.previsao .previsao-tempo')"), "a previsão de atendimento não apareceu");
    await pessoa.clicar("#meus-chamados");
    confere(await pessoa.ate("document.querySelectorAll('.meu-chamado').length === 1"), "Meus chamados não mostrou o chamado");
    await pessoa.print("meus-chamados.png");
    await pessoa.clicar("#fechar-meus");
  });

  await cenario("Técnico vê o chamado com o que o colaborador já tentou", async () => {
    await tecnico.ir("/tecnico", { largura: 1360, altura: 900 });
    await entrarPrimeiraVez(tecnico, "admin.xxxxx7@teste.com", senhas["admin.xxxxx7@teste.com"], "Suporte2026");
    confere(await tecnico.ate("!document.getElementById('tela-painel').hidden && document.querySelector('.cartao-tecnico')"), "o painel não abriu");
    await tecnico.js(`[...document.querySelectorAll(".cartao-tecnico")].pop().click(), true`);
    confere(await tecnico.ate(`[...document.querySelectorAll(".ficha")].some(f => f.textContent.includes("desde hoje cedo"))`), "o chamado da XXXXX não apareceu");
    const resumo = await tecnico.js(`(() => { const f = [...document.querySelectorAll(".ficha")].find(f => f.textContent.includes("desde hoje cedo"));
      f.querySelector(".historico summary").click(); f.scrollIntoView({ block: "start" }); window.scrollBy(0, -80); return f.querySelector(".resumo-historico").textContent; })()`);
    confere(/2 de \d+ passos feitos/.test(resumo), `o histórico não mostra os passos feitos (veio: "${resumo}")`);
    await tecnico.print("painel.png");
  });

  await cenario("Conversa entre técnico e colaborador, com a bolha digitando", async () => {
    await tecnico.js(`[...document.querySelectorAll(".ficha")].find(f => f.textContent.includes("desde hoje cedo")).querySelector(".botao-conversa").click(), true`);
    confere(await tecnico.ate("!document.getElementById('gaveta').hidden && !document.getElementById('gaveta-iniciar').hidden"), "a conversa não abriu");
    await tecnico.clicar("#iniciar-conversa");
    confere(await tecnico.ate("!document.getElementById('gaveta-form').hidden"), "não deu para iniciar a conversa");
    await tecnico.digitar("#gaveta-texto", "Olá, XXXXX! Sou o XXXXX. Vou olhar o seu Teams agora.");
    confere(await pessoa.ate("document.querySelector('.msg .digitando') && document.getElementById('mensagens').textContent.includes('XXXXX')", 8000),
      "a pessoa não viu a bolha \"digitando\" do técnico");
    await tecnico.js(`document.getElementById("gaveta-form").requestSubmit(), true`);
    confere(await pessoa.ate("document.getElementById('mensagens').textContent.includes('Vou olhar o seu Teams')", 8000), "a mensagem do técnico não chegou ao chat");
    await pessoa.digitar("#texto", "Obrigada! O erro aparece ao abrir.");
    confere(await tecnico.ate("document.querySelector('#gaveta-mensagens .digitando')", 8000), "o técnico não viu a bolha \"digitando\" da pessoa");
    await tecnico.print("conversa-tecnico.png");
    await pessoa.js(`mandar(document.getElementById("texto").value)`);
    confere(await tecnico.ate("document.getElementById('gaveta-mensagens').textContent.includes('O erro aparece ao abrir')", 8000), "a resposta da pessoa não chegou ao técnico");
    await pessoa.print("chat-com-tecnico.png");
    await tecnico.clicar("#encerrar-conversa");
    await tecnico.clicar("#fechar-gaveta");
  });

  await cenario("Administrador vê indicadores e cria uma conta", async () => {
    confere(await tecnico.ate("!document.getElementById('abas-painel').hidden"), "as abas de administrador não apareceram");
    await tecnico.clicar('[data-area="indicadores"]');
    confere(await tecnico.ate("document.querySelectorAll('.tile').length === 5 && document.querySelector('.svg-grafico')"), "os indicadores não carregaram");
    await tecnico.js("window.scrollTo(0, 0), true");
    await tecnico.print("indicadores.png", { inteira: true });
    await tecnico.clicar('[data-area="contas"]');
    confere(await tecnico.ate("document.querySelector('.form-conta')"), "a tela de contas não abriu");
    await tecnico.js(`document.querySelector('.segmentos [role="radio"]:nth-child(2)').click(), true`);
    await tecnico.ate("document.querySelector('.form-conta') && !document.querySelector('.form-conta .marcar-admin')");
    await tecnico.digitar('.form-conta input[name="nome"]', "XXXXX");
    await tecnico.digitar('.form-conta input[name="email"]', "xxxxx6@teste.com");
    await tecnico.js(`document.querySelector(".form-conta").requestSubmit(), true`);
    confere(await tecnico.ate("document.querySelector('.senha-gerada code')?.textContent.startsWith('Prov-')"), "a senha provisória da conta nova não apareceu");
    await tecnico.print("contas.png");
    await tecnico.clicar('[data-area="chamados"]');
  });

  await cenario("Configurações trocam tema e idioma na hora, sem perder a conversa", async () => {
    const antes = await pessoa.js(`document.querySelectorAll(".msg").length`);
    await pessoa.clicar("#usuario");
    confere(await pessoa.ate("document.querySelector('.modal-conta')"), "a janela de conta não abriu");
    await pessoa.js(`[...document.querySelectorAll(".abas-conta button")][1].click(), true`);
    await pessoa.clicar('input[name="config-tema"][value="escuro"]');
    confere(await pessoa.js(`document.documentElement.dataset.tema === "escuro"`), "o tema escuro não foi aplicado");
    await pessoa.print("configuracoes.png");
    await pessoa.clicar('input[name="config-idioma"][value="en"]');
    confere(await pessoa.ate(`document.title === "IT Support" && document.getElementById("meus-chamados").textContent.includes("My tickets")`), "o idioma não mudou");
    confere(await pessoa.js(`document.querySelectorAll(".msg").length`) === antes, "a conversa foi perdida ao trocar o idioma");
    await pessoa.clicar('input[name="config-idioma"][value="pt"]');
    await pessoa.clicar('input[name="config-tema"][value="auto"]');
    await pessoa.js(`document.querySelector(".modal-conta .fechar").click(), true`);
  });

  await cenario("Funciona no celular", async () => {
    await pessoa.ir("/chat", { largura: 390, altura: 844 });
    confere(await pessoa.ate("!document.getElementById('conversa').hidden"), "o chat não abriu no celular (a sessão deveria continuar)");
    const largura = await pessoa.js("document.documentElement.scrollWidth");
    confere(largura <= 390, `o chat fica mais largo que a tela (${largura}px)`);
    await pessoa.print("celular.png");
    for (const [aba, caminho, pronto] of [[tecnico, "/tecnico", "!document.getElementById('tela-painel').hidden"], [pessoa, "/", "true"]]) {
      await aba.ir(caminho, { largura: 390, altura: 844 });
      await aba.ate(pronto);
      const l = await aba.js("document.documentElement.scrollWidth");
      confere(l <= 390, `${caminho} fica mais largo que a tela (${l}px)`);
    }
  });

  await cenario("Nenhum erro de script ou recurso bloqueado na página", async () => {
    confere(errosNaPagina.length === 0, errosNaPagina.slice(0, 5).join(" | "));
  });

  const falhas = resultados.filter(([ok]) => !ok).length;
  console.log(`\n${resultados.length - falhas} de ${resultados.length} cenários passaram${PRINTS ? ` · imagens em ${PRINTS}` : ""}`);
  encerrar(falhas ? 1 : 0);
}

principal().catch((e) => { console.error(`\nErro ao preparar os testes: ${e.message}`); encerrar(1); });
