$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ambiente.ps1')

if (-not (Test-Path $Python)) { throw 'Ambiente não configurado. Rode primeiro: .\sistema\configurar.ps1' }

$enderecoChat = "http://127.0.0.1:$PortaServico/"
if (Get-NetTCPConnection -LocalPort $PortaServico -State Listen -ErrorAction SilentlyContinue) {
    Write-Host 'O serviço de suporte já está ligado.' -ForegroundColor Green
} else {
    Write-Host 'Iniciando o serviço de suporte...'
    Start-Process powershell -WorkingDirectory (Join-Path $Raiz 'servico') -ArgumentList '-NoExit', '-Command',
        "`$Host.UI.RawUI.WindowTitle = 'Serviço Suporte (Python) - não feche'; & '$Python' -m uvicorn suporte.main:app --factory --host 127.0.0.1 --port $PortaServico"
    $limite = (Get-Date).AddSeconds(30)
    $ok = $false
    while (-not $ok -and (Get-Date) -lt $limite) {
        try { Invoke-WebRequest "$($enderecoChat)health" -UseBasicParsing -TimeoutSec 3 | Out-Null; $ok = $true }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ok) { throw 'O serviço não respondeu em 30 s. Veja o erro na janela "Serviço Suporte (Python)".' }
    Write-Host '  Serviço de suporte no ar.' -ForegroundColor Green
}

$saude = Invoke-RestMethod "$($enderecoChat)health"
if (-not $saude.planilha_existe) {
    Write-Host "ATENÇÃO: planilha não encontrada em $($saude.planilha). Ajuste PLANILHA_CHAMADOS no .env." -ForegroundColor Yellow
}

Write-Host "`nSuporte aberto no navegador: $enderecoChat" -ForegroundColor Cyan
Write-Host "  Colaborador: $($enderecoChat)chat"
Write-Host "  Técnico:     $($enderecoChat)tecnico"
Start-Process $enderecoChat
