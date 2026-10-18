param([string]$Distribution = 'Debian', [Parameter(ValueFromRemainingArguments=$true)][string[]]$AppArguments)
$ErrorActionPreference = 'Stop'
$linuxRoot = & wsl.exe -d $Distribution -- wslpath -a -u $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Install WSL2 and Debian before launching the app.' }
& wsl.exe -d $Distribution -- bash ($linuxRoot.Trim() + '/Launch-Linux.sh') @AppArguments
if ($LASTEXITCODE -ne 0) { throw 'Linux GUI startup failed. Check the output above and the README prerequisites.' }
