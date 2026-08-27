# QC Bake for Maya - release builder
#
# Produces dist/qc_bake_maya.zip, laid out so that unzipping it anywhere and
# dragging install/install.py into a Maya viewport is the whole installation.
#
#     powershell -ExecutionPolicy Bypass -File tools/build_release.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$package = Join-Path $repoRoot "qc_bake_maya"
$initFile = Join-Path $package "__init__.py"
$distDir = Join-Path $repoRoot "dist"

if (-not (Test-Path -LiteralPath $initFile)) {
    throw "Missing qc_bake_maya/__init__.py in $repoRoot"
}

# The version lives in exactly one place - the package - so the archive name
# can never disagree with what the panel reports.
$versionLine = Select-String -LiteralPath $initFile -Pattern '^VERSION\s*=\s*\((.+)\)'
if (-not $versionLine) {
    throw "Could not read VERSION from $initFile"
}
$version = ($versionLine.Matches[0].Groups[1].Value -replace '\s', '') -replace ',', '.'
Write-Host "QC Bake for Maya $version"

$zipPath = Join-Path $distDir "qc_bake_maya-$version.zip"

if (Test-Path -LiteralPath $distDir) {
    Remove-Item -LiteralPath $distDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

$stagingRoot = Join-Path $distDir "_stage"
$stagingTool = Join-Path $stagingRoot "qc_bake_maya"
New-Item -ItemType Directory -Force -Path $stagingTool | Out-Null

Copy-Item -LiteralPath $package -Destination (Join-Path $stagingTool "qc_bake_maya") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "install") -Destination (Join-Path $stagingTool "install") -Recurse -Force

foreach ($doc in @("README.md", "CHANGELOG.md", "LICENSE")) {
    $source = Join-Path $repoRoot $doc
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $stagingTool -Force
    }
}

Get-ChildItem -LiteralPath $stagingTool -Directory -Recurse -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath $stagingTool -File -Recurse |
    Where-Object {
        $_.Extension -in @(".pyc", ".pyo") -or
        $_.Name -in @(".DS_Store", "Thumbs.db")
    } |
    Remove-Item -Force

Compress-Archive -LiteralPath $stagingTool -DestinationPath $zipPath -Force
Remove-Item -LiteralPath $stagingRoot -Recurse -Force

Write-Host "Built $zipPath"

# ---------------------------------------------------------------------------
# Kept releases
# ---------------------------------------------------------------------------
# dist/ is wiped on every build, so a copy goes to "Zip Addon" as well - the
# same place the Blender edition keeps its releases. This folder is never
# cleared: previous versions stay, which is what makes it possible to hand
# someone the exact build they were running.
$keepDir = Join-Path $repoRoot "Zip Addon"
if (-not (Test-Path -LiteralPath $keepDir)) {
    New-Item -ItemType Directory -Force -Path $keepDir | Out-Null
}
$keptZip = Join-Path $keepDir "qc_bake_maya-$version.zip"
Copy-Item -LiteralPath $zipPath -Destination $keptZip -Force
Write-Host "Kept   $keptZip"

# ---------------------------------------------------------------------------
# Publishing payload
# ---------------------------------------------------------------------------
# Maya has no add-on repository, so the tool checks a manifest we publish.
# It is generated here rather than written by hand for one reason: a manifest
# whose version disagrees with the archive beside it advertises an update that
# installs nothing and is then offered forever. Both come from the same build.
$pagesDir = Join-Path $repoRoot "pages"
if (Test-Path -LiteralPath $pagesDir) {
    Remove-Item -LiteralPath $pagesDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $pagesDir | Out-Null

$publishedZip = Join-Path $pagesDir "qc_bake_maya.zip"
Copy-Item -LiteralPath $zipPath -Destination $publishedZip -Force

$digest = (Get-FileHash -LiteralPath $publishedZip -Algorithm SHA256).Hash.ToLower()

$notes = ""
$changelog = Join-Path $repoRoot "CHANGELOG.md"
if (Test-Path -LiteralPath $changelog) {
    # One sentence describing the newest release, taken from the first
    # paragraph under its heading. Markdown wraps lines, so the continuation
    # lines have to be gathered too - reading only the first physical line
    # produces a sentence that stops mid-clause, which is what the panel would
    # then show the artist.
    $seenHeading = $false
    $collected = @()
    foreach ($line in Get-Content -LiteralPath $changelog) {
        if ($line -match '^##\s') {
            if ($seenHeading) { break }
            $seenHeading = $true
            continue
        }
        if (-not $seenHeading) { continue }
        $trimmed = $line.Trim()
        if ($trimmed -eq "") {
            if ($collected.Count -gt 0) { break }
            continue
        }
        $collected += ($trimmed -replace '^\s*[-*]\s+', '')
    }
    if ($collected.Count -gt 0) {
        $notes = ($collected -join ' ') -replace '\*\*', '' -replace '`', ''
        $notes = ($notes -replace '\s+', ' ').Trim()
        # Take whole sentences until there is something worth reading. A
        # single sentence is not enough on its own: an entry that opens with a
        # bold lead-in ("**Updates.** Maya has no...") would otherwise publish
        # the word "Updates." as its entire release note.
        $sentences = [regex]::Matches($notes, '.+?([.!?](\s|$)|$)')
        $built = ""
        foreach ($sentence in $sentences) {
            $candidate = ($built + " " + $sentence.Value).Trim()
            if ($built.Length -ge 40 -and $candidate.Length -gt 160) { break }
            $built = $candidate
            if ($built.Length -ge 90) { break }
        }
        $notes = $built.Trim()
        if ($notes.Length -gt 160) {
            $notes = $notes.Substring(0, 157).TrimEnd() + "..."
        }
    }
}

$baseUrl = $env:QCBAKE_PAGES_URL
if (-not $baseUrl) { $baseUrl = "https://mutaform.github.io/qc-bake-maya" }

$manifest = [ordered]@{
    id       = "qc_bake_maya"
    name     = "QC Bake"
    version  = $version
    download = "$baseUrl/qc_bake_maya.zip"
    sha256   = $digest
    notes    = $notes
    maya     = @("2025")
}
$manifestPath = Join-Path $pagesDir "version.json"
# Written without a byte-order mark, deliberately. PowerShell's -Encoding UTF8
# prepends one, and Python's json.loads refuses a BOM outright - so a manifest
# written the obvious way is rejected by the very updater it is meant to feed.
$manifestJson = $manifest | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText(
    $manifestPath, $manifestJson, (New-Object System.Text.UTF8Encoding($false)))

@"
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>QC Bake for Maya</title></head>
  <body>
    <h1>QC Bake for Maya</h1>
    <p>Version $version</p>
    <p><a href="version.json">Update manifest</a></p>
    <p><a href="qc_bake_maya.zip">Download ZIP</a></p>
    <p>Install: unzip, then drag <code>install/install.py</code> into a Maya viewport.</p>
  </body>
</html>
"@ | Set-Content -Path (Join-Path $pagesDir "index.html") -Encoding UTF8

Write-Host "Publishing payload in $pagesDir"
Write-Host "  version.json -> $version  sha256 $digest"
