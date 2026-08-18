#!/usr/bin/env bash
set -euo pipefail

# Switch to the directory where this script is located
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

mcp_entry_name="${MCP_ENTRY_NAME:-obspy_xu}"
mcp_entry_url="${MCP_ENTRY_URL:-http://localhost:7860/mcp}"
mcp_dir="${HOME}/.cursor"
mcp_path="${mcp_dir}/mcp.json"
mkdir -p "${mcp_dir}"

if command -v python3 >/dev/null 2>&1; then
python3 - "${mcp_path}" "${mcp_entry_name}" "${mcp_entry_url}" <<'PY'
import json, os, sys
path, name, url = sys.argv[1:4]
cfg = {"mcpServers": {}}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {"mcpServers": {}}
if not isinstance(cfg, dict):
    cfg = {"mcpServers": {}}
servers = cfg.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
ordered = {}
for k, v in servers.items():
    if k != name:
        ordered[k] = v
ordered[name] = {"url": url}
cfg = {"mcpServers": ordered}
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PY
elif command -v python >/dev/null 2>&1; then
python - "${mcp_path}" "${mcp_entry_name}" "${mcp_entry_url}" <<'PY'
import json, os, sys
path, name, url = sys.argv[1:4]
cfg = {"mcpServers": {}}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {"mcpServers": {}}
if not isinstance(cfg, dict):
    cfg = {"mcpServers": {}}
servers = cfg.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
ordered = {}
for k, v in servers.items():
    if k != name:
        ordered[k] = v
ordered[name] = {"url": url}
cfg = {"mcpServers": ordered}
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PY
elif command -v jq >/dev/null 2>&1; then
  name="${mcp_entry_name}"; url="${mcp_entry_url}"
  if [ -f "${mcp_path}" ]; then
    tmp="$(mktemp)"
    jq --arg name "$name" --arg url "$url" '
      .mcpServers = (.mcpServers // {})
      | .mcpServers as $s
      | ($s | with_entries(select(.key != $name))) as $base
      | .mcpServers = ($base + {($name): {"url": $url}})
    ' "${mcp_path}" > "${tmp}" && mv "${tmp}" "${mcp_path}"
  else
    printf '{ "mcpServers": { "%s": { "url": "%s" } } }
' "$name" "$url" > "${mcp_path}"
  fi
else
  echo "Warning: neither python nor jq found; skipped updating ~/.cursor/mcp.json" >&2
fi

docker build -t obspy_xu-mcp .
docker run --rm -p 7860:7860 obspy_xu-mcp
