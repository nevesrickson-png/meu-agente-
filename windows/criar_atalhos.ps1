# Cria/atualiza os atalhos do Quiron na Area de Trabalho. Chamado pelo "Abrir Quiron.bat" a cada abertura
# (sempre da versao nova do programa, entao atalhos novos aparecem logo apos a atualizacao).
param([string]$Pasta = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$icones = Join-Path $env:SystemRoot 'System32\imageres.dll'
$atalhos = @(
  @{ Nome = 'Quiron';                 Alvo = 'Abrir Quiron.bat';         Icone = 76 },
  @{ Nome = 'Quiron - Offline';       Alvo = 'Quiron Offline.bat';       Icone = 54 }
)
# Telas que antes tinham atalho proprio e agora sao abas do Quiron (Terminal, Acervo, Configuracoes)
foreach ($velho in @('Quiron - Configuracoes', 'Quiron - Acervo', 'Quiron - Terminal', 'Quiron - Google Agenda')) {
  $lnk = Join-Path $desktop ($velho + '.lnk')
  if (Test-Path $lnk) { Remove-Item $lnk -Force -ErrorAction SilentlyContinue }
}
$criados = 0
foreach ($a in $atalhos) {
  $alvo = Join-Path $Pasta $a.Alvo
  if (-not (Test-Path $alvo)) { continue }
  try {
    $s = $shell.CreateShortcut((Join-Path $desktop ($a.Nome + '.lnk')))
    $s.TargetPath = $alvo
    $s.WorkingDirectory = $Pasta
    $s.IconLocation = "$icones,$($a.Icone)"
    $s.Save()
    $criados++
  } catch {
    Write-Host "  Nao consegui criar o atalho '$($a.Nome)': $($_.Exception.Message)"
  }
}
Write-Host "  Atalhos na Area de Trabalho: $criados (Quiron e Quiron - Offline). Terminal, Acervo e Configuracoes sao abas do Quiron."
