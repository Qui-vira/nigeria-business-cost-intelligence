# Build the NBCI semantic model as real Tabular Object Model objects and serialise it
# with Microsoft's own TmdlSerializer.
#
# WHY THIS EXISTS RATHER THAN HAND-WRITTEN TMDL
# ---------------------------------------------
# Hand-authoring a metadata format that cannot be opened is how the #QNAN defect reached the
# Excel build. Here the model is constructed through the TOM API - which rejects an invalid
# object as it is added - and written by the serializer that ships inside the installed Power
# BI Desktop. The on-disk TMDL is therefore whatever that build itself produces, not a guess.
#
# MUST RUN UNDER WINDOWS POWERSHELL 5.1 (.NET Framework).
# PowerShell 7 is .NET Core and is refused by the WindowsApps ACL with "Access is denied"
# when loading these assemblies.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File pbi_build_model.ps1 `
#       -SpecPath <model_spec.json> -OutPath <...SemanticModel\definition>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $SpecPath,
    [Parameter(Mandatory = $true)] [string] $OutPath,
    [string] $PbiBin = ''
)

$ErrorActionPreference = 'Stop'

function Resolve-PbiBin {
    if ($script:PbiBin -and (Test-Path $script:PbiBin)) { return $script:PbiBin }
    $pkg = Get-AppxPackage -Name 'Microsoft.MicrosoftPowerBIDesktop' -ErrorAction SilentlyContinue |
           Sort-Object Version -Descending | Select-Object -First 1
    if ($pkg) {
        $c = Join-Path $pkg.InstallLocation 'bin'
        if (Test-Path $c) { return $c }
    }
    foreach ($c in @('C:\Program Files\Microsoft Power BI Desktop\bin',
                     'C:\Program Files (x86)\Microsoft Power BI Desktop\bin')) {
        if (Test-Path $c) { return $c }
    }
    throw 'Power BI Desktop not found. Install it, or pass -PbiBin explicitly.'
}

$bin = Resolve-PbiBin
Write-Host "Power BI bin : $bin"
[void][System.Reflection.Assembly]::LoadFrom((Join-Path $bin 'Microsoft.PowerBI.Amo.dll'))
[void][System.Reflection.Assembly]::LoadFrom((Join-Path $bin 'Microsoft.PowerBI.Tabular.dll'))

$spec = Get-Content -Path $SpecPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Has($obj, [string]$prop) { return ($obj.PSObject.Properties.Name -contains $prop) }

# ---------------------------------------------------------------------------
# Database + model
# ---------------------------------------------------------------------------
# The four settings below are NOT cosmetic. They were read off Power BI Desktop's OWN
# blank model by serialising its live workspace database with this same TmdlSerializer -
# the "diff a trivial model" method - rather than guessed:
#
#     database <name>                       model Model
#         compatibilityLevel: 1606              culture: en-US
#         compatibilityMode: powerBI            defaultPowerBIDataSourceVersion: powerBI_V3
#         language: 1033                        valueFilterBehavior: independent
#                                               dataAccessOptions
#                                                   legacyRedirects
#                                                   returnErrorValuesAsNull
#
# Without `defaultPowerBIDataSourceVersion = PowerBI_V3` Desktop loads the model but
# REFUSES TO REFRESH IT, with "A data model with version 3 of metadata is required" -
# that property IS the "enhanced metadata / version 3" the message is asking for.
$database = New-Object Microsoft.AnalysisServices.Tabular.Database
$database.Name = $spec.name
$database.ID   = $spec.name
$database.CompatibilityLevel = [int]$spec.compatibilityLevel
$database.CompatibilityMode  = [Microsoft.AnalysisServices.CompatibilityMode]::PowerBI
$database.Language = 1033

$model = New-Object Microsoft.AnalysisServices.Tabular.Model
$model.Name = 'Model'
$model.Culture = $spec.culture
$model.DefaultPowerBIDataSourceVersion =
    [Microsoft.AnalysisServices.Tabular.PowerBIDataSourceVersion]::PowerBI_V3
$model.ValueFilterBehavior = [Microsoft.AnalysisServices.Tabular.ValueFilterBehaviorType]::Independent
$model.DataAccessOptions.LegacyRedirects = $true
$model.DataAccessOptions.ReturnErrorValuesAsNull = $true
$database.Model = $model

# Auto date/time is switched OFF deliberately. The model has its own `dim_date`, and
# leaving it on would have Power BI generate a hidden LocalDateTable_* per date column -
# dozens of tables that bloat the model and offer a second, unmanaged date hierarchy
# alongside the real one.
$tiAnn = New-Object Microsoft.AnalysisServices.Tabular.Annotation
$tiAnn.Name = '__PBI_TimeIntelligenceEnabled'
$tiAnn.Value = '0'
$model.Annotations.Add($tiAnn)

# The single point of configuration: where the model reads its CSVs from.
$param = New-Object Microsoft.AnalysisServices.Tabular.NamedExpression
$param.Name = 'DataFolder'
$param.Kind = [Microsoft.AnalysisServices.Tabular.ExpressionKind]::M
$param.Description = 'Folder holding the model CSVs. The ONLY machine-dependent setting in this project; change it here if the repository lives elsewhere.'
$param.Expression = '"' + $spec.dataFolderDefault + '" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
$model.Expressions.Add($param)

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
$sortLater = @()
foreach ($t in $spec.tables) {
    $table = New-Object Microsoft.AnalysisServices.Tabular.Table
    $table.Name = $t.name
    if (Has $t 'description')  { $table.Description  = $t.description }
    if (Has $t 'dataCategory') { $table.DataCategory = $t.dataCategory }

    foreach ($c in $t.columns) {
        $col = New-Object Microsoft.AnalysisServices.Tabular.DataColumn
        $col.Name         = $c.name
        $col.SourceColumn = $c.sourceColumn
        $col.DataType     = [Microsoft.AnalysisServices.Tabular.DataType]::($c.dataType)
        if (Has $c 'formatString') { $col.FormatString = $c.formatString }
        if (Has $c 'description')  { $col.Description  = $c.description }
        if ((Has $c 'isHidden') -and $c.isHidden) { $col.IsHidden = $true }
        if ((Has $c 'isKey')    -and $c.isKey)    { $col.IsKey    = $true }
        if (Has $c 'summarizeBy') {
            $col.SummarizeBy = [Microsoft.AnalysisServices.Tabular.AggregateFunction]::($c.summarizeBy)
        }
        if (Has $c 'sortByColumn') {
            $sortLater += , @($t.name, $c.name, $c.sortByColumn)
        }
        $table.Columns.Add($col)
    }

    foreach ($m in $t.measures) {
        $measure = New-Object Microsoft.AnalysisServices.Tabular.Measure
        $measure.Name       = $m.name
        $measure.Expression = $m.expression
        if (Has $m 'formatString')  { $measure.FormatString  = $m.formatString }
        if (Has $m 'displayFolder') { $measure.DisplayFolder = $m.displayFolder }
        if (Has $m 'description')   { $measure.Description   = $m.description }
        $table.Measures.Add($measure)
    }

    $partition = New-Object Microsoft.AnalysisServices.Tabular.Partition
    $partition.Name = $t.name
    $psource = New-Object Microsoft.AnalysisServices.Tabular.MPartitionSource
    $psource.Expression = $t.partitionExpression
    $partition.Source = $psource
    $table.Partitions.Add($partition)

    $model.Tables.Add($table)
}

# Sort-by columns need both columns to exist first.
foreach ($s in $sortLater) {
    $model.Tables[$s[0]].Columns[$s[1]].SortByColumn = $model.Tables[$s[0]].Columns[$s[2]]
}

# ---------------------------------------------------------------------------
# Relationships - all many-to-one, single direction.
# ---------------------------------------------------------------------------
foreach ($r in $spec.relationships) {
    $rel = New-Object Microsoft.AnalysisServices.Tabular.SingleColumnRelationship
    $rel.Name       = $r.name
    $rel.FromColumn = $model.Tables[$r.fromTable].Columns[$r.fromColumn]
    $rel.ToColumn   = $model.Tables[$r.toTable].Columns[$r.toColumn]
    $rel.FromCardinality = [Microsoft.AnalysisServices.Tabular.RelationshipEndCardinality]::Many
    $rel.ToCardinality   = [Microsoft.AnalysisServices.Tabular.RelationshipEndCardinality]::One
    $rel.CrossFilteringBehavior = [Microsoft.AnalysisServices.Tabular.CrossFilteringBehavior]::OneDirection
    $rel.IsActive = $true
    $model.Relationships.Add($rel)
}

# ---------------------------------------------------------------------------
# Serialise with Microsoft's own writer, then prove it round-trips.
# ---------------------------------------------------------------------------
if ([System.IO.Directory]::Exists($OutPath)) { [System.IO.Directory]::Delete($OutPath, $true) }
[Microsoft.AnalysisServices.Tabular.TmdlSerializer]::SerializeDatabaseToFolder($database, $OutPath)

$rt = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeDatabaseFromFolder($OutPath)
$measureCount = 0
foreach ($tb in $rt.Model.Tables) { $measureCount += $tb.Measures.Count }

Write-Host ''
Write-Host 'TMDL written and round-tripped through the same serializer:'
Write-Host ("  compatibilityLevel {0}" -f $rt.CompatibilityLevel)
Write-Host ("  tables             {0}" -f $rt.Model.Tables.Count)
Write-Host ("  relationships      {0}" -f $rt.Model.Relationships.Count)
Write-Host ("  measures           {0}" -f $measureCount)
Write-Host ("  expressions        {0}" -f $rt.Model.Expressions.Count)
Write-Host ("  -> {0}" -f $OutPath)
