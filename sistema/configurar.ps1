$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ambiente.ps1')
Set-Location $Raiz

function Passo([string]$Texto) { Write-Host "`n==> $Texto" -ForegroundColor Cyan }

function Executar([scriptblock]$Comando, [string]$Erro) {
    & $Comando
    if ($LASTEXITCODE -ne 0) { throw "$Erro (código $LASTEXITCODE)" }
}

Passo 'Ambiente Python'
if (-not (Test-Path $Python)) {
    Executar { py -3.12 -m venv .venv } 'Falha ao criar .venv. Instale o Python 3.12 (python.org) e tente de novo.'
}
Executar { & $Python -m pip install -q --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt') } 'Falha ao instalar dependências Python'
Write-Host '  ok'

Passo 'Arquivo .env'
if (-not (Test-Path $ArquivoEnv)) {
    [IO.File]::WriteAllText($ArquivoEnv, @"
DIRETORIO_MODO=mock
"@, (New-Object Text.UTF8Encoding($false)))
    Write-Host '  criado'
} else {
    Write-Host '  já existe (mantido)'
}

Passo 'Contas de demonstração (login do chat e do painel)'
Executar { & $Python (Join-Path $PSScriptRoot 'contas_demo.py') } 'Falha ao criar as contas de demonstração'

Write-Host "`nPronto! Agora dê dois cliques em 'Abrir Suporte.cmd' (ou rode .\sistema\iniciar.ps1)." -ForegroundColor Green
