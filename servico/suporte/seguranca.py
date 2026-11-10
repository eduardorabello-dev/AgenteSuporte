from fastapi import Request
from fastapi.responses import JSONResponse

ENDERECOS_LOCAIS = {"127.0.0.1", "::1", "localhost", "testclient"}
HOSTS_PERMITIDOS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
METODOS_QUE_ALTERAM = {"POST", "PUT", "PATCH", "DELETE"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
CABECALHOS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
INICIO_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _host_sem_porta(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def _origem_do_proprio_site(request: Request) -> bool:
    origem = request.headers.get("origin")
    if origem and origem != "null":
        host_origem = origem.split("://", 1)[-1]
        return _host_sem_porta(host_origem) in HOSTS_PERMITIDOS and host_origem == request.headers.get("host", "")
    if origem == "null":
        return False
    return request.headers.get("sec-fetch-site", "same-origin") in {"same-origin", "none"}


async def proteger(request: Request, chamar_proximo):
    cliente = request.client.host if request.client else ""
    if cliente not in ENDERECOS_LOCAIS:
        return JSONResponse({"detail": "O suporte só pode ser usado neste computador."}, status_code=403)
    if _host_sem_porta(request.headers.get("host", "")) not in HOSTS_PERMITIDOS:
        return JSONResponse({"detail": "Endereço não permitido."}, status_code=400)
    if request.method in METODOS_QUE_ALTERAM and not _origem_do_proprio_site(request):
        return JSONResponse({"detail": "Pedido de outro site recusado."}, status_code=403)

    resposta = await chamar_proximo(request)
    for nome, valor in CABECALHOS.items():
        resposta.headers.setdefault(nome, valor)
    if not request.url.path.startswith("/arquivos/"):
        resposta.headers["Cache-Control"] = "no-store"
    return resposta


def celula_segura(valor) -> str:
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto.startswith(INICIO_FORMULA) else texto


def celula_original(texto: str) -> str:
    if texto.startswith("'") and texto[1:].startswith(INICIO_FORMULA):
        return texto[1:]
    return texto


def linha_segura(linha: dict) -> dict:
    return {k: celula_segura(v) for k, v in linha.items()}


def linha_original(linha: dict) -> dict:
    return {k: celula_original(v) if isinstance(v, str) else v for k, v in linha.items()}
