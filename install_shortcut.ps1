# Cria um atalho "JARVIS" no Desktop apontando pra start.bat.
# Uso: clique direito neste arquivo > "Executar com PowerShell".
# Se o Windows reclamar de execution policy, rode antes:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root 'start.bat'

if (-not (Test-Path $target)) {
    Write-Host "ERRO: $target nao encontrado." -ForegroundColor Red
    exit 1
}

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop 'JARVIS.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath       = $target
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle      = 7   # 7 = minimizado
$shortcut.Description      = 'J.A.R.V.I.S. — assistente local'

# Tenta usar um icone bonito se existir; senao usa shell32
$ico = Join-Path $root 'frontend\jarvis.ico'
if (Test-Path $ico) {
    $shortcut.IconLocation = "$ico,0"
} else {
    # Icone do Windows (chip eletronico) como placeholder
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
}

$shortcut.Save()

Write-Host "Atalho criado em: $lnkPath" -ForegroundColor Green
Write-Host "Pode tambem fixar na barra de tarefas (clique direito > Fixar na barra)." -ForegroundColor Cyan
