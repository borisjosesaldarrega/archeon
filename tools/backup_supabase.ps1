param(
    [string]$ProjectRef = "rcgipowzivogyqbuwzlv",
    [string]$DatabaseHost = "db.rcgipowzivogyqbuwzlv.supabase.co",
    [int]$DatabasePort = 5432,
    [string]$DatabaseUser = "postgres",
    [string]$DatabaseName = "postgres"
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$backupRoot = Join-Path $workspaceRoot "backups"
$timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$destination = Join-Path $backupRoot $timestamp
$temporaryPassword = $false
$passwordPointer = [IntPtr]::Zero

$postgresArchiveUrl = "https://sbp.enterprisedb.com/getfile.jsp?fileid=1260427"
$postgresArchiveName = "archeon-postgresql-17.11-windows-x64-binaries.zip"
$portableRoot = Join-Path $backupRoot ".tools"
$portableBin = Join-Path $portableRoot "pgsql\bin"

function Get-PostgresTools {
    $installed = Get-Command pg_dump.exe -ErrorAction SilentlyContinue
    if ($null -ne $installed) {
        return Split-Path -Parent $installed.Source
    }
    $portableDump = Join-Path $portableBin "pg_dump.exe"
    if (Test-Path -LiteralPath $portableDump) {
        return $portableBin
    }

    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $archivePath = Join-Path ([IO.Path]::GetTempPath()) $postgresArchiveName
    Write-Host "Downloading official PostgreSQL 17 portable tools (one-time setup)..."
    Invoke-WebRequest -UseBasicParsing -Uri $postgresArchiveUrl -OutFile $archivePath
    try {
        Expand-Archive -LiteralPath $archivePath -DestinationPath $portableRoot -Force
    }
    finally {
        $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        $resolvedArchive = [IO.Path]::GetFullPath($archivePath)
        if ($resolvedArchive.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and
            [IO.Path]::GetFileName($resolvedArchive) -eq $postgresArchiveName) {
            Remove-Item -LiteralPath $resolvedArchive -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path -LiteralPath $portableDump)) {
        throw "Official PostgreSQL archive did not contain pg_dump.exe"
    }
    return $portableBin
}

function Invoke-PgTool {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$OutputPath
    )
    $errorPath = "$OutputPath.stderr"
    & $Executable @Arguments 1> $OutputPath 2> $errorPath
    if ($LASTEXITCODE -ne 0) {
        $detail = (Get-Content -LiteralPath $errorPath -Raw -ErrorAction SilentlyContinue).Trim()
        throw "$(Split-Path -Leaf $Executable) failed: $detail"
    }
    Remove-Item -LiteralPath $errorPath -Force -ErrorAction SilentlyContinue
}

function Write-FilteredSql {
    param(
        [string]$InputPath,
        [string]$OutputPath,
        [scriptblock]$Filter
    )
    $result = foreach ($line in Get-Content -LiteralPath $InputPath) {
        & $Filter $line
    }
    $result | Set-Content -LiteralPath $OutputPath -Encoding UTF8
}

try {
    if ([string]::IsNullOrWhiteSpace($env:SUPABASE_DB_PASSWORD)) {
        $securePassword = Read-Host "Supabase database password" -AsSecureString
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        $env:SUPABASE_DB_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        $temporaryPassword = $true
    }
    if ([string]::IsNullOrWhiteSpace($env:SUPABASE_DB_PASSWORD)) {
        throw "Database password cannot be empty"
    }

    $postgresBin = Get-PostgresTools
    $pgDump = Join-Path $postgresBin "pg_dump.exe"
    $pgDumpAll = Join-Path $postgresBin "pg_dumpall.exe"
    if (-not (Test-Path -LiteralPath $pgDumpAll)) {
        throw "pg_dumpall.exe was not found beside pg_dump.exe"
    }

    $env:PGHOST = $DatabaseHost
    $env:PGPORT = [string]$DatabasePort
    $env:PGUSER = $DatabaseUser
    $env:PGPASSWORD = $env:SUPABASE_DB_PASSWORD
    $env:PGDATABASE = $DatabaseName
    $env:PGSSLMODE = "require"

    New-Item -ItemType Directory -Path $destination -Force | Out-Null

    $rolesRaw = Join-Path $destination "roles.raw.sql"
    $rolesPath = Join-Path $destination "roles.sql"
    Invoke-PgTool $pgDumpAll @(
        "--roles-only", "--role=postgres", "--quote-all-identifiers",
        "--no-role-passwords", "--no-comments"
    ) $rolesRaw
    Write-FilteredSql $rolesRaw $rolesPath {
        param($line)
        if ($line -match '^\\(un)?restrict ' -or $line -match '^--') { return }
        $reserved = 'anon|authenticated|authenticator|cli_login_.*|dashboard_user|pgbouncer|postgres|service_role|supabase_.*|pgsodium_keyholder|pgsodium_keyiduser|pgsodium_keymaker|pgtle_admin'
        if ($line -match "^(CREATE|ALTER) ROLE `"($reserved)`"") { return }
        if ($line -match "^GRANT `".*`" TO `"($reserved)`"") { return }
        $line = $line -replace ' (NOSUPERUSER|NOREPLICATION)', ''
        return $line
    }
    Add-Content -LiteralPath $rolesPath -Value "RESET ALL;" -Encoding UTF8
    Remove-Item -LiteralPath $rolesRaw -Force

    $schemaRaw = Join-Path $destination "schema.raw.sql"
    $schemaPath = Join-Path $destination "schema.sql"
    $excludedSchemas = 'information_schema|pg_*|_analytics|_realtime|_supavisor|auth|etl|extensions|pgbouncer|realtime|storage|supabase_functions|supabase_migrations|cron|dbdev|graphql|graphql_public|net|pgmq|pgsodium|pgsodium_masks|pgtle|repack|tiger|tiger_data|timescaledb_*|_timescaledb_*|topology|vault'
    Invoke-PgTool $pgDump @(
        "--schema-only", "--quote-all-identifiers", "--role=postgres",
        "--exclude-schema=$excludedSchemas"
    ) $schemaRaw
    Write-FilteredSql $schemaRaw $schemaPath {
        param($line)
        if ($line -match '^\\(un)?restrict ' -or $line -match '^--') { return }
        if ($line -match '^CREATE PUBLICATION "supabase_realtime' -or
            $line -match '^CREATE EVENT TRIGGER ' -or $line -match '^ALTER EVENT TRIGGER ' -or
            $line -match '^         WHEN TAG IN ' -or $line -match '^   EXECUTE FUNCTION ' -or
            $line -match '^ALTER PUBLICATION "supabase_realtime_' -or
            $line -match '^ALTER FOREIGN DATA WRAPPER .+ OWNER TO ' -or
            $line -match '^ALTER DEFAULT PRIVILEGES FOR ROLE "supabase_admin"' -or
            $line -match '^GRANT .+ ON .+ "(information_schema|pg_|auth|storage|extensions|vault)' -or
            $line -match '^REVOKE .+ ON .+ "(information_schema|pg_|auth|storage|extensions|vault)' -or
            $line -match '^COMMENT ON EXTENSION ' -or $line -match '^CREATE POLICY "cron_job_' -or
            $line -match '^ALTER TABLE "cron"' -or $line -eq 'SET transaction_timeout = 0;') { return }
        $line = $line -replace '^CREATE SCHEMA "', 'CREATE SCHEMA IF NOT EXISTS "'
        $line = $line -replace '^CREATE TABLE "', 'CREATE TABLE IF NOT EXISTS "'
        $line = $line -replace '^CREATE SEQUENCE "', 'CREATE SEQUENCE IF NOT EXISTS "'
        $line = $line -replace '^CREATE VIEW "', 'CREATE OR REPLACE VIEW "'
        $line = $line -replace '^CREATE FUNCTION "', 'CREATE OR REPLACE FUNCTION "'
        $line = $line -replace '^CREATE TRIGGER "', 'CREATE OR REPLACE TRIGGER "'
        $line = $line -replace '^(CREATE EXTENSION IF NOT EXISTS "(?:pg_tle|pgsodium|pgmq)").*', '$1;'
        return $line
    }
    Remove-Item -LiteralPath $schemaRaw -Force

    $dataRaw = Join-Path $destination "data.raw.sql"
    $dataPath = Join-Path $destination "data.sql"
    $dataExcludedSchemas = 'information_schema|pg_*|graphql|graphql_public|pgsodium|pgsodium_masks|pgtle|repack|tiger|tiger_data|timescaledb_*|_timescaledb_*|topology|vault|etl|extensions|pgbouncer|realtime|supabase_migrations|_analytics|_realtime|_supavisor'
    Invoke-PgTool $pgDump @(
        "--data-only", "--quote-all-identifiers", "--role=postgres",
        "--exclude-schema=$dataExcludedSchemas",
        "--exclude-table=auth.schema_migrations", "--exclude-table=storage.migrations",
        "--exclude-table=supabase_functions.migrations", "--schema=*",
        "--exclude-table=storage.buckets_vectors", "--exclude-table=storage.vector_indexes"
    ) $dataRaw
    @("SET session_replication_role = replica;", "") +
        (Get-Content -LiteralPath $dataRaw | Where-Object { $_ -notmatch '^\\(un)?restrict ' }) +
        @("", "RESET ALL;") |
        Set-Content -LiteralPath $dataPath -Encoding UTF8
    Remove-Item -LiteralPath $dataRaw -Force

    & python (Join-Path $PSScriptRoot "verify_supabase_backup.py") $destination
    if ($LASTEXITCODE -ne 0) { throw "backup verification failed" }
    Write-Output "Verified backup: $destination"
}
finally {
    foreach ($name in "PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE") {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    if ($temporaryPassword) {
        Remove-Item "Env:SUPABASE_DB_PASSWORD" -ErrorAction SilentlyContinue
    }
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
}
