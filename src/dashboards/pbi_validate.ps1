# Validate the built PBIP project by OPENING IT IN POWER BI DESKTOP and interrogating the
# live Analysis Services engine Desktop loads it into.
#
# THE PRINCIPLE, CARRIED OVER FROM THE EXCEL BUILD
# ------------------------------------------------
# A build log saying "written" is not evidence. The Excel workbook shipped 20 invalid #QNAN
# literals that every build log called a success; only reading the saved FILE caught it.
# So nothing here trusts the generator: Desktop opens the project, loads the model, and every
# assertion below is answered by the engine - DMV queries for structure, DAX queries for
# values, reconciled against the committed evidence CSVs.
#
# AND VALIDATION IS NOT THE SAME AS LOOKING AT IT. A rendered visual QA pass found six
# defects every check here had passed - an empty plot, cards summing incompatible units,
# prose clipped to three words, an alphabetical date axis. Check E8 catches the first of
# those; the rest are why the rendered pages still get looked at.
#
# MUST RUN UNDER WINDOWS POWERSHELL 5.1. PowerShell 7 is .NET Core and the WindowsApps ACL
# refuses to load Power BI's assemblies into it ("Access is denied").

[CmdletBinding()]
param(
    [string] $ProjectRoot = 'C:\Projects\Nigeria Business Cost Intelligence\powerbi',
    [string] $Name = 'NBCI_Cost_Dashboard',
    [int]    $LoadWaitSeconds = 200,
    [switch] $SkipLaunch
)

$ErrorActionPreference = 'Stop'
$script:Pass = 0
$script:Fail = 0

function Check([string]$name, [bool]$ok, [string]$evidence = '') {
    if ($ok) { $script:Pass++; $tag = 'PASS' } else { $script:Fail++; $tag = 'FAIL' }
    Write-Host ("[{0}] {1}{2}" -f $tag, $name, $(if ($evidence) { "  -- $evidence" } else { '' }))
}

function CheckEq([string]$name, $actual, $expected, [double]$tol = 0) {
    if ($actual -is [string] -or $expected -is [string]) {
        $ok = ("$actual" -eq "$expected")
    } else {
        $ok = ([math]::Abs([double]$actual - [double]$expected) -le $tol)
    }
    Check $name $ok "actual=$actual expected=$expected"
}

# ---------------------------------------------------------------------------
# 0. Resolve Power BI and load its client library
# ---------------------------------------------------------------------------
$pkg = Get-AppxPackage -Name 'Microsoft.MicrosoftPowerBIDesktop' -ErrorAction SilentlyContinue |
       Sort-Object Version -Descending | Select-Object -First 1
if (-not $pkg) { throw 'Power BI Desktop is not installed.' }
$bin = Join-Path $pkg.InstallLocation 'bin'
Write-Host "Power BI Desktop $($pkg.Version)"
Write-Host "bin: $bin"
Write-Host ''

[void][System.Reflection.Assembly]::LoadFrom((Join-Path $bin 'Microsoft.PowerBI.AdomdClient.dll'))

# ---------------------------------------------------------------------------
# 1. Launch Desktop with the project and wait for the model to load
# ---------------------------------------------------------------------------
$pbip = Join-Path $ProjectRoot "$Name.pbip"
if (-not (Test-Path $pbip)) { throw "Project not found: $pbip" }

if (-not $SkipLaunch) {
    # COLD START. Delete the local data cache so every run genuinely re-reads the CSVs
    # through Power Query. Validating against a warm cache would prove only that
    # yesterday's data is still in memory, not that the model still builds.
    foreach ($abf in (Get-ChildItem $ProjectRoot -Recurse -Filter 'cache.abf' -Force -ErrorAction SilentlyContinue)) {
        try { [System.IO.File]::Delete($abf.FullName); Write-Host "Cold start: deleted $($abf.Name)" } catch { }
    }
    Get-Process PBIDesktop -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }
    for ($i = 0; $i -lt 20; $i++) {
        if (-not (Get-Process PBIDesktop -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Seconds 1
    }
    Get-Process PBIDesktop -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4

    $exe = "$env:LOCALAPPDATA\Microsoft\WindowsApps\PBIDesktopStore.exe"
    if (-not (Test-Path $exe)) { $exe = Join-Path $bin 'PBIDesktop.exe' }
    Write-Host 'Launching Desktop with the project ...'
    Start-Process -FilePath $exe -ArgumentList "`"$pbip`""
}

$conn = $null
$catalog = $null
$deadline = (Get-Date).AddSeconds($LoadWaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $msmd = Get-CimInstance Win32_Process -Filter "Name='msmdsrv.exe'" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if (-not $msmd) { continue }
    if ($msmd.CommandLine -notmatch '-s\s+"([^"]+)"') { continue }
    $portFile = Join-Path $Matches[1] 'msmdsrv.port.txt'
    if (-not (Test-Path $portFile)) { continue }
    $port = (Get-Content $portFile -Raw -Encoding Unicode) -replace '[^\d]', ''
    if (-not $port) { continue }
    try {
        $probe = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
        $probe.Open()
        $cmd = $probe.CreateCommand()
        $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
        $rdr = $cmd.ExecuteReader()
        $cats = @()
        while ($rdr.Read()) { $cats += $rdr.GetValue(0) }
        $rdr.Close(); $probe.Close()
        if ($cats.Count -eq 0) { continue }
        $catalog = $cats[0]
        $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Catalog=$catalog")
        $conn.Open()
        $c2 = $conn.CreateCommand()
        $c2.CommandText = "SELECT [Name] FROM `$SYSTEM.TMSCHEMA_TABLES"
        $r2 = $c2.ExecuteReader(); $tc = 0
        while ($r2.Read()) { $tc++ }
        $r2.Close()
        if ($tc -gt 1) { Write-Host "Model loaded: $tc tables in catalog $catalog"; break }
        $conn.Close(); $conn = $null
    } catch { if ($conn) { try { $conn.Close() } catch { } }; $conn = $null }
}

if (-not $conn) {
    # Desktop reports load failures in a WebView dialog whose text UI Automation cannot
    # read, so capture the window as an image - the only reliable way to see WHICH problem
    # it found.
    try {
        Add-Type -AssemblyName System.Drawing
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public struct SRECT { public int Left, Top, Right, Bottom; }
public class ShotW {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out SRECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
        $pp = Get-Process PBIDesktop -ErrorAction SilentlyContinue |
              Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
        if ($pp) {
            [void][ShotW]::ShowWindow($pp.MainWindowHandle, 3)
            [void][ShotW]::SetForegroundWindow($pp.MainWindowHandle)
            Start-Sleep -Milliseconds 1200
            $rc = New-Object SRECT
            [void][ShotW]::GetWindowRect($pp.MainWindowHandle, [ref]$rc)
            $bmp = New-Object System.Drawing.Bitmap(($rc.Right - $rc.Left), ($rc.Bottom - $rc.Top))
            $gfx = [System.Drawing.Graphics]::FromImage($bmp)
            $gfx.CopyFromScreen($rc.Left, $rc.Top, 0, 0, $bmp.Size)
            $shot = Join-Path $env:TEMP 'pbi_load_failure.png'
            $bmp.Save($shot, [System.Drawing.Imaging.ImageFormat]::Png)
            $gfx.Dispose(); $bmp.Dispose()
            Write-Host "Screenshot of the failure: $shot"
        }
    } catch { Write-Host "screenshot failed: $($_.Exception.Message)" }
    throw 'Validation aborted: no loaded model.'
}

function Scalar([string]$dax) {
    $c = $conn.CreateCommand(); $c.CommandText = $dax
    $r = $c.ExecuteReader()
    $v = $null
    if ($r.Read()) { $v = $r.GetValue(0) }
    $r.Close()
    return $v
}

function Rows([string]$q) {
    $c = $conn.CreateCommand(); $c.CommandText = $q
    $r = $c.ExecuteReader()
    $out = New-Object System.Collections.ArrayList
    while ($r.Read()) {
        $h = @{}
        for ($i = 0; $i -lt $r.FieldCount; $i++) { $h[$r.GetName($i)] = $r.GetValue($i) }
        [void]$out.Add([pscustomobject]$h)
    }
    $r.Close()
    return $out
}

# A freshly opened PBIP has no data cache, so every partition starts in state 3 "no data".
# The refresh is a TMSL script over the existing ADOMD connection - no UI automation.
# THIS ONLY WORKS BECAUSE THE MODEL IS V3: before
# `defaultPowerBIDataSourceVersion = PowerBI_V3` was set, Desktop owned the workspace model
# in a legacy metadata mode and refused every external write with "Value cannot be null.
# Parameter name: key", while its own refresh said "A data model with version 3 of metadata
# is required". With V3 set, the identical call completes in about ten seconds.
$partState = Rows "SELECT [Name],[State] FROM `$SYSTEM.TMSCHEMA_PARTITIONS"
if (($partState | Where-Object { $_.State -ne 1 }).Count -gt 0) {
    Write-Host ''
    Write-Host 'Partitions hold no data yet - running a full TMSL refresh ...'
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $rc2 = $conn.CreateCommand()
        $rc2.CommandTimeout = 900
        $rc2.CommandText = ('{"refresh":{"type":"full","objects":[{"database":"' + $catalog + '"}]}}')
        [void]$rc2.ExecuteNonQuery()
        Write-Host ("Refresh completed in {0:N1}s" -f $sw.Elapsed.TotalSeconds)
    } catch {
        Write-Host "REFRESH FAILED: $($_.Exception.Message)"
        if ($_.Exception.InnerException) { Write-Host "  INNER: $($_.Exception.InnerException.Message)" }
    }
    $conn.Close(); $conn.Open()
}

Write-Host ''
Write-Host '=== A. MODEL STRUCTURE (DMV) ==============================================='

# The compat level must be one the ENGINE supports, not merely one TOM will accept.
# 1610 passes the TOM setter and is then refused by Desktop with
# "Unsupported db compat level detected" - SupportedCompatibilityLevels goes ...1609, 1700.
$compatRow = Rows "SELECT [CATALOG_NAME], [COMPATIBILITY_LEVEL] FROM `$SYSTEM.DBSCHEMA_CATALOGS"
CheckEq 'A0 model compatibility level = 1606 (what this engine itself writes)' `
        $compatRow[0].COMPATIBILITY_LEVEL 1606

$tables = Rows "SELECT [Name] FROM `$SYSTEM.TMSCHEMA_TABLES"
$tableNames = $tables | ForEach-Object { $_.Name }
CheckEq 'A1 table count' ($tableNames | Where-Object { $_ -notlike 'LocalDateTable*' -and $_ -notlike 'DateTableTemplate*' }).Count 37
foreach ($t in @('fact_cost','dim_jurisdiction','dim_metric','dim_date',
                 'ref_finding','ref_finding_section','ref_scope','ref_capability',
                 'ref_archetype','ref_archetype_section',
                 'ref_page_narrative','ref_methodology','ref_rule')) {
    Check "A2 table present: $t" ($tableNames -contains $t)
}

$rels = Rows "SELECT * FROM `$SYSTEM.TMSCHEMA_RELATIONSHIPS"
CheckEq 'A3 relationship count' $rels.Count 24
$badRel = $rels | Where-Object { $_.State -ne 1 }
Check 'A4 every relationship is in a valid state' ($badRel.Count -eq 0) "invalid=$($badRel.Count)"

$measures = Rows "SELECT [Name],[TableID],[ErrorMessage] FROM `$SYSTEM.TMSCHEMA_MEASURES"
CheckEq 'A5 measure count' $measures.Count 47
$brokenM = $measures | Where-Object { $_.ErrorMessage -and "$($_.ErrorMessage)".Trim() -ne '' }
Check 'A6 no measure has an error message' ($brokenM.Count -eq 0) `
      ($(if ($brokenM) { ($brokenM | ForEach-Object { "$($_.Name): $($_.ErrorMessage)" }) -join ' | ' } else { 'all clean' }))

$cols = Rows "SELECT [ExplicitName],[TableID],[ErrorMessage] FROM `$SYSTEM.TMSCHEMA_COLUMNS"
$brokenC = $cols | Where-Object { $_.ErrorMessage -and "$($_.ErrorMessage)".Trim() -ne '' }
Check 'A7 no column has an error message' ($brokenC.Count -eq 0) "broken=$($brokenC.Count)"

$parts = Rows "SELECT [Name],[State],[ErrorMessage] FROM `$SYSTEM.TMSCHEMA_PARTITIONS"
$unloaded = $parts | Where-Object { $_.State -ne 1 }
Check 'A8 every partition is loaded' ($unloaded.Count -eq 0) `
      ($(if ($unloaded) { ($unloaded | ForEach-Object { "$($_.Name) state=$($_.State)" }) -join ' | ' } else { "$($parts.Count) partitions loaded" }))

Write-Host ''
Write-Host '=== B. THE RULES ARE ENFORCED IN THE MODEL ================================='

$tblById = @{}
foreach ($t in (Rows "SELECT [ID],[Name] FROM `$SYSTEM.TMSCHEMA_TABLES")) { $tblById[[string]$t.ID] = $t.Name }
$relPairs = @()
foreach ($r in $rels) { $relPairs += ("{0}->{1}" -f $tblById[[string]$r.FromTableID], $tblById[[string]$r.ToTableID]) }

Check 'B1 G3 - ref_food_zone has NO relationship to dim_jurisdiction' `
      (-not ($relPairs -contains 'ref_food_zone->dim_jurisdiction'))
Check 'B2 G4 - ref_nerc_band has NO relationship to dim_jurisdiction' `
      (-not ($relPairs -contains 'ref_nerc_band->dim_jurisdiction'))
Check 'B2b ref_scope stands alone - the framing is not sliceable data' `
      (($relPairs | Where-Object { $_ -like 'ref_scope->*' }).Count -eq 0)

$unstable = Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Dearest Jurisdiction], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE" ) )'
Check 'B3 G9 - diesel (unstable) refuses to name a jurisdiction' `
      ("$unstable" -like 'Not named*') "returned='$unstable'"

$stable = Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Dearest Jurisdiction], dim_metric[metric_code] = "TRANSPORT_WATER_NGN_PER_JOURNEY", dim_date[date] = DATE(2026,4,1) ) )'
Check 'B4 G9 - water (stable) DOES name a jurisdiction' `
      ("$stable" -eq 'Rivers') "returned='$stable' expected='Rivers' (d8)"

$yoyGap = Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Value YoY %], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE", dim_date[date] = DATE(2025,3,1) ) )'
Check 'B5 G11 - YoY is BLANK where no 12-month-prior row exists' ($null -eq $yoyGap) "returned='$yoyGap'"

Write-Host ''
Write-Host '=== C. DAX RECONCILES TO COMMITTED EVIDENCE ================================'

CheckEq 'C1 jurisdictions = 37' (Scalar 'EVALUATE ROW ( "v", [Jurisdiction Count] )') 37
CheckEq 'C2 costs tracked = 13'  (Scalar 'EVALUATE ROW ( "v", [Metric Count] )') 13
CheckEq 'C3 panel rows = 8177'   (Scalar 'EVALUATE ROW ( "v", [Observation Count] )') 8177
CheckEq 'C4 validation checks = 110' (Scalar 'EVALUATE ROW ( "v", [Validation Checks Passed] )') 110
CheckEq 'C5 raw files verified = 342' (Scalar 'EVALUATE ROW ( "v", [Raw Files Verified] )') 342

CheckEq 'C6 K01 diesel trough-to-latest = +158.16% (f31)' `
    (Scalar 'EVALUATE ROW ( "v", [Diesel Trough to Latest %] )') 158.1588 0.0001
CheckEq 'C7 K02 petrol trough-to-latest = +65.35% (f31)' `
    (Scalar 'EVALUATE ROW ( "v", [Petrol Trough to Latest %] )') 65.3465 0.01
CheckEq 'C8 K28 diesel EXTREME level = 52.04% (d1)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [EXTREME Level %], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE" ) )') 52.04 0.01
CheckEq 'C9 K10 diesel spread = NGN 638.66 (d8)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Spread NGN (evidence)], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE" ) )') 638.66 0.01
CheckEq 'C10 K11 petrol spread = NGN 195.16 (d8)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Spread NGN (evidence)], dim_metric[metric_code] = "PETROL_PRICE_NGN_PER_LITRE" ) )') 195.16 0.01
CheckEq 'C11 K18 water dearest/cheapest = 6.91x (d8)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Dearest over Cheapest (evidence)], dim_metric[metric_code] = "TRANSPORT_WATER_NGN_PER_JOURNEY" ) )') 6.91 0.01
CheckEq 'C12 K21 petrol dearest/cheapest = 1.14x (d8)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Dearest over Cheapest (evidence)], dim_metric[metric_code] = "PETROL_PRICE_NGN_PER_LITRE" ) )') 1.14 0.01
CheckEq 'C13 K17 okada rose while petrol fell = 100.0% (f29)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Share Fare Rose %], dim_metric[metric_code] = "TRANSPORT_OKADA_NGN_PER_JOURNEY" ) )') 100.0 0.01

CheckEq 'C14 computed diesel spread at 2026-04 matches d8' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Spread NGN], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE", dim_date[date] = DATE(2026,4,1) ) )') 638.66 0.02
CheckEq 'C15 computed water ratio at 2026-04 matches d8' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Dearest over Cheapest], dim_metric[metric_code] = "TRANSPORT_WATER_NGN_PER_JOURNEY", dim_date[date] = DATE(2026,4,1) ) )') 6.91 0.01
CheckEq 'C16 diesel median 2025-02 = 1450.00 (f01)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Median Value], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE", dim_date[date] = DATE(2025,2,1) ) )') 1450.0 0.01
CheckEq 'C17 diesel median 2025-09 trough = 1266.33 (f01)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Median Value], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE", dim_date[date] = DATE(2025,9,1) ) )') 1266.33 0.01
CheckEq 'C18 diesel median 2026-04 = 2472.04 (f01)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Median Value], dim_metric[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE", dim_date[date] = DATE(2026,4,1) ) )') 2472.04 0.01
CheckEq 'C19 self-gen multiple 2026-05 at 3.0 kWh/l = 5.17x (d3)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( [Self-gen Multiple of Reference], ref_selfgen[observation_month] = DATE(2026,5,1), ref_selfgen[genset_kwh_per_litre] = 3.0 ) )') 5.17 0.01
CheckEq 'C20 NERC Band A reference = NGN 209.50 (f25)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( SUM ( ref_nerc_band[median_tariff] ), ref_nerc_band[service_band] = "A" ) )') 209.50 0.001
CheckEq 'C21 NERC Band A spread = 0 across 11 DisCos (f25)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( SUM ( ref_nerc_band[spread] ), ref_nerc_band[service_band] = "A" ) )') 0 0.0001
CheckEq 'C22 self-gen break-even diesel Band A = NGN 628.50 (d4)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( SUM ( ref_breakeven[breakeven_diesel_ngn_per_litre_at_3kwh] ), ref_breakeven[service_band] = "A" ) )') 628.50 0.01
CheckEq 'C23 food zone premium South East = +12.49% (f22)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( SUM ( ref_food_zone[mean_premium_pct_vs_national] ), ref_food_zone[zone_name] = "South East" ) )') 12.49 0.01
CheckEq 'C24 air variance eta-squared = 0.8264 (v2a, G7)' `
    (Scalar 'EVALUATE ROW ( "v", CALCULATE ( SUM ( ref_mode_variance[eta_sq_month] ), ref_mode_variance[mode] = "AIR" ) )') 0.8264 0.0001
CheckEq 'C25 rank-stable metrics = exactly 4 (f40)' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( dim_metric, dim_metric[rank_stable] = TRUE ) ) )') 4

# --- metric-pinned headline cards -------------------------------------------
# Each replaced a card that had been silently aggregating one evidence column across all
# nine costs. Pinning them means each carries a single unit, so each must equal its
# evidence file exactly.
CheckEq 'C26 water dearest/cheapest card = 6.91x (d8)' `
    (Scalar 'EVALUATE ROW ( "v", [Water Location Ratio] )') 6.91 0.001
CheckEq 'C27 petrol dearest/cheapest card = 1.14x (d8)' `
    (Scalar 'EVALUATE ROW ( "v", [Petrol Location Ratio] )') 1.14 0.001
CheckEq 'C28 water spread card = NGN 5,796.57 (d8)' `
    (Scalar 'EVALUATE ROW ( "v", [Water Spread NGN] )') 5796.57 0.01
CheckEq 'C29 diesel ELEVATED card = 26.03% (d1)' `
    (Scalar 'EVALUATE ROW ( "v", [Diesel ELEVATED Level %] )') 26.0267 0.001
CheckEq 'C30 diesel EXTREME card = 52.04% (d1)' `
    (Scalar 'EVALUATE ROW ( "v", [Diesel EXTREME Level %] )') 52.0384 0.001
CheckEq 'C31 peak jurisdictions flagged = 26, one metric-month (d2)' `
    (Scalar 'EVALUATE ROW ( "v", [Peak Jurisdictions Flagged EXTREME] )') 26
CheckEq 'C32 self-gen card = 5.17x at 2026-05, 3.0 kWh/l (d3)' `
    (Scalar 'EVALUATE ROW ( "v", [Self-gen Multiple Latest] )') 5.17 0.001

# G9 must work in BOTH directions on the same page: water names a jurisdiction, petrol
# refuses to. A rule that only ever says "no" proves nothing.
$waterName = Scalar 'EVALUATE ROW ( "v", [Dearest Water Jurisdiction] )'
Check 'C33 G9 - water card NAMES Rivers' ("$waterName" -eq 'Rivers') "returned='$waterName'"
$petrolName = Scalar 'EVALUATE ROW ( "v", [Dearest Petrol Jurisdiction] )'
Check 'C34 G9 - petrol card REFUSES to name one' ("$petrolName" -like 'Not named*') "returned='$petrolName'"

CheckEq 'C35 rules carry a numeric sort key (G1..G15, not G1, G10, G11)' `
    (Scalar 'EVALUATE ROW ( "v", MAX ( ref_rule[rule_no] ) )') 15

Write-Host ''
Write-Host '=== D. THE EXPLANATION LAYER ==============================================='

CheckEq 'D1 page narrative rows = 7' (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_page_narrative ) )') 7
CheckEq 'D2 archetypes = 6'          (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_archetype ) )') 6
CheckEq 'D3 headline findings = 6'   (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_finding ) )') 6
CheckEq 'D4 rules carried = 15'      (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_rule ) )') 15
CheckEq 'D5 finding sections = 30 (6 findings x 5 parts)' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_finding_section ) )') 30
CheckEq 'D6 archetype sections = 36 (6 archetypes x 6 parts)' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_archetype_section ) )') 36
CheckEq 'D7 scope framing carries all 4 parts of the equation' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_scope ) )') 4

# A finding missing "why it matters" or its boundary is exactly the analyst-dashboard
# failure this redesign exists to fix.
$emptyFind = Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( ref_finding, LEN ( ref_finding[question] ) = 0 || LEN ( ref_finding[headline] ) = 0 || LEN ( ref_finding[found] ) = 0 || LEN ( ref_finding[matters] ) = 0 || LEN ( ref_finding[who] ) = 0 || LEN ( ref_finding[review] ) = 0 || LEN ( ref_finding[evidence] ) = 0 || LEN ( ref_finding[boundary] ) = 0 ) ) )'
Check 'D8 every finding has all six parts plus its evidence' `
      ($null -eq $emptyFind -or [int]$emptyFind -eq 0) "empty=$emptyFind"

$emptyArch = Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( ref_archetype, LEN ( ref_archetype[costs] ) = 0 || LEN ( ref_archetype[signals] ) = 0 || LEN ( ref_archetype[why] ) = 0 || LEN ( ref_archetype[review] ) = 0 || LEN ( ref_archetype[needed] ) = 0 || LEN ( ref_archetype[boundary] ) = 0 ) ) )'
Check 'D9 every archetype has all six parts' `
      ($null -eq $emptyArch -or [int]$emptyArch -eq 0) "empty=$emptyArch"

$emptyNarr = Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( ref_page_narrative, LEN ( ref_page_narrative[signal] ) = 0 || LEN ( ref_page_narrative[meaning] ) = 0 || LEN ( ref_page_narrative[review] ) = 0 || LEN ( ref_page_narrative[boundary] ) = 0 ) ) )'
Check 'D10 every page has all four narrative parts' `
      ($null -eq $emptyNarr -or [int]$emptyNarr -eq 0) "empty=$emptyNarr"

# THE FRAMING CHECK. The whole redesign turns on NBCI not being mistaken for a measure of
# business quality, so the model must actually carry that statement.
CheckEq 'D11 three of the four parts of the equation are OUTSIDE NBCI' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( ref_scope, ref_scope[in_nbci] = "NOT measured here" ) ) )') 3
CheckEq 'D12 exactly one part is the NBCI slice, and only PARTLY covered' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( ref_scope, SEARCH ( "PARTLY measured", ref_scope[in_nbci], 1, 0 ) > 0 ) ) )') 1

# THE CAPABILITY BOUNDARY. What is measured and what may be CONCLUDED from it are
# different questions. Both halves must be present, and the CANNOT half must never
# shrink quietly - that is how a cost tool turns into a claimed profitability tool.
CheckEq 'D14 capability boundary rows carried' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( ref_capability ) )') 13
CheckEq 'D15 seven things this project CAN do today' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( ref_capability, ref_capability[direction] = "CAN do today" ) ) )') 7
CheckEq 'D16 six things it CANNOT do today, stated as plainly' `
    (Scalar 'EVALUATE ROW ( "v", COUNTROWS ( FILTER ( ref_capability, ref_capability[direction] = "CANNOT do today" ) ) )') 6
foreach ($must in @('profitable', 'lose money', 'margin')) {
    $hit = Scalar ("EVALUATE ROW ( `"v`", COUNTROWS ( FILTER ( ref_capability, " +
                     "ref_capability[direction] = `"CANNOT do today`" && " +
                     "SEARCH ( `"$must`", ref_capability[capability], 1, 0 ) > 0 ) ) )")
    Check "D17 the CANNOT half explicitly refuses '$must'" ([int]$hit -ge 1) "rows=$hit"
}

# LANGUAGE GUARD. Nothing in the explanation layer may instruct a business to act, or
# equate a lower measured cost with a better place to do business.
$banned = @('you should raise', 'raise your prices', 'increase your prices',
            'you should relocate', 'relocate to', 'expand here', 'leave this state',
            'reduce salaries', 'choose this location', 'best state', 'best place',
            'cheapest state', 'cheaper place to do business', 'we recommend that you')
$langHits = @()
foreach ($tbl in @('ref_finding', 'ref_archetype', 'ref_page_narrative', 'ref_scope',
                   'ref_capability')) {
    foreach ($row in (Rows "EVALUATE $tbl")) {
        foreach ($prop in $row.PSObject.Properties) {
            $val = [string]$prop.Value
            if (-not $val) { continue }
            $low = $val.ToLower()
            foreach ($b in $banned) { if ($low.Contains($b)) { $langHits += "$tbl :: '$b'" } }
        }
    }
}
Check 'D13 no prescriptive or cost-equals-quality language in the model' `
      ($langHits.Count -eq 0) $(if ($langHits) { ($langHits | Select-Object -Unique) -join ' | ' } else { 'clean' })

$conn.Close()

Write-Host ''
Write-Host '=== E. FILE HYGIENE ========================================================'

# No BOM anywhere: a BOM breaks PBIR parsing.
$bomFiles = @()
foreach ($f in (Get-ChildItem $ProjectRoot -Recurse -File -Include *.json,*.pbip,*.pbir,*.pbism,*.tmdl,*.platform -ErrorAction SilentlyContinue)) {
    $b = [System.IO.File]::ReadAllBytes($f.FullName)
    if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { $bomFiles += $f.FullName }
}
Check 'E1 no UTF-8 BOM in any project file' ($bomFiles.Count -eq 0) "withBom=$($bomFiles.Count)"

# Exactly ONE absolute path is expected - the DataFolder parameter.
$absHits = @()
foreach ($f in (Get-ChildItem $ProjectRoot -Recurse -File -Include *.json,*.pbip,*.pbir,*.pbism,*.tmdl -ErrorAction SilentlyContinue)) {
    if ($f.FullName -like '*\build\*') { continue }
    foreach ($line in (Get-Content $f.FullName)) {
        if ($line -match '(?<![A-Za-z0-9])[A-Za-z]:\\\\?[^\\/]') { $absHits += ("{0}: {1}" -f $f.Name, $line.Trim()) }
    }
}
Check 'E2 exactly one absolute path, and it is the DataFolder parameter' `
      ($absHits.Count -eq 1 -and $absHits[0] -like '*expressions.tmdl*DataFolder*') `
      ($(if ($absHits.Count) { ($absHits -join ' | ') } else { 'none found' }))

$userHits = @()
foreach ($f in (Get-ChildItem $ProjectRoot -Recurse -File -Include *.json,*.pbip,*.pbir,*.pbism,*.tmdl -ErrorAction SilentlyContinue)) {
    if ($f.FullName -like '*\build\*') { continue }
    if (Select-String -Path $f.FullName -Pattern 'C:\\Users\\' -SimpleMatch -Quiet) { $userHits += $f.Name }
}
Check 'E3 no user-specific path (C:\Users\...) in any project file' ($userHits.Count -eq 0) "hits=$($userHits -join ',')"

# Names must be word characters or hyphens: a space is silently dropped by Desktop.
$badNames = @()
foreach ($d in (Get-ChildItem (Join-Path $ProjectRoot "$Name.Report\definition\pages") -Recurse -Directory -ErrorAction SilentlyContinue)) {
    if ($d.Name -notmatch '^[A-Za-z0-9_][A-Za-z0-9_-]*$') { $badNames += $d.Name }
}
Check 'E4 every page/visual folder name is word-characters only' ($badNames.Count -eq 0) "bad=$($badNames -join ',')"

# 260-char Windows path limit. PBIR nests deeply, so this is a real failure mode.
$longest = 0
foreach ($f in (Get-ChildItem $ProjectRoot -Recurse -File)) { if ($f.FullName.Length -gt $longest) { $longest = $f.FullName.Length } }
Check 'E5 no path within 10 chars of the 260-char limit' ($longest -lt 250) "longest=$longest chars"

$visFiles = Get-ChildItem (Join-Path $ProjectRoot "$Name.Report\definition\pages") -Recurse -Filter visual.json
$badVis = @()
foreach ($f in $visFiles) {
    try {
        $j = Get-Content $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($j.'$schema' -notlike '*visualContainer/2.9.0*') { $badVis += $f.FullName }
        if (-not $j.name -or -not $j.position) { $badVis += $f.FullName }
    } catch { $badVis += $f.FullName }
}
CheckEq 'E6 visual.json files found' $visFiles.Count 98
Check 'E7 every visual.json parses and declares visualContainer/2.9.0' ($badVis.Count -eq 0) "bad=$($badVis.Count)"

# E8 catches the defect schema validation cannot: a bare Column in a chart's Y role. It
# validates perfectly and renders an EMPTY plot.
$badY = @()
foreach ($f in $visFiles) {
    $j = Get-Content $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $vt = $j.visual.visualType
    if ($vt -notmatch 'Chart$|^funnel$|^gauge$|^treemap$') { continue }
    $yRole = $j.visual.query.queryState.Y
    if (-not $yRole) { continue }
    foreach ($pr in $yRole.projections) {
        $names = $pr.field.PSObject.Properties.Name
        if (($names -notcontains 'Measure') -and ($names -notcontains 'Aggregation')) {
            $badY += ("{0} :: {1}" -f $f.Directory.Name, ($names -join ','))
        }
    }
}
Check 'E8 no chart plots a bare column in its value role (would render empty)' `
      ($badY.Count -eq 0) $(if ($badY) { $badY -join ' | ' } else { 'all value roles aggregated' })

Write-Host ''
Write-Host ('=' * 76)
Write-Host ("VALIDATION: {0} passed, {1} failed, {2} total" -f $script:Pass, $script:Fail, ($script:Pass + $script:Fail))
Write-Host ('=' * 76)
if ($script:Fail -gt 0) { exit 1 }
