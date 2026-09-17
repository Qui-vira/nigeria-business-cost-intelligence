# Power BI — Nigeria Business Cost Intelligence

**NBCI helps a business understand cost pressure. It does not by itself tell them which
jurisdiction will be most profitable.** The report is organised around business
questions rather than datasets, and states what it does NOT measure on its first page.

A Power BI **project (PBIP)**, not a `.pbix`: the semantic model is TMDL and the report is
PBIR, so both are plain text and diff properly in Git.

## Open it

```
powerbi\NBCI_Cost_Dashboard.pbip
```

Double-click it, or launch Power BI Desktop with the path as an argument. On a first open
the tables hold no data — the data cache is deliberately **not** committed. Press
**Home → Refresh → Schema and data** once; it takes about ten seconds and reads the 36 CSVs
in `data/`. If the repository is not at the path below, set `DataFolder` first — see
**Portability**.

## Portability — what happens when you clone this

**Short version.** After you clone, the project opens straight away. To see any data in it,
point one setting at the `powerbi\data` folder inside your own clone, then refresh. You do
not need a database, a password, or a network connection.

### The one setting you change

`DataFolder` is a Power Query parameter. It holds the full path of the folder that has the
36 CSV files the report reads. It lives in
`NBCI_Cost_Dashboard.SemanticModel/definition/expressions.tmdl`:

```
expression DataFolder = "C:\Projects\Nigeria Business Cost Intelligence\powerbi\data" meta [...]
```

Change it to `<your clone>\powerbi\data`, either in Power BI Desktop under
**Home → Transform data → Manage parameters**, or by editing that one line in the file.
Then **Home → Refresh**.

### The three things worth knowing, each one tested

| | |
|---|---|
| **1. The project opens after cloning, before you change anything** | Tested by pointing `DataFolder` at a path that does not exist and opening the project anyway. Power BI Desktop loaded it: **36 tables and 47 measures**, all pages present. The structure of the model is stored in the project itself, so it does not need the files to open. The tables simply hold no data yet |
| **2. Refresh needs `DataFolder` pointed at your clone's `powerbi\data`** | Until you do, a refresh stops with a clear message that names the folder it could not find: `[DataSource.NotFound] File or Folder: Could not find a part of the path ...`. It fails loudly. It does not quietly show you stale or wrong numbers |
| **3. You do not need PostgreSQL credentials to refresh** | Tested by copying the project to a different folder, pointing `DataFolder` at the copy, and running the full 82-check validation **while the PostgreSQL password on this machine was failing**. All 82 passed, including a cold-start refresh that deletes the cache first and genuinely re-reads the CSVs. PostgreSQL is used by the *builder* to regenerate those CSVs. The report never touches it |

### Why it is not a relative path

Power Query M has **no way to ask where its own file is**. Microsoft's own function
reference lists every data-access function, and the only "current" one is
`Excel.CurrentWorkbook`, which is Excel-only and returns a workbook's tables, not a path.
`File.Contents` and `Folder.Files` both take a full path and nothing else. Relative-path
support has been an open request from users for years and is still not in the product.

The workarounds people reach for are all worse than a parameter you set once:

* searching the drive with `Folder.Files` from the root is slow and can match the wrong
  folder;
* a fixed path such as `C:\NBCI\data` is still absolute, and it also forces where you may
  put the repository;
* there is no environment-variable function in M to read a path from.

So the parameter stays. It is the **only** absolute path in the project, it contains no
user name, and `pbi_validate.ps1` checks both of those on every run (E2 and E3).

### What the report reads

| Question | Answer |
|---|---|
| What the report reads | **Only `powerbi/data/*.csv`** — 36 files, 593 KB. All 36 tables use `Csv.Document(File.Contents(DataFolder & "\<table>.csv"))` |
| Database connections in the model | **None.** No SQL, no ODBC, no web source, no gateway |
| Absolute paths remaining | **One** — the `DataFolder` parameter |
| What a clone needs | `NBCI_Cost_Dashboard.pbip`, both item folders with their `definition/`, and `data/*.csv`. Nothing else |
| What a clone must change | The `DataFolder` value, unless it clones to the same path |

`powerbi/data/` **is committed**, deliberately. Unlike the Excel extracts — which duplicate
rows already embedded in the workbook — a PBIP embeds no data of its own, so these CSVs are
the only copy the report can read. `powerbi/build/` and `**/.pbi/cache.abf` are gitignored.

## What is in it

| | |
|---|---|
| Pages | 7, each named for the business question it answers — What is changing? · Fuel and energy · Moving people and goods · Where costs differ · How unusual is this month? · Which businesses are exposed? · Can I trust this? |
| Visuals | 94 |
| Tables | 36 — a star schema (`fact_cost`, `dim_jurisdiction`, `dim_metric`, `dim_date`) plus 32 evidence and explanation tables |
| Rows | 8,177 panel rows, jurisdiction × month × metric |
| Measures | 47 DAX measures |
| Relationships | 24 — all many-to-one, single direction |
| Compatibility level | 1606 |

Every page carries the same four-part band, so a reader never has to derive the conclusion
from a chart: **Signal** (what the data shows) · **What it means** (the business
implication) · **What to review** (what deserves attention) · **Boundary** (what this data
cannot tell you).

## The rules are enforced by the model, not by convention

A dashboard that relies on people remembering a rule will break the first time someone
drags a field. These are structural instead:

| Rule | How it is enforced |
|---|---|
| **G2** CPI index levels are never compared across jurisdictions | `[Median Value]` returns BLANK when a metric marked `comparable_across_jurisdictions = FALSE` is in filter context. `fact_cost[value]` is hidden so it cannot be aggregated directly |
| **G3** Food is zone grain only | `ref_food_zone` is given **no relationship** to `dim_jurisdiction`. The join that would let someone break the rule does not exist |
| **G4** NERC tariffs are DisCo grain, July 2025 cross-section | `ref_nerc_band` likewise has **no relationship** to `dim_jurisdiction` |
| **G9** Rank-unstable metrics may show spread but name no jurisdiction | `[Dearest Jurisdiction]` / `[Cheapest Jurisdiction]` return *"Not named — order unstable over time"* unless `dim_metric[rank_stable]` |
| **G11** Never interpolate across a known gap | `[Value YoY %]` returns BLANK with no 12-month-prior row, so the CPI line **breaks** at 2026-02 rather than bridging it |
| **G15** A median of 37 jurisdictions is not a national statistic | Every median measure is named and described that way |

Six relationships are **absent on purpose** and are listed as such in
`build/model_spec.json` under `relationshipsAbsentByDesign`. Do not "fix" them.

## No map — and why

Page 4 has **no choropleth**. The dashboard specification makes boundary reconciliation a
build gate: the geoBoundaries `gbOpen` NGA ADM1 file must be downloaded, hashed, and
matched 1:1 against all 37 jurisdictions before any map is drawn. That has not been done,
so the page uses ranked bars and tables instead. A map that silently drops or mismatches a
jurisdiction is worse than no map.

## Rebuild and validate

```bash
python src/dashboards/build_powerbi_project.py
```

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "src\dashboards\pbi_validate.ps1"
```

The validator is the point. It opens the project in Power BI Desktop, waits for the model
to load, triggers a **cold-start** refresh (it deletes `cache.abf` first, so the CSVs are
genuinely re-read), then interrogates the live Analysis Services engine: DMV queries for
tables, columns, relationships, partitions and measure errors; DAX queries reconciled
against the committed evidence CSVs; and a file-hygiene pass for BOMs, absolute paths,
folder-name legality and the 260-character path limit.

A build log saying "written" is not evidence. The Excel workbook in this repository once
shipped 20 invalid `#QNAN` literals that every build log called a success.

**And validation is not the same as looking at it.** A visual QA pass over all seven
rendered pages found six defects that every automated check had passed:

* a numeric **column** in a chart's value role renders an **empty plot** — it needs an
  explicit `Aggregation` wrapper. Schema-valid, and blank;
* cards bound to a per-metric evidence column with no metric in context **summed across
  nine incompatible units** — "spread = 68.40K" added naira-per-litre to naira-per-journey;
* the archetype paragraphs rendered as giant truncated headlines, because a card is not a
  prose visual;
* a text month column sorted **alphabetically** (Apr 2025, Apr 2026, Aug 2025 …);
* the headline chart was **scroll-clipped to 5 of 9 costs** by its own height;
* the rules table sorted G1, G10, G11 … G2, G3.

`pbi_validate.ps1` now has a check (E8) for the first of those. The rest are the reason
the rendered pages get looked at, not just the file.

**One practical note:** close Power BI Desktop before rebuilding. It holds a lock on the
report folder, and it caches the report in memory, so a rebuild underneath it is neither
possible nor picked up. The builder fails with a clear message if you try.

## Requirements

* **Power BI Desktop** — built and validated against 2.157.1354.0 (Microsoft Store).
* **Windows PowerShell 5.1** for the build and validation scripts. PowerShell 7 is .NET
  Core and the WindowsApps ACL refuses to load Power BI's assemblies into it with
  *"Access is denied"*.

Nothing else: no `pbi-tools`, no Tabular Editor, no `dotnet`, no Power BI MCP server.
