cd $PSScriptRoot

$ErrorActionPreference = "Stop"

$entryName = if ($env:MCP_ENTRY_NAME) { $env:MCP_ENTRY_NAME } else { "obspy" }
$entryUrl  = if ($env:MCP_ENTRY_URL)  { $env:MCP_ENTRY_URL  } else { "http://localhost:7860/mcp" }
$imageName = if ($env:MCP_IMAGE_NAME) { $env:MCP_IMAGE_NAME } else { "obspy-mcp" }

$mcpDir = Join-Path $env:USERPROFILE ".cursor"
$mcpPath = Join-Path $mcpDir "mcp.json"
if (!(Test-Path $mcpDir)) { New-Item -ItemType Directory -Path $mcpDir | Out-Null }

$config = @{}
if (Test-Path $mcpPath) {
  try { $config = Get-Content $mcpPath -Raw | ConvertFrom-Json } catch { $config = @{} }
}

# Rebuild mcpServers as ordered and append the entry last
$serversOrdered = [ordered]@{}
if ($config -and ($config.PSObject.Properties.Name -contains "mcpServers") -and $config.mcpServers) {
  $existing = $config.mcpServers
  if ($existing -is [pscustomobject]) {
    foreach ($p in $existing.PSObject.Properties) { if ($p.Name -ne $entryName) { $serversOrdered[$p.Name] = $p.Value } }
  } elseif ($existing -is [System.Collections.IDictionary]) {
    foreach ($k in $existing.Keys) { if ($k -ne $entryName) { $serversOrdered[$k] = $existing[$k] } }
  }
}
$serversOrdered[$entryName] = @{ url = $entryUrl }
$config = @{ mcpServers = $serversOrdered }

$config | ConvertTo-Json -Depth 10 | Set-Content -Path $mcpPath -Encoding UTF8
Write-Host ("Updated $entryName in " + $mcpPath + " -> " + $entryUrl)

docker build -t $imageName .
docker run --rm -p 7860:7860 $imageName
