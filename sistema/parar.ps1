. (Join-Path $PSScriptRoot 'ambiente.ps1')

$donos = Get-NetTCPConnection -LocalPort $PortaServico -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
if (-not $donos) { Write-Host 'O serviço de suporte não estava ligado.' }
foreach ($id in $donos) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p) { Write-Host "Desligando o serviço de suporte ($($p.ProcessName))"; Stop-Process -Id $id -Force }
}
