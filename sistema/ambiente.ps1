[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseDeclaredVarsMoreThanAssignments', '')]
param()

$Raiz         = Split-Path $PSScriptRoot -Parent
$Python       = Join-Path $Raiz '.venv\Scripts\python.exe'
$ArquivoEnv   = Join-Path $Raiz '.env'
$PortaServico = 5080
$env:PYTHONDONTWRITEBYTECODE = '1'

if (Test-Path $ArquivoEnv) {
    foreach ($linha in Get-Content $ArquivoEnv -Encoding UTF8) {
        if ($linha -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            Set-Item "env:$($Matches[1])" $Matches[2].Trim()
        }
    }
}
