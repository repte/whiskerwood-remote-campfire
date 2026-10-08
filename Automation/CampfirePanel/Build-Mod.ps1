param(
    [string]$EngineRoot = 'D:\WWEngine',
    [string]$ProjectRoot = '',
    [switch]$UseGeneratedAssets
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $ProjectRoot) {
    $ProjectRoot = Join-Path (Split-Path $repository -Parent) 'Modkit'
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$editor = Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'
$uat = Join-Path $EngineRoot 'Engine\Build\BatchFiles\RunUAT.bat'
$unrealPak = Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealPak.exe'
$python = Join-Path $EngineRoot 'Engine\Binaries\ThirdParty\Python3\Win64\python.exe'
$project = Join-Path $ProjectRoot 'Whiskerwood.uproject'
$metadataPath = Join-Path $ProjectRoot 'Saved\CampfirePanel-PackageSetup.json'
$repositoryContent = Join-Path $repository 'Content\Mods\CampfirePanel'
$descriptor = Join-Path $repositoryContent 'CampfirePanel.uplugin'
$sourceDescriptor = Join-Path $ProjectRoot 'Content\Mods\CampfirePanel\CampfirePanel.uplugin'
$expected = @('BP_MapLoad', 'WBP_CampfirePanel', 'WBP_CampfireRow')
foreach ($required in @($editor, $uat, $unrealPak, $python, $project, $descriptor,
        (Join-Path $PSScriptRoot 'generator.py'), (Join-Path $PSScriptRoot 'prepare_package.py'),
        (Join-Path $PSScriptRoot 'test_precision.py'), (Join-Path $PSScriptRoot 'test_ui.py'),
        (Join-Path $PSScriptRoot 'test_public.py'),
        (Join-Path $PSScriptRoot 'test_performance.py'),
        (Join-Path $PSScriptRoot 'test_catalog.py'), (Join-Path $PSScriptRoot 'test_localization.py'),
        (Join-Path $PSScriptRoot 'translations.json'),
        (Join-Path $ProjectRoot 'Plugins\CampfireProbeEditor\CampfireProbeEditor.uplugin'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file missing: $required" }
}
$mod = Get-Content -LiteralPath $descriptor -Raw | ConvertFrom-Json
if ($mod.Name -cne 'CampfirePanel' -or $mod.Version -cne '0.1.2' -or $mod.EngineVersion -cne '5.8') {
    throw 'Unexpected CampfirePanel descriptor identity, version, or engine'
}
if (@(Get-Process -Name '*Whiskerwood*', '*UnrealEditor*' -ErrorAction SilentlyContinue).Count) {
    throw 'Close Whiskerwood and the editor before building.'
}
$targetContent = Split-Path $sourceDescriptor -Parent
if (-not $UseGeneratedAssets -and [IO.Path]::GetFullPath($repositoryContent) -ne [IO.Path]::GetFullPath($targetContent)) {
    [void](New-Item -ItemType Directory -Path $targetContent -Force)
    foreach ($name in @('BP_MapLoad.uasset', 'WBP_CampfirePanel.uasset', 'WBP_CampfireRow.uasset', 'PAL_CampfirePanel.uasset', 'CampfirePanel.uplugin')) {
        Copy-Item -LiteralPath (Join-Path $repositoryContent $name) -Destination (Join-Path $targetContent $name)
    }
}

$id = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$output = Join-Path $ProjectRoot "Saved\RemoteCampfireBuilds\$id"
$logs = Join-Path $output 'Logs'
[void](New-Item -ItemType Directory -Path $logs -Force)
$errorPattern = '(?im)\b(?:Error|Fatal):|\bBUILD FAILED\b|Traceback \(most recent call last\):|Assertion failed:|Fatal error:|AutomationTool exiting with ExitCode=[1-9]'

function Invoke-CampfireEditorScript {
    param([string]$Script, [string]$Marker)
    $log = Join-Path $logs "$Script.log"
    $console = Join-Path $logs "$Script-console.log"
    & $editor $project ("-ExecutePythonScript=" + (Join-Path $PSScriptRoot $Script)) `
        -unattended -nullrhi -nosound -culture=en ("-abslog=$log") -stdout -FullStdOutLogOutput *> $console
    if ($LASTEXITCODE -ne 0) { throw "CampfirePanel editor step failed: $console" }
    if (-not (Test-Path -LiteralPath $log -PathType Leaf)) { throw "Editor log missing: $log" }
    $text = (Get-Content -LiteralPath $log -Raw) + "`n" + (Get-Content -LiteralPath $console -Raw)
    if ($text -match $errorPattern -or $text -notmatch ([regex]::Escape($Marker))) {
        throw "CampfirePanel editor step not verified: $log"
    }
}

& $python (Join-Path $PSScriptRoot 'test_catalog.py') -v *> (Join-Path $logs 'test_catalog.log')
if ($LASTEXITCODE -ne 0) { throw 'CampfirePanel translation catalog checks failed' }
if (-not $UseGeneratedAssets) {
    Invoke-CampfireEditorScript -Script 'generator.py' -Marker 'CAMPFIRE_GENERATED_PASS'
}
Invoke-CampfireEditorScript -Script 'test_localization.py' -Marker 'CAMPFIRE_LOCALIZATION_TESTS_PASS'
Invoke-CampfireEditorScript -Script 'test_precision.py' -Marker 'CAMPFIRE_PRECISION_TESTS_PASS'
Invoke-CampfireEditorScript -Script 'test_ui.py' -Marker 'CAMPFIRE_UI_TESTS_PASS'
Invoke-CampfireEditorScript -Script 'test_public.py' -Marker 'CAMPFIRE_PUBLIC_TESTS_PASS'
Invoke-CampfireEditorScript -Script 'test_performance.py' -Marker 'CAMPFIRE_PERFORMANCE_TESTS_PASS'
if (-not (Test-Path -LiteralPath $sourceDescriptor -PathType Leaf) -or
        (Get-FileHash -LiteralPath $descriptor -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $sourceDescriptor -Algorithm SHA256).Hash) {
    throw 'Generated CampfirePanel source descriptor does not match the release descriptor'
}
$setupStarted = [DateTime]::UtcNow
Invoke-CampfireEditorScript -Script 'prepare_package.py' -Marker 'CAMPFIRE_PACKAGE_SETUP_PASS'
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf) -or
        (Get-Item -LiteralPath $metadataPath).LastWriteTimeUtc -lt $setupStarted) {
    throw "Fresh CampfirePanel package metadata missing: $metadataPath"
}
$setup = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
$chunk = 0
if ($setup.mod -cne 'CampfirePanel' -or $setup.version -cne $mod.Version -or
        -not [int]::TryParse([string]$setup.chunk, [ref]$chunk) -or $chunk -lt 1 -or $chunk -gt 300 -or
        @($setup.runtime_assets).Count -ne $expected.Count -or
        @(Compare-Object -ReferenceObject $expected -DifferenceObject @($setup.runtime_assets) -CaseSensitive).Count) {
    throw 'Invalid CampfirePanel chunk metadata'
}
Copy-Item -LiteralPath $metadataPath -Destination (Join-Path $output 'CampfirePanel-PackageSetup.json')

$cookLog = Join-Path $logs 'BuildCookRun.log'
& $uat BuildCookRun ("-project=$project") -platform=Win64 -clientconfig=Shipping `
    -build -cook -stage -pak -archive ("-archivedirectory=$output") `
    -nocompileeditor -installed -nop4 -utf8output -unattended -WaitForUATMutex *> $cookLog
if ($LASTEXITCODE -ne 0) { throw "CampfirePanel cook/package failed: $cookLog" }
$cookText = Get-Content -LiteralPath $cookLog -Raw
if ($cookText -notmatch 'BUILD SUCCESSFUL' -or $cookText -match $errorPattern) {
    throw "CampfirePanel cook/package not verified: $cookLog"
}
$pak = Join-Path $output "Windows\Whiskerwood\Content\Paks\pakchunk$chunk-Windows.pak"
if (-not (Test-Path -LiteralPath $pak -PathType Leaf)) { throw "CampfirePanel chunk pak missing: $pak" }
$csv = Join-Path $logs 'CampfirePanel-Pak.csv'
$listLog = Join-Path $logs 'CampfirePanel-Pak-list.log'
$integrityLog = Join-Path $logs 'CampfirePanel-Pak-integrity.log'
& $unrealPak $pak -List -ExtractToMountPoint ("-CSV=$csv") -unattended *> $listLog
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $csv -PathType Leaf) -or
        (Get-Content -LiteralPath $listLog -Raw) -match $errorPattern) {
    throw "CampfirePanel pak listing failed: $listLog"
}
$lines = @(Get-Content -LiteralPath $csv)
if ($lines.Count -lt 2 -or ($lines[0] -replace '\s', '') -cne 'Filename,Offset,Size,Hash,Deleted,Compressed,CompressionMethod') {
    throw "Empty or unsupported UnrealPak inventory: $csv"
}
$entries = @($lines | Select-Object -Skip 1 | ConvertFrom-Csv -Header Filename,Offset,Size,Hash,Deleted,Compressed,CompressionMethod)
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$assets = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($entry in $entries) {
    $path = [string]$entry.Filename
    if ($path -cnotmatch '^\.\./\.\./\.\./Whiskerwood/Content/Mods/CampfirePanel/([A-Za-z0-9_]+)\.(uasset|uexp|ubulk|uptnl)$') {
        throw "File outside the CampfirePanel runtime boundary: $path"
    }
    $name, $extension = $Matches[1], $Matches[2]
    if ($name -cnotin $expected) { throw "Unexpected CampfirePanel asset: $path" }
    if (-not $seen.Add($path)) { throw "Duplicate CampfirePanel entry: $path" }
    $size = 0L
    if (-not [long]::TryParse(([string]$entry.Size).Trim(), [ref]$size) -or $size -le 0 -or
            ([string]$entry.Deleted).Trim() -cne 'false') {
        throw "Invalid CampfirePanel pak entry: $path"
    }
    if ($extension -ceq 'uasset') { [void]$assets.Add($name) }
}
foreach ($name in $expected) {
    if (-not $assets.Contains($name)) { throw "Missing cooked CampfirePanel asset: $name" }
}
& $unrealPak $pak -Verify -unattended *> $integrityLog
if ($LASTEXITCODE -ne 0) { throw "CampfirePanel pak integrity failed: $integrityLog" }
$integrity = Get-Content -LiteralPath $integrityLog -Raw
if ($integrity -notmatch 'Pak file .* healthy' -or $integrity -match $errorPattern) {
    throw "CampfirePanel pak integrity not confirmed: $integrityLog"
}
$verification = [pscustomobject]@{
    Result = 'CAMPFIRE_PACKAGE_CHECKS_PASS'
    Pak = $pak
    Version = $mod.Version
    Chunk = $chunk
    Assets = $expected
    Entries = $entries.Count
    Bytes = (Get-Item -LiteralPath $pak).Length
    SHA256 = (Get-FileHash -LiteralPath $pak -Algorithm SHA256).Hash
    Inventory = $csv
    ListLog = $listLog
    IntegrityLog = $integrityLog
    RuntimeValidated = $false
}
$delivery = Join-Path $output 'Delivery\CampfirePanel'
[void](New-Item -ItemType Directory -Path $delivery)
$deliveryPak = Join-Path $delivery 'CampfirePanel.pak'
$deliveryDescriptor = Join-Path $delivery 'CampfirePanel.uplugin'
Copy-Item -LiteralPath $pak -Destination $deliveryPak
Copy-Item -LiteralPath $descriptor -Destination $deliveryDescriptor
if ((Get-FileHash -LiteralPath $deliveryPak -Algorithm SHA256).Hash -cne $verification.SHA256 -or
        (Get-FileHash -LiteralPath $deliveryDescriptor -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $descriptor -Algorithm SHA256).Hash) {
    throw 'CampfirePanel delivery copy hash mismatch'
}
$verification | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'package-verification.json') -Encoding utf8
if ([IO.Path]::GetFullPath($repositoryContent) -ne [IO.Path]::GetFullPath($targetContent)) {
    foreach ($name in @('BP_MapLoad.uasset', 'WBP_CampfirePanel.uasset', 'WBP_CampfireRow.uasset', 'PAL_CampfirePanel.uasset')) {
        Copy-Item -LiteralPath (Join-Path $targetContent $name) -Destination (Join-Path $repositoryContent $name)
    }
}
Write-Output "CAMPFIRE_BUILD_PASS: $delivery"
Write-Output 'Public package checks passed; nothing was installed or published.'
