# Probe the clipboard for Electronics Workbench XML.
#
# Route A check: with Multisim open, select a few components, press Ctrl+C, then run
#   powershell -STA -ExecutionPolicy Bypass -File clipboard_probe.ps1
# If the clipboard carries plain <?xml or "ElectronicsWorkbench", that route works and
# generated XML can be pasted straight into the schematic.
#
# -STA is required: the clipboard needs a single-threaded apartment.
param(
    [string]$DumpDir = "$PSScriptRoot\..\..\..\..\.work\clipboard"
)

Add-Type -AssemblyName System.Windows.Forms

if (-not [System.Threading.Thread]::CurrentThread.GetApartmentState().Equals('STA')) {
    Write-Error "run with: powershell -STA -File clipboard_probe.ps1"
    exit 2
}

$data = [System.Windows.Forms.Clipboard]::GetDataObject()
if ($null -eq $data) {
    Write-Output "clipboard is empty"
    exit 1
}

$formats = $data.GetFormats()
Write-Output ("clipboard formats ({0}): {1}" -f $formats.Count, ($formats -join ' | '))

$newDir = New-Item -ItemType Directory -Force -Path $DumpDir
$hit = $false
foreach ($f in $formats) {
    $obj = $data.GetData($f, $true)
    $text = $null
    if ($obj -is [string]) { $text = $obj }
    elseif ($obj -is [System.IO.MemoryStream]) {
        try { $text = [Text.Encoding]::UTF8.GetString($obj.ToArray()) } catch { $text = $null }
    }
    if (-not $text) { continue }

    $safe = ($f -replace '[^\w\.-]', '_')
    $path = Join-Path $newDir ("clipboard_{0}.txt" -f $safe)
    Set-Content -LiteralPath $path -Value $text -Encoding utf8

    if ($text -match 'MSMCompressedElectronicsWorkbenchXML|ElectronicsWorkbench|<\?xml') {
        $hit = $true
        Write-Output ("HIT format={0} bytes={1} file={2}" -f $f, $text.Length, $path)
        $preview = $text.Substring(0, [Math]::Min(200, $text.Length))
        Write-Output ("  head: " + ($preview -replace "`r?`n", ' '))
    }
}

if ($hit) {
    Write-Output "RESULT route A viable: clipboard holds EWB/XML text, dumped to $newDir"
    exit 0
}
Write-Output "RESULT no XML in clipboard. Route A unsupported here; dump kept at $newDir for inspection (look for a binary format with a 36-byte MSMCompressed... header)."
exit 1
