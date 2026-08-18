from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import redact_sensitive_data, redact_sensitive_text

DEFAULT_OUTPUT = PROJECT_ROOT / "benchmark" / "repositories_resolved.json"
DEFAULT_OVERRIDES = PROJECT_ROOT / "benchmark" / "manual_overrides.json"


def _repair_mojibake(value: str) -> str:
    if not value:
        return ""
    try:
        repaired = value.encode("gb18030").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired and repaired != value else value


def _row_value(row: dict[str, str], *keys: str) -> str:
    repaired = {_repair_mojibake(str(k)): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
        if key in repaired and repaired[key] is not None:
            return str(repaired[key]).strip()
    return ""


def _read_csv_legacy(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            repo = (row.get("repo") or "").strip()
            if not repo:
                continue
            rows.append(
                {
                    "nature_category": (row.get("Nature分类") or "").strip(),
                    "subcategory": (row.get("子类") or "").strip(),
                    "repo_name": repo,
                    "description": (row.get("描述") or "").strip(),
                    "expected_count": (row.get("数量") or "").strip(),
                }
            )
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    decoded = None
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        decoded = raw.decode("utf-8", errors="replace")

    rows = []
    for row in csv.DictReader(decoded.splitlines()):
        repo = _row_value(row, "repo", "repository", "仓库", "项目")
        if not repo:
            continue
        rows.append(
            {
                "nature_category": _repair_mojibake(_row_value(row, "Nature分类", "Nature category", "Nature鍒嗙被")),
                "subcategory": _repair_mojibake(_row_value(row, "子类", "subcategory", "瀛愮被")),
                "repo_name": _repair_mojibake(repo),
                "description": _repair_mojibake(_row_value(row, "描述", "description", "鎻忚堪")),
                "expected_count": _repair_mojibake(_row_value(row, "数量", "count", "鏁伴噺")),
            }
        )
    return rows


def _load_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {str(k).strip().lower(): str(v).strip() for k, v in data.items() if v}


def _github_request(url: str) -> dict[str, Any] | None:
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "Code2MCP-benchmark-resolver")
    token = os.getenv("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _without_url_credentials(value: str) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc or "@" not in parsed.netloc:
        return url
    host = parsed.hostname or ""
    if not host:
        return redact_sensitive_text(url)
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def _canonical_repo_url(value: str) -> str:
    url = _without_url_credentials(value)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() == "github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            owner = urllib.parse.quote(parts[0], safe="")
            repo = urllib.parse.quote(parts[1].removesuffix(".git"), safe="")
            return f"https://github.com/{owner}/{repo}"
    return url


def _search_github_repo(repo_name: str) -> dict[str, Any] | None:
    query = urllib.parse.quote(f"{repo_name} in:name")
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page=10"
    payload = _github_request(url)
    if not payload:
        return None
    items = payload.get("items") or []
    if not items:
        return None

    target = repo_name.lower().replace(" ", "-").replace("_", "-")

    def score(item: dict[str, Any]) -> tuple[int, int]:
        name = str(item.get("name") or "").lower()
        full = str(item.get("full_name") or "").lower()
        exact = 2 if name == target else 1 if target in {name, full.split("/")[-1]} else 0
        python = 1 if str(item.get("language") or "").lower() == "python" else 0
        return exact + python, int(item.get("stargazers_count") or 0)

    return sorted(items, key=score, reverse=True)[0]


def _repo_api_info(url: str) -> dict[str, Any] | None:
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].replace(".git", "")
    return _github_request(f"https://api.github.com/repos/{owner}/{repo}")


def _git_ls_remote(url: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--symref", url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": redact_sensitive_text(str(exc)), "default_branch": "", "latest_commit": ""}
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": redact_sensitive_text((proc.stderr or proc.stdout).strip()),
            "default_branch": "",
            "latest_commit": "",
        }

    default_branch = ""
    latest_commit = ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("ref:") and "HEAD" in line:
            ref = line.split()[1]
            default_branch = ref.removeprefix("refs/heads/")
        elif line.strip().endswith("\tHEAD"):
            latest_commit = line.split()[0]
    return {
        "ok": bool(latest_commit),
        "error": "",
        "default_branch": default_branch,
        "latest_commit": latest_commit,
    }


def _resolve_one(row: dict[str, str], overrides: dict[str, str]) -> dict[str, Any]:
    repo_name = row["repo_name"]
    key = repo_name.strip().lower()
    url = overrides.get(key)
    source = "manual_override" if url else "github_search"
    search_item = None

    if not url:
        if "github.com/" in repo_name:
            url = _canonical_repo_url(repo_name)
            source = "csv_url"
        else:
            search_item = _search_github_repo(repo_name)
            if search_item:
                url = _canonical_repo_url(str(search_item.get("html_url") or ""))
    else:
        url = _canonical_repo_url(url)

    info = _repo_api_info(url) if url else None
    clone_info = _git_ls_remote(url) if url else {"ok": False, "error": "no resolved url", "default_branch": "", "latest_commit": ""}
    clone_ok = bool(clone_info["ok"])

    result = {
        **row,
        "resolved_github_url": url or "",
        "resolution_source": source,
        "resolution_confidence": "high" if source in {"manual_override", "csv_url"} else "medium" if url else "none",
        "is_valid": False,
        "default_branch": "",
        "latest_commit": "",
        "language": "",
        "stars": 0,
        "archived": None,
        "size_kb": None,
        "clone_check": clone_ok,
        "notes": redact_sensitive_text(clone_info["error"]),
    }

    if info:
        result.update(
            {
                "default_branch": info.get("default_branch") or clone_info["default_branch"],
                "language": info.get("language") or "",
                "stars": int(info.get("stargazers_count") or 0),
                "archived": bool(info.get("archived", False)),
                "size_kb": info.get("size"),
            }
        )
        pushed = info.get("pushed_at") or ""
        result["last_updated"] = pushed
    else:
        result["default_branch"] = clone_info["default_branch"]

    result["latest_commit"] = clone_info["latest_commit"]
    result["is_valid"] = bool(url and clone_ok and result["archived"] is not True)
    if result["is_valid"]:
        result["notes"] = "" if info else "GitHub API metadata unavailable; validated by git ls-remote"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve CSV benchmark repo names to validated GitHub repositories.")
    parser.add_argument("--csv", required=True, help="Path to Repo汇总 CSV")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON manifest")
    parser.add_argument("--overrides", default=str(DEFAULT_OVERRIDES), help="Manual override JSON")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between GitHub API searches")
    parser.add_argument("--limit", type=int, default=0, help="Resolve only the first N rows for a smoke test")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    rows = _read_csv(csv_path)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    overrides = _load_overrides(Path(args.overrides))
    results = []
    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] resolving {redact_sensitive_text(row['repo_name'])}", flush=True)
        results.append(_resolve_one(row, overrides))
        if args.sleep:
            time.sleep(args.sleep)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(redact_sensitive_data(results), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    valid = sum(1 for item in results if item.get("is_valid"))
    print(f"Resolved {valid}/{len(results)} valid repositories -> {redact_sensitive_text(output)}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
