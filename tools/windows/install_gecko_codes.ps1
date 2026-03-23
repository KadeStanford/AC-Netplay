param(
    [string]$RepoRoot,
    [string]$DolphinUserPath,
    [string]$GameId = "GAFE01",
    [string]$CodeFilePath
)

$ErrorActionPreference = "Stop"

function Resolve-DolphinUserPath([string]$OverridePath) {
    if ($OverridePath) {
        return $OverridePath
    }

    $candidates = @(
        (Join-Path $env:USERPROFILE "Documents\Dolphin Emulator"),
        (Join-Path $env:USERPROFILE "OneDrive\Documents\Dolphin Emulator")
    )

    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $candidates[0]
}

function Read-GeckoBlocks([string]$Path) {
    if (-not (Test-Path $Path)) {
        throw "Gecko code source file not found: $Path"
    }

    $rawLines = Get-Content -Path $Path
    $names = New-Object System.Collections.Generic.List[string]
    $geckoLines = New-Object System.Collections.Generic.List[string]

    $inBlock = $false

    foreach ($line in $rawLines) {
        $trim = $line.Trim()
        if ($trim -eq "") {
            continue
        }

        if ($trim.StartsWith("#")) {
            continue
        }

        if ($trim.StartsWith("$")) {
            $names.Add($trim)
            $geckoLines.Add($trim)
            $inBlock = $true
            continue
        }

        if ($inBlock -and ($trim -match "^[0-9A-Fa-f]{8}\s+[0-9A-Fa-f]{8}$")) {
            $geckoLines.Add($trim.ToUpper())
            continue
        }
    }

    if ($names.Count -eq 0) {
        throw "No Gecko code blocks were found in: $Path"
    }

    return @{
        Names = $names
        GeckoLines = $geckoLines
    }
}

function Parse-IniFile([string]$Path) {
    $data = @{
        Preamble = New-Object System.Collections.Generic.List[string]
        Sections = @{}
        SectionOrder = New-Object System.Collections.Generic.List[string]
    }

    if (-not (Test-Path $Path)) {
        return $data
    }

    $lines = Get-Content -Path $Path
    $currentSection = $null

    foreach ($line in $lines) {
        if ($line -match "^\[(.+)\]$") {
            $currentSection = $Matches[1]
            if (-not $data.Sections.ContainsKey($currentSection)) {
                $data.Sections[$currentSection] = New-Object System.Collections.Generic.List[string]
                $data.SectionOrder.Add($currentSection)
            }
            continue
        }

        if ($null -eq $currentSection) {
            $data.Preamble.Add($line)
        }
        else {
            $data.Sections[$currentSection].Add($line)
        }
    }

    return $data
}

function Ensure-Section($iniData, [string]$SectionName) {
    if (-not $iniData.Sections.ContainsKey($SectionName)) {
        $iniData.Sections[$SectionName] = New-Object System.Collections.Generic.List[string]
        $iniData.SectionOrder.Add($SectionName)
    }
}

function Remove-GeckoCodeBlocks($sectionLines, $codeNames) {
    $out = New-Object System.Collections.Generic.List[string]
    $skipCurrentBlock = $false

    foreach ($line in $sectionLines) {
        $trim = $line.Trim()

        if ($trim.StartsWith("$")) {
            if ($codeNames -contains $trim) {
                $skipCurrentBlock = $true
                continue
            }

            $skipCurrentBlock = $false
            $out.Add($line)
            continue
        }

        if ($skipCurrentBlock) {
            if ($trim -match "^[0-9A-Fa-f]{8}\s+[0-9A-Fa-f]{8}$") {
                continue
            }

            # Keep skipping non-code lines until the next code name starts.
            continue
        }

        $out.Add($line)
    }

    return $out
}

function Remove-EnabledCodeNames($sectionLines, $codeNames) {
    $out = New-Object System.Collections.Generic.List[string]

    foreach ($line in $sectionLines) {
        $trim = $line.Trim()
        if ($codeNames -contains $trim) {
            continue
        }
        $out.Add($line)
    }

    return $out
}

function Write-IniFile([string]$Path, $iniData) {
    $outLines = New-Object System.Collections.Generic.List[string]

    foreach ($line in $iniData.Preamble) {
        $outLines.Add($line)
    }

    if ($outLines.Count -gt 0 -and $outLines[$outLines.Count - 1] -ne "") {
        $outLines.Add("")
    }

    for ($i = 0; $i -lt $iniData.SectionOrder.Count; $i++) {
        $section = $iniData.SectionOrder[$i]
        $outLines.Add("[$section]")

        foreach ($line in $iniData.Sections[$section]) {
            $outLines.Add($line)
        }

        if ($i -lt $iniData.SectionOrder.Count - 1) {
            $outLines.Add("")
        }
    }

    $content = [string]::Join("`r`n", $outLines) + "`r`n"
    Set-Content -Path $Path -Value $content -Encoding ascii
}

if (-not $RepoRoot) {
    $RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
}

if (-not $CodeFilePath) {
    $CodeFilePath = Join-Path $RepoRoot "gecko_codes\ac_netplay.txt"
}

$resolvedDolphinPath = Resolve-DolphinUserPath -OverridePath $DolphinUserPath
$gameSettingsDir = Join-Path $resolvedDolphinPath "GameSettings"
$iniPath = Join-Path $gameSettingsDir ("$GameId.ini")

if (-not (Test-Path $gameSettingsDir)) {
    New-Item -ItemType Directory -Path $gameSettingsDir -Force | Out-Null
}

$codeData = Read-GeckoBlocks -Path $CodeFilePath
$codeNames = $codeData.Names
$newGeckoLines = $codeData.GeckoLines

$iniData = Parse-IniFile -Path $iniPath
Ensure-Section -iniData $iniData -SectionName "Gecko"
Ensure-Section -iniData $iniData -SectionName "Gecko_Enabled"

$existingGecko = Remove-GeckoCodeBlocks -sectionLines $iniData.Sections["Gecko"] -codeNames $codeNames
$existingEnabled = Remove-EnabledCodeNames -sectionLines $iniData.Sections["Gecko_Enabled"] -codeNames $codeNames

if ($existingGecko.Count -gt 0 -and $existingGecko[$existingGecko.Count - 1].Trim() -ne "") {
    $existingGecko.Add("")
}
foreach ($line in $newGeckoLines) {
    $existingGecko.Add($line)
}

if ($existingEnabled.Count -gt 0 -and $existingEnabled[$existingEnabled.Count - 1].Trim() -ne "") {
    $existingEnabled.Add("")
}
foreach ($name in $codeNames) {
    $existingEnabled.Add($name)
}

$iniData.Sections["Gecko"] = $existingGecko
$iniData.Sections["Gecko_Enabled"] = $existingEnabled

Write-IniFile -Path $iniPath -iniData $iniData
Write-Host "Installed AC-Netplay Gecko codes into $iniPath" -ForegroundColor Green
