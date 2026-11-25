# Install or update DockSight with Docker Compose on Windows.
#
#   irm https://github.com/Neizvestnyj/DockSight/releases/latest/download/install.ps1 | iex
#
# Settings (environment variables, for example $env:DOCKSIGHT_COMPONENTS = 'backend'):
#   DOCKSIGHT_DIR         Install directory. Default: %LOCALAPPDATA%\DockSight
#   DOCKSIGHT_PORT        Local web port. Default: 8080
#   DOCKSIGHT_COMPONENTS  all (default) or backend for the API only
#   DOCKSIGHT_API_PORT    Local API port in backend-only mode. Default: 8000
#   DOCKSIGHT_PROJECT     Docker Compose project name. Default: docksight
#
# Rerunning the installer of a newer release updates DockSight and keeps .env.
& {
    Set-StrictMode -Version 3.0
    $ErrorActionPreference = 'Stop'

    $ReleaseTag = '__DOCKSIGHT_RELEASE_TAG__'
    $ComposeSha256 = '__DOCKSIGHT_COMPOSE_SHA256__'
    $RepositoryUrl = 'https://github.com/Neizvestnyj/DockSight'
    $MinComposeVersion = [version]'2.24.0'
    $OverrideMarker = '# Managed by the DockSight installer.'
    $ReleaseFiles = @('compose.yaml', 'docksight.env.example', 'INSTALL.md')
    $Utf8 = New-Object System.Text.UTF8Encoding($false)

    function Write-Step([string]$Message) {
        Write-Host "docksight: $Message"
    }

    function Invoke-Docker([string[]]$Arguments, [switch]$Capture) {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            if ($Capture) {
                $output = & docker @Arguments 2>$null
                return [pscustomobject]@{ Output = ($output | Out-String).Trim(); ExitCode = $LASTEXITCODE }
            }
            & docker @Arguments | Out-Host
            return [pscustomobject]@{ Output = ''; ExitCode = $LASTEXITCODE }
        } finally {
            $ErrorActionPreference = $previous
        }
    }

    function Test-Port([string]$Name, [string]$Value) {
        $port = 0
        if (-not [int]::TryParse($Value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
            throw "$Name must be a port number between 1 and 65535."
        }
    }

    function Test-Docker {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw 'Docker is not installed. See https://docs.docker.com/get-started/get-docker/'
        }
        if ((Invoke-Docker @('info') -Capture).ExitCode -ne 0) {
            throw 'Docker is not running. Start Docker Desktop and try again.'
        }
        $result = Invoke-Docker @('compose', 'version', '--short') -Capture
        $match = [regex]::Match($result.Output, '\d+\.\d+\.\d+')
        if ($result.ExitCode -ne 0 -or -not $match.Success -or [version]$match.Value -lt $MinComposeVersion) {
            throw "Docker Compose $MinComposeVersion or later is required."
        }
    }

    function Get-ReleaseFile([string]$Base, [string]$Name, [string]$Destination) {
        if (Test-Path -LiteralPath $Base -PathType Container) {
            Copy-Item -LiteralPath (Join-Path $Base $Name) -Destination $Destination
            return
        }
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$Base/$Name" -OutFile $Destination
        } catch {
            throw "Cannot download $Base/$Name"
        }
    }

    function Get-Release([string]$Directory) {
        $base = if ($env:DOCKSIGHT_RELEASE_URL) { $env:DOCKSIGHT_RELEASE_URL } else {
            "$RepositoryUrl/releases/download/$ReleaseTag"
        }
        $staging = Join-Path ([IO.Path]::GetTempPath()) ("docksight-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $staging | Out-Null
        try {
            foreach ($name in $ReleaseFiles) {
                Get-ReleaseFile $base $name (Join-Path $staging $name)
            }
            if ($ComposeSha256.StartsWith('__')) {
                Write-Step 'Skipping the compose.yaml checksum for an unrendered installer.'
            } else {
                $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $staging 'compose.yaml')).Hash
                if ($actual.ToLowerInvariant() -ne $ComposeSha256) {
                    throw 'compose.yaml does not match the release checksum. Nothing was changed.'
                }
            }
            foreach ($name in $ReleaseFiles) {
                Copy-Item -LiteralPath (Join-Path $staging $name) -Destination (Join-Path $Directory $name) -Force
            }
        } finally {
            Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    function Read-EnvLines {
        return [IO.File]::ReadAllLines((Join-Path (Get-Location) '.env'), $Utf8)
    }

    function Write-EnvLines([string[]]$Lines) {
        $text = ($Lines -join "`n") + "`n"
        [IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), $text, $Utf8)
    }

    function Get-EnvValue([string]$Key) {
        $value = ''
        foreach ($line in Read-EnvLines) {
            if ($line.StartsWith("$Key=")) { $value = $line.Substring($Key.Length + 1) }
        }
        return $value
    }

    function Set-EnvValue([string]$Key, [string]$Value) {
        $lines = New-Object System.Collections.Generic.List[string]
        $done = $false
        foreach ($line in Read-EnvLines) {
            if ($line.StartsWith("$Key=")) {
                if (-not $done) { $lines.Add("$Key=$Value") }
                $done = $true
            } else {
                $lines.Add($line)
            }
        }
        if (-not $done) { $lines.Add("$Key=$Value") }
        Write-EnvLines $lines.ToArray()
    }

    function Get-SocketGroup {
        $compose = [IO.File]::ReadAllText((Join-Path (Get-Location) 'compose.yaml'), $Utf8)
        $match = [regex]::Match($compose, '(?m)^\s*image:\s*(\S*docksight-backend\S*)\s*$')
        if (-not $match.Success) { throw 'compose.yaml names no backend image.' }
        $result = Invoke-Docker @(
            'run', '--rm', '--volume', '/var/run/docker.sock:/var/run/docker.sock',
            '--entrypoint', 'stat', $match.Groups[1].Value, '-c', '%g', '/var/run/docker.sock'
        ) -Capture
        if ($result.ExitCode -ne 0 -or $result.Output -notmatch '^\d+$') {
            throw 'Cannot read the group of /var/run/docker.sock. DockSight needs the local Docker socket.'
        }
        return $result.Output
    }

    function New-EnvFile {
        $bytes = New-Object byte[] 32
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($bytes) } finally { $random.Dispose() }
        $token = -join ($bytes | ForEach-Object { $_.ToString('x2') })
        $port = if ($env:DOCKSIGHT_PORT) { $env:DOCKSIGHT_PORT } else { '8080' }
        $group = Get-SocketGroup
        $example = [IO.File]::ReadAllText((Join-Path (Get-Location) 'docksight.env.example'), $Utf8)
        Write-EnvLines ($example -replace "`r", '').TrimEnd("`n").Split("`n")
        Set-EnvValue 'DOCKSIGHT_API_TOKEN' $token
        Set-EnvValue 'DOCKSIGHT_DOCKER_GID' $group
        Set-EnvValue 'DOCKSIGHT_HTTP_PORT' $port
        Set-EnvValue 'DOCKSIGHT_BROWSER_ORIGIN' "http://127.0.0.1:$port"
        return $token
    }

    function Set-Overrides {
        if ($env:DOCKSIGHT_PORT) {
            Set-EnvValue 'DOCKSIGHT_HTTP_PORT' $env:DOCKSIGHT_PORT
            Set-EnvValue 'DOCKSIGHT_BROWSER_ORIGIN' "http://127.0.0.1:$($env:DOCKSIGHT_PORT)"
        }
        if ($env:DOCKSIGHT_API_PORT) { Set-EnvValue 'DOCKSIGHT_API_PORT' $env:DOCKSIGHT_API_PORT }
        if ($env:DOCKSIGHT_COMPONENTS) { Set-EnvValue 'DOCKSIGHT_COMPONENTS' $env:DOCKSIGHT_COMPONENTS }
        if ($env:DOCKSIGHT_PROJECT) { Set-EnvValue 'COMPOSE_PROJECT_NAME' $env:DOCKSIGHT_PROJECT }
    }

    function Start-DockSight([string]$Components) {
        $override = Join-Path (Get-Location) 'compose.override.yaml'
        if ($Components -eq 'backend') {
            $text = "$OverrideMarker Rerun it with DOCKSIGHT_COMPONENTS=all to remove this file.`n" +
                "services:`n  backend:`n    ports:`n      - `"127.0.0.1:`${DOCKSIGHT_API_PORT:-8000}:8000`"`n"
            [IO.File]::WriteAllText($override, $text, $Utf8)
            $started = Invoke-Docker @('compose', 'up', '--detach', '--wait', '--remove-orphans', 'backend')
            Invoke-Docker @('compose', 'rm', '--stop', '--force', 'web') -Capture | Out-Null
        } else {
            if ((Test-Path -LiteralPath $override) -and
                ([IO.File]::ReadAllText($override, $Utf8)).StartsWith($OverrideMarker)) {
                Remove-Item -LiteralPath $override
            }
            $started = Invoke-Docker @('compose', 'up', '--detach', '--wait', '--remove-orphans')
        }
        if ($started.ExitCode -ne 0) { throw 'DockSight did not start. See: docker compose logs' }
    }

    function Write-Report([string]$Directory, [string]$Components, [string]$Token) {
        $version = if ($ReleaseTag.StartsWith('__')) { 'development build' } else { $ReleaseTag }
        Write-Step "DockSight $version is running in $Directory."
        if ($Components -eq 'backend') {
            $apiPort = Get-EnvValue 'DOCKSIGHT_API_PORT'
            if (-not $apiPort) { $apiPort = '8000' }
            Write-Step "API: http://127.0.0.1:$apiPort/api/v1"
        } else {
            Write-Step "Open http://127.0.0.1:$(Get-EnvValue 'DOCKSIGHT_HTTP_PORT') and choose Connect API."
        }
        if ($Token) {
            Write-Step "API token: $Token"
            Write-Step "The token is also stored in $Directory\.env."
        } else {
            Write-Step "Your settings and API token in $Directory\.env are unchanged."
        }
        Write-Step "Diagnoses need a model. The default is Ollama on this computer. See $Directory\INSTALL.md."
        Write-Step "Update: rerun this installer. Stop: cd `"$Directory`"; docker compose down"
    }

    if ($env:DOCKSIGHT_PORT) { Test-Port 'DOCKSIGHT_PORT' $env:DOCKSIGHT_PORT }
    if ($env:DOCKSIGHT_API_PORT) { Test-Port 'DOCKSIGHT_API_PORT' $env:DOCKSIGHT_API_PORT }
    if ($env:DOCKSIGHT_COMPONENTS -and $env:DOCKSIGHT_COMPONENTS -notin @('all', 'backend')) {
        throw 'DOCKSIGHT_COMPONENTS must be all or backend.'
    }
    if ($ReleaseTag.StartsWith('__') -and -not $env:DOCKSIGHT_RELEASE_URL) {
        throw 'This is an installer template. Use install.ps1 from a release.'
    }
    Test-Docker
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor
        [Net.SecurityProtocolType]::Tls12

    $directory = if ($env:DOCKSIGHT_DIR) { $env:DOCKSIGHT_DIR } else { Join-Path $env:LOCALAPPDATA 'DockSight' }
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $directory = (Resolve-Path -LiteralPath $directory).Path
    Push-Location -LiteralPath $directory
    try {
        Get-Release $directory
        $token = ''
        if (-not (Test-Path -LiteralPath '.env')) { $token = New-EnvFile }
        Set-Overrides
        $components = Get-EnvValue 'DOCKSIGHT_COMPONENTS'
        if (-not $components) { $components = 'all' }
        if ($components -notin @('all', 'backend')) { throw 'DOCKSIGHT_COMPONENTS in .env must be all or backend.' }
        Start-DockSight $components
        Write-Report $directory $components $token
    } finally {
        Pop-Location
    }
}
