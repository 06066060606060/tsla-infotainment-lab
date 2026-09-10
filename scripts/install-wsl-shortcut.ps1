param([string]$Distribution = 'Debian')
$ErrorActionPreference = 'Stop'
if ($Distribution -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Enter a WSL distribution name such as Debian.' }
$labRoot = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $labRoot 'Launch-Linux.sh'))) {
    $labRoot = Split-Path -Parent $PSScriptRoot
}
if (-not (Test-Path -LiteralPath (Join-Path $labRoot 'Launch-Linux.sh'))) { throw 'Launch-Linux.sh is missing beside this application.' }
$labWslg = Join-Path $env:ProgramFiles 'WSL\wslg.exe'
if (-not (Test-Path -LiteralPath $labWslg)) {
    $labWslg = (Get-Command wslg.exe -ErrorAction Stop).Source
}
$labShell = New-Object -ComObject WScript.Shell
$labFolders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($labFolder in $labFolders) {
    $labLinkPath = Join-Path $labFolder 'Infotainment Lab.lnk'
    $labLink = $labShell.CreateShortcut($labLinkPath)
    $labLink.TargetPath = $labWslg
    $labLink.Arguments = '-d ' + $Distribution + ' --cd "' + $labRoot + '" -- bash ./Launch-Linux.sh'
    $labLink.WorkingDirectory = $labRoot
    $labLink.WindowStyle = 7
    $labLink.Description = 'Open the native Linux Infotainment Lab in ' + $Distribution
    $labLink.Save()
    Write-Output $labLinkPath
}
