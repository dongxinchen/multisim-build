# Build the two x86 helpers next to their sources.
#
# C# 5 via the .NET Framework compiler that ships with Windows. /platform:x86 is
# mandatory: MSInterface.dll is 32-bit only, and the private clipboard formats
# Multisim writes cannot be read from a 64-bit process.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { throw "csc.exe not found at $csc (needs .NET Framework 4.x)" }

foreach ($name in @('mscom', 'clipdump')) {
    $src = Join-Path $here "$name.cs"
    $out = Join-Path $here "$name.exe"
    if (-not (Test-Path $src)) { throw "missing source: $src" }
    & $csc /nologo /platform:x86 /optimize+ /out:"$out" "$src"
    if (-not (Test-Path $out)) { throw "build produced no $name.exe" }
    Write-Output ("built " + (Get-Item $out).Length + " bytes -> $out")
}
