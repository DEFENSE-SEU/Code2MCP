<div align="center">

# Code2MCP: Transforming Code Repositories into MCP Services
![Official Repository](https://img.shields.io/badge/Repo-Official-green?style=flat-square)
[![arXiv](https://img.shields.io/badge/arXiv-2509.05941-b31b1b.svg?style=flat-square)](https://arxiv.org/abs/2509.05941)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
![Github stars](https://img.shields.io/github/stars/DEFENSE-SEU/Code2MCP.svg)

[Chaoqian Ouyang (欧阳超前)*](https://scholar.google.com/citations?user=w_WGwkwAAAAJ&hl=en)<img src="figs/SYSU.png" alt="Logo" width="20">, &nbsp; &nbsp;
[Ling YUE (岳凌)*](https://scholar.google.com/citations?user=EhgyJeYAAAAJ&hl=en)<img src="figs/RPI.png" alt="Logo" width="20">, &nbsp; &nbsp;
[Shimin Di (邸世民)](https://sdiaa.github.io/)✉<img src="figs/SEU.png" alt="Logo" width="20">, &nbsp; &nbsp;
[Libin Zheng (郑立彬)](https://libinzheng.github.io/)✉<img src="figs/SYSU.png" alt="Logo" width="20">, &nbsp; &nbsp;

[Linan Yue (岳立楠)](https://yuelinan.github.io/)<img src="figs/SEU.png" alt="Logo" width="20">, &nbsp; &nbsp;
[Shaowu Pan (潘韶武)](https://www.shaowupan.com/)<img src="figs/RPI.png" alt="Logo" width="20">, &nbsp; &nbsp;
[Jian Yin (印鉴)](https://sai.sysu.edu.cn/teacher/225)<img src="figs/SYSU.png" alt="Logo" width="20">, &nbsp; &nbsp;
[Min-Ling Zhang (张敏灵)](https://palm.seu.edu.cn/zhangml/)<img src="figs/SEU.png" alt="Logo" width="20">, &nbsp; &nbsp;

\* *Equal Contribution*
✉ *Corresponding Author*

</div>

## Project Overview

![Code2MCP Workflow Overview](figs/overview.png)

Code2MCP is an automated workflow system that transforms existing code repositories into MCP (Model Context Protocol) services. The system follows a minimal intrusion principle, preserving the original repository's core code while only adding service-related files and tests.

## Core Features

1. **Intelligent Code Analysis**
   - AST-first source analysis by default, with optional LLM enrichment
   - Automatic identification of real core modules, public functions, classes, signatures, imports, and file paths
   - Smart generation of MCP service code

2. **MCP Service Generation**
   - Automatic generation of `mcp_service.py`, `adapter.py`, and other core files
   - Support for multiple project structures (src/, source/, root directory, etc.)
   - Ranks safer wrapper candidates first and avoids complex parameters, unsafe paths, and classes that require constructor arguments

3. **Workflow Automation**
   - Complete 7-node workflow: download -> analysis -> env -> generate -> run -> review -> finalize
   - Automatic environment configuration and test validation
   - Comprehensive logging and status tracking
   - Intelligent error recovery and retry mechanisms

4. **End-to-End Automation**
   - Generates HuggingFace Spaces/Docker deployment scaffolding
   - Automatic client configuration after a validated local or remote service is available
   - Runtime validation is required before a conversion is marked successful

## Quick Start

### 1. Create a Python Environment

Code2MCP requires Python 3.10 or newer because FastMCP does not support Python 3.9.

Conda example:
```bash
conda create -n code2mcp python=3.12 -y
conda activate code2mcp
```

venv example, when your `python` is already 3.10+:
```bash
python -m venv .venv
```

Windows PowerShell:
```powershell
.\.venv\Scripts\Activate.ps1
```

Bash/macOS/Linux:
```bash
source .venv/bin/activate
```

Confirm the version:
```bash
python --version
```

### 2. Configure Environment Variables

Copy the environment variables template:
```bash
cp env.example .env
```

Windows PowerShell:
```powershell
Copy-Item .\env.example .\.env
```

Edit `.env` and fill `OPENAI_API_KEY` before running:
```bash
MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

If you already have a local Codex/OpenAI auth cache, you may use Codex auth instead:
```bash
MODEL_PROVIDER=openai-codex
OPENAI_API_KEY=
OPENAI_CODEX_AUTH_FILE=C:\Users\<you>\.codex\auth.json
```

### 3. Install Dependencies

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
```

The default Codex model is controlled by `OPENAI_CODEX_MODEL`. Override it if your account uses a different Codex backend model name.
Generated OpenAI Responses API copy examples use `OPENAI_RESPONSES_MODEL` when set, then `OPENAI_MODEL`, and finally `gpt-5`. They intentionally do not use `OPENAI_CODEX_MODEL`, because Codex auth/cache models and public OpenAI API example models are separate paths.

Code2MCP requires Python 3.10 or newer for FastMCP. If the `python` on PATH is older than 3.10, use a modern interpreter for installation and set `CODE2MCP_PYTHON` before running validation:
```bash
python --version
CODE2MCP_PYTHON=C:\path\to\python.exe
```

### 4. Run Workflow

Default Hugging Face preparation. This runs analysis, environment setup, generation, and finalize, then writes MCP files and deployment scaffolding. It does not push to Hugging Face unless `AUTO_DEPLOY_HF=true` and `HF_PUSH=true`:
```bash
python main.py https://github.com/<owner>/<repo>
```

Analysis is AST-first by default. LLM analysis can be enabled with `CODE2MCP_ANALYSIS_LLM=true`, but LLM output is filtered against static source evidence and cannot introduce tools for symbols that do not exist.

Generation, review, and finalize use deterministic service, adapter, README, repair-analysis, and summary fallbacks by default. Optional LLM-written adapter, README, review repair, and finalize analysis can be enabled with `CODE2MCP_ADAPTER_LLM=true`, `CODE2MCP_README_LLM=true`, `CODE2MCP_REVIEW_LLM=true`, and `CODE2MCP_FINALIZE_LLM=true`, but these are not required for validation and may add latency.

Generate files only, without runtime validation. This still runs analysis and environment preparation before generation, then skips run/review validation after generation. It returns a `generated` state, not a validated success:
```bash
python main.py https://github.com/<owner>/<repo> --generate-only
```

Validated local run. This generates local Docker scripts after validation. It does not start a long-running Docker service unless `CODE2MCP_LOCAL_AUTORUN=true`:
```text
python main.py https://github.com/<owner>/<repo> local
```

Local directories and `file://` URLs are supported. Code2MCP copies them into an isolated `workspace/<repo>/source` directory and ignores generated artifacts such as `.git`, `mcp_output`, `deployment`, and virtual environments:
```text
python main.py file:///C:/path/to/repo local
python main.py E:\path\to\repo local
```

Runtime validation uses `scripts/validate_mcp_service.py` with a real FastMCP Client. By default `CODE2MCP_CLIENT_VALIDATION_REQUIRE_SEMANTIC_SUCCESS=true`, `CODE2MCP_CLIENT_VALIDATION_REQUIRE_MEANINGFUL_RESULT=true`, and `CODE2MCP_CLIENT_VALIDATION_SEMANTIC_POLICY=all`, meaning at least one executed tool must return a structured `{"success": true}` result with a non-empty result payload, and any executed tool that returns `success=false` fails validation. All safely sampleable tools are called by default, while complex/path-like tools are skipped unless explicitly requested. Set `CODE2MCP_MAX_CLIENT_CALLS=<n>` or workflow option `max_client_calls` only when you intentionally want to cap validation for debugging.

Generation focuses on public functions by default. Class wrappers are disabled unless `CODE2MCP_ENABLE_CLASS_WRAPPERS=true`, because many classes require project state or data and object construction alone is rarely a useful MCP tool.

Environment setup installs the core MCP runtime first, then prefers package metadata or AST-discovered import packages over full `requirements.txt` files. This avoids treating docs/dev/heavy optional dependencies as mandatory for smoke validation. Set `CODE2MCP_INSTALL_FULL_REQUIREMENTS_FIRST=true` when you intentionally want requirements installed before the lightweight strategy, and `CODE2MCP_INSTALL_HEAVY_IMPORT_DEPS=true` when deeper native/scientific dependency installation is acceptable.

### 5. Deployment Guide

#### 5.1 Generated `deployment/` layout
```
workspace/<repo>/deployment/
- Dockerfile
- requirements.txt
- app.py
- run_docker.sh
- run_docker.ps1
- port.json
- connection_hint.json
- <repo_name>/
  - mcp_output/
    - start_mcp.py
    - mcp_plugin/
    - README_MCP.md
  - source/ (original repository files)
```

#### 5.2 Which path to follow
- `python main.py https://github.com/<owner>/<repo>` uses the default `hf` target and prepares Hugging Face deployment files.
- `python main.py https://github.com/<owner>/<repo> local` uses the local target and prepares local Docker scripts after validation.

#### 5.3 Hugging Face Spaces
By default Code2MCP creates the `deployment/` directory but does not push to Hugging Face. To push automatically, both of these must be true in `.env`:
```bash
AUTO_DEPLOY_HF=true
HF_PUSH=true
```

The generated deployment folder includes:
- `Dockerfile`: starts `workspace/<repo>/mcp_output/start_mcp.py` with `MCP_TRANSPORT=http` and `MCP_PORT=7860`
- `requirements.txt`: merged runtime requirements with `fastmcp` and `pydantic` included as a baseline
- `deployment_manifest.json`: records the entrypoint, transport, port, and `/mcp` path

When pushed to Hugging Face, the usable MCP endpoint is:
```text
https://{your-username}-{space-name}.hf.space/mcp
```

```bash
git clone https://huggingface.co/spaces/{your-username}/{space-name} {local-dir}
cd {local-dir}
```
Copy all files from `workspace/<repo>/deployment/` into `{local-dir}` root (do not include the `deployment` folder itself), then:
```bash
git add .
```

Remove local Git hooks if your environment enforces hooks:
- Bash:
  ```bash
  rm -rf .git/hooks
  ```
- PowerShell:
  ```powershell
  Remove-Item -Recurse -Force .git\hooks
  ```

```bash
git commit -m "Init"
git push
```

If `git push` fails due to large/binary files, use Git LFS and retry:
```bash
git lfs install
git lfs track "*.bin" "*.pt" "*.onnx" "*.h5" "*.npz" "*.pkl" "*.pickle" "*.tar" "*.gz" "*.zip" "*.7z" "*.so" "*.dll" "*.dylib" "*.png" "*.jpg" "*.jpeg"
git add .gitattributes
git add .
git commit -m "Use Git LFS"
git push
```
If large files already exist in history:
```bash
git lfs migrate import --include="*.bin,*.pt,*.onnx,*.h5,*.npz,*.pkl,*.pickle,*.tar,*.gz,*.zip,*.7z,*.so,*.dll,*.dylib,*.png,*.jpg,*.jpeg"
git push --force
```

Use the generated connection guide to choose the right payload for your agent:
```bash
python scripts/connect_agent.py --repo-root workspace/<repo> --open-guide --remote-url https://{your-username}-{space-name}.hf.space --probe-remote
```

If `--remote-url` is provided without `--probe-remote`, Code2MCP still writes copyable payloads, but
remote ChatGPT/OpenAI readiness stays false because the HTTPS MCP endpoint has not been verified with a
FastMCP client. Remote config writes require `--probe-remote`.

For clients that accept MCP JSON, the remote server shape is:
```json
{
  "mcpServers": {
    "{alias}": {
      "url": "https://{your-username}-{space-name}.hf.space/mcp"
    }
  }
}
```

#### 5.4 Local (port allocation & reuse)
- Port range: 7860–7999
- Strategy: derive a preferred port from repository name; if taken, probe the next available
- Record: `workspace/<repo>/deployment/port.json`
- Connection hint: `workspace/<repo>/deployment/connection_hint.json`
- Generated local scripts only build and start the Docker HTTP service. They do not modify Cursor, Claude, VS Code, or any other agent configuration.
- Code2MCP does not launch the local Docker service automatically unless `CODE2MCP_LOCAL_AUTORUN=true`.

No port conflict concerns
- The launcher derives a stable per-repository preferred port in 7860-7999.
- It probes availability with a bind test; if taken, it increments to the next free port.
- The chosen port is persisted to `workspace/<repo>/deployment/port.json` and the HTTP MCP URL is written to `workspace/<repo>/deployment/connection_hint.json`.
- On subsequent runs, it tries the recorded port first; if busy, it automatically picks the next free one.
- Multiple concurrent runs safely spread across free ports without clashes.

After starting the local Docker service, open `workspace/<repo>/mcp_output/agent_connect.html` or run:
```bash
python scripts/connect_agent.py --repo-root workspace/<repo> --client cursor --remote --remote-url http://localhost:<port> --probe-remote --write
python scripts/connect_agent.py --repo-root workspace/<repo> --client vscode --remote --remote-url http://localhost:<port> --probe-remote
python scripts/connect_agent.py --repo-root workspace/<repo> --client openai --remote-url http://localhost:<port> --probe-remote
```

## End-to-End Automation

**What Happens:**
1. Analyzes real source files under `workspace/<repo>/source`
2. Creates an isolated Python environment with the core MCP validation packages
3. Generates MCP service files from discovered public functions/classes
4. Runs import/create_app/tool-registration smoke tests and FastMCP Client tool calls
5. Attempts review/fix/regeneration on failure
6. Writes a final status: `validated`, `generated`, or `failed`
7. Writes deployment/local launch scripts without starting a long-running service by default

## Workflow Process

1. **Download Node**: Clone repository to `workspace/{repo_name}/`
2. **Analysis Node**: Analyze real source files and identify public modules/functions/classes
3. **Env Node**: Create isolated environment with core MCP validation packages and validate original project
4. **Generate Node**: Generate MCP service code from verified analysis results
5. **Run Node**: Execute import/create_app/tool-registration smoke tests and FastMCP Client tool calls
6. **Review Node**: Analyze runtime failures with heuristic evidence by default, record failed client-called tools, attempt deterministic generated-file fixes when safe, or regenerate while avoiding previously failed tools. Set `CODE2MCP_REVIEW_LLM=true` only when you want LLM-written review analysis and direct repairs.
7. **Finalize Node**: Compile results, write `validated`, `generated`, or `failed` status, generate connection/deployment artifacts, and use deterministic reports unless `CODE2MCP_FINALIZE_LLM=true`

`validated` means the generated service passed runtime smoke tests and client-level MCP tool validation. `generated` means files were produced with `--generate-only`, but the service was not verified. `failed` means Code2MCP could not prove the generated service runs.

## Security Validation

Generated tools that expose path-like inputs (`file_path`, `path`, `directory`, and similar names) must call `_safe_resolve_path` before invoking project code. The guard rejects absolute paths, URI schemes, home/UNC/network paths, `..` traversal, hidden path segments, sensitive path segments such as secret/token/password/key/credential/private/auth, and any path resolving outside the source directory.

The generator quality gate does not only check for the helper name. It compiles the helper in isolation and runs unsafe samples such as traversal, hidden files, URI paths, absolute paths, and sensitive path segments. A weak or placeholder helper fails generation/review and cannot be reported as `validated`.

Reusable safety policy helpers live under `src/security/`. Parameter and tool validation rules are centralized there so generation and client validation can share the same skip decisions without hard-coding them in the workflow path.

## Benchmark Validation

The repository includes scripts to validate Code2MCP against a curated CSV benchmark list.

Resolve repo names to real GitHub repositories:
```bash
python scripts/resolve_benchmark_repos.py --csv "D:\download\WeiXin\xwechat_files\wxid_d88haf3if05n12_cb61\msg\file\2025-12\Repo汇总-Sheet1(1).csv"
```

Run the first 50 valid repositories with resumable logging:
```bash
python scripts/run_benchmark.py --manifest benchmark/repositories_resolved.json --limit 50 --resume
```

The benchmark runs the workflow and then invokes the generated MCP service through `scripts/validate_mcp_service.py`. By default it requires at least one called tool to return `{"success": true}` with a non-empty result payload; use `--no-require-semantic-success` or `--no-require-meaningful-result` only for transport-only diagnostics. Use `--semantic-policy any|all|none` to tune how returned `{"success": ...}` payloads are interpreted. Benchmark validation also calls all safely sampleable tools by default; pass `--max-client-calls <n>` only for capped exploratory runs. Each result records the Code2MCP commit and whether the working tree was dirty, so benchmark evidence can be traced back to the exact code version. Outputs are written under `benchmark/` and are intentionally ignored by git: `results*.json`, `benchmark_report*.md`, per-repository logs, and artifact snapshots containing fresh `workflow_summary.json`, `run_log.json`, `analysis.json`, `env_info.json`, and `error_analysis.json` when available.

## Output Structure

Complete structure for each converted project:

![Output Structure](figs/Output-Structure.png)

## Successfully Converted Project Examples

- **UFL**: Finite element symbolic language → MCP finite element analysis
- **dalle-mini**: Higher-quality, controllable text-to-image → MCP image generation
- **ESM**: Protein structure/variant scoring (real artifacts) → MCP protein analysis
- **deep-searcher**: Query rewrite, multi-hop, credible sources → MCP search
- **TextBlob**: Deterministic tokenize/POS/sentiment → MCP NLP preprocessing
- **dateutil**: Correct timezones/rrule edge cases → MCP time utilities
- **sympy**: Exact symbolic math/solve/codegen → MCP math reasoning

## Key Features

- **Smart Import Handling**: Automatic identification of correct module import paths
- **Professional Documentation**: Automatic generation of English README and comments
- **Comprehensive Test Coverage**: Includes basic functionality tests and health checks
- **Detailed Report Generation**: Provides complete conversion process reports
- **Intelligent Dependency Management**: Automatic handling of complex Python package dependencies

## Usage Example

```bash
python main.py https://github.com/username/repo
```

## Quick Agent Connection

Code2MCP writes reusable connection files for every generated service:

```
workspace/<repo>/mcp_output/agent_connect.html
workspace/<repo>/mcp_output/agent_connection.json
workspace/<repo>/mcp_output/agent_mcp_config.json
workspace/<repo>/mcp_output/cursor_mcp_config.json
```

For a local MCP service, no Hugging Face deployment is required. After the workflow is `validated`, open the copy guide and choose the agent you use:

```bash
python scripts/connect_agent.py --repo-root workspace/<repo> --open-guide
```

The guide shows what to copy for Cursor, Claude Desktop, Claude Code, VS Code, Windsurf, Cline, Gemini CLI, ChatGPT, OpenAI API, generic MCP clients, local stdio mode, and remote HTTP mode.

GPT / ChatGPT note:
- ChatGPT apps and the OpenAI Responses API use remote MCP servers, not local stdio `command`/`args`.
- Deploy the generated service to an HTTPS MCP endpoint first, then copy the ChatGPT or OpenAI API card from `agent_connect.html`.
- The OpenAI API card contains a `tools` entry with `type: "mcp"` and `server_url`.

If you intentionally want Code2MCP to write Cursor config for you:

```bash
python scripts/connect_agent.py --repo-root workspace/<repo> --client cursor --write
```

To preview the MCP JSON without writing any client config:

```bash
python scripts/connect_agent.py --repo-root workspace/<repo> --client generic
```

To verify a task-level agent call, run the generated MCP service through a real FastMCP client with a natural-language task and explicit arguments:

```bash
python scripts/agent_validate_mcp_service.py --repo-root workspace/<repo> --task "format 1536 bytes as a natural size" --arguments-file args.json --expect-contains "kB"
```

This harness lists tools, selects the best matching tool by weighted name/description/schema overlap, refuses ambiguous selection unless `--expect-tool` is provided, calls the tool, and checks the returned result. It requires `{"success": true}` and a non-empty result by default; use `--no-require-success --no-require-meaningful-result` only for transport-only diagnostics. Prefer `--arguments-file` for JSON on Windows shells. It is meant for scenario validation after the general smoke/client validation has already passed.

You can also connect immediately after a successful conversion:

```text
python main.py https://github.com/<owner>/<repo> local --connect-client cursor --connect-write
```

Safety behavior:
- Client config writes are refused unless `workflow_summary.json` says the MCP service is `validated`.
- Use `--allow-unvalidated` only when intentionally testing an unverified service.
- Existing Cursor config is merged under `mcpServers`; if a config file already exists, a timestamped backup is created first.
- The HTML guide never writes client files; it only displays copyable configuration.

For remote services, deploy first and then pass the remote base URL:

```bash
python scripts/connect_agent.py --repo-root workspace/<repo> --client cursor --remote-url https://<space>.hf.space --remote --probe-remote --write
python scripts/connect_agent.py --repo-root workspace/<repo> --client vscode --remote-url https://<space>.hf.space --remote --probe-remote
python scripts/connect_agent.py --repo-root workspace/<repo> --client openai --remote-url https://<space>.hf.space --probe-remote
```

-----

## Citation

If you use Code2MCP in your research, please cite our paper:

```bibtex
@article{ouyang2025code2mcp,
  title={Code2MCP: Transforming Code Repositories into MCP Services},
  author={Ouyang, Chaoqian and Yue, Ling and Di, Shimin and Zheng, Libin and Yue, Linan and Pan, Shaowu and Yin, Jian and Zhang, Min-Ling},
  journal={arXiv preprint arXiv:2509.05941},
  year={2025}
}
```



