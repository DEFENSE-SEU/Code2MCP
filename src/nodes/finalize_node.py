# Finalize Node - Compile results and output final status
from __future__ import annotations
import os
import json
import time
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List
from ..utils import derive_repo_name, setup_logging, write_file, get_llm_service, redact_sensitive_text, sanitize_deepwiki_content
from ..tools.deploy_hf import deploy_to_huggingface, create_and_run_local_scripts
from ..tools.quick_connect import QuickConnectError, build_connection_profile, connect_agent, write_connection_files

logger = setup_logging()


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _finalize_llm_enabled() -> bool:
    return _truthy_env("CODE2MCP_FINALIZE_LLM", "false")


def _finalize_summary_log_message() -> str:
    if _finalize_llm_enabled():
        return "Starting optional LLM finalize summary generation"
    return "Generating deterministic finalize summary (LLM disabled)"


def _is_valid_deepwiki_content(content: str) -> bool:
    content = sanitize_deepwiki_content(content)
    if not content or len(content.strip()) < 50:
        return False
    
    loading_indicators = ["Loading...", "loading", "Please wait", "Analyzing", "Processing"]
    if any(indicator in content for indicator in loading_indicators) and len(content.strip()) < 200:
        return False
    
    valid_indicators = ["Analysis", "Repository", "Functions", "Classes", "Dependencies", "Features", "Description", "Overview"]
    if any(indicator in content for indicator in valid_indicators):
        return True
    
    if len(content) > 200 and not content.strip().startswith("Warning:"):
        return True
    
    return False


def _deterministic_project_type_description(analysis: Dict[str, Any]) -> str:
    project_type = _detect_project_type_from_static_evidence(analysis)
    labels = {
        "Python": "Python library",
        "C/C++": "C/C++ project",
        "Swift": "Swift package",
        "Rust": "Rust project",
        "Java": "Java project",
        "JavaScript/TypeScript": "JavaScript/TypeScript project",
        "R": "R project",
    }
    return labels.get(project_type, "Python library")


def _repository_language_from_analysis(analysis: Dict[str, Any]) -> str:
    detected = _detect_project_type_from_static_evidence(analysis)
    if detected != "Unknown":
        return detected
    deepwiki = analysis.get("deepwiki_analysis", {}) if isinstance(analysis, dict) else {}
    if isinstance(deepwiki, dict) and deepwiki.get("language"):
        return str(deepwiki["language"])
    return "Python"


def _detect_project_type_from_static_evidence(analysis: Dict[str, Any]) -> str:
    if not isinstance(analysis, dict):
        return "Unknown"

    explicit_sources = [
        analysis.get("project_type"),
        (analysis.get("llm_analysis") or {}).get("project_type") if isinstance(analysis.get("llm_analysis"), dict) else None,
    ]
    for value in explicit_sources:
        normalized = _normalize_project_type(value)
        if normalized != "Unknown":
            return normalized

    cpp_info = analysis.get("cpp_info", {}) if isinstance(analysis.get("cpp_info", {}), dict) else {}
    if cpp_info.get("has_cpp_files"):
        return "C/C++"

    deps = analysis.get("dependencies", {}) if isinstance(analysis.get("dependencies", {}), dict) else {}
    structure = analysis.get("structure", {}) if isinstance(analysis.get("structure", {}), dict) else {}
    if deps.get("pyproject") or deps.get("setup_py") or deps.get("setup_cfg") or structure.get("packages"):
        return "Python"

    summary = analysis.get("summary", {}) if isinstance(analysis.get("summary", {}), dict) else {}
    file_tree = summary.get("file_tree", {}) if isinstance(summary.get("file_tree", {}), dict) else {}
    source_paths = [str(path).replace("\\", "/").strip("/") for path in file_tree.keys()]
    lower_paths = [path.lower() for path in source_paths]
    basenames = {os.path.basename(path) for path in lower_paths}

    if "package.swift" in basenames or any(path.endswith(".swift") for path in lower_paths):
        return "Swift"
    if "cargo.toml" in basenames or any(path.endswith(".rs") for path in lower_paths):
        return "Rust"
    if "pom.xml" in basenames or "build.gradle" in basenames or "build.gradle.kts" in basenames or any(path.endswith(".java") for path in lower_paths):
        return "Java"
    if "package.json" in basenames or any(path.endswith((".js", ".jsx", ".ts", ".tsx")) for path in lower_paths):
        return "JavaScript/TypeScript"
    if any(path.endswith((".cpp", ".hpp", ".cc", ".cxx", ".c", ".h")) for path in lower_paths):
        return "C/C++"
    if any(path.endswith((".r", ".rmd")) for path in lower_paths):
        return "R"
    if any(path.endswith(".py") for path in lower_paths):
        return "Python"

    llm_analysis = analysis.get("llm_analysis", {}) if isinstance(analysis.get("llm_analysis", {}), dict) else {}
    for module in llm_analysis.get("core_modules", []) or []:
        if not isinstance(module, dict):
            continue
        path = str(module.get("file_path") or module.get("package") or "").lower()
        if path.endswith(".py"):
            return "Python"
        if path.endswith((".cpp", ".hpp", ".cc", ".cxx", ".c", ".h")):
            return "C/C++"

    language_sources = [
        analysis.get("language"),
        (analysis.get("deepwiki_analysis") or {}).get("language") if isinstance(analysis.get("deepwiki_analysis"), dict) else None,
        (analysis.get("llm_analysis") or {}).get("language") if isinstance(analysis.get("llm_analysis"), dict) else None,
    ]
    for value in language_sources:
        normalized = _normalize_project_type(value)
        if normalized != "Unknown":
            return normalized

    return "Unknown"


def _normalize_project_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or text in {"unknown", "none", "null"}:
        return "Unknown"
    if "swift" in text:
        return "Swift"
    if "rust" in text:
        return "Rust"
    if "java" in text and "script" not in text:
        return "Java"
    if any(token in text for token in ["javascript", "typescript", "node", "npm"]):
        return "JavaScript/TypeScript"
    if "c++" in text or "cpp" in text or "c/c++" in text:
        return "C/C++"
    if text in {"c"}:
        return "C/C++"
    if text in {"r"} or " r " in f" {text} ":
        return "R"
    if "python" in text or "pyproject" in text:
        return "Python"
    return "Unknown"

def _generate_llm_summary(state: Dict[str, Any], workflow_summary: Dict[str, Any]) -> Dict[str, Any]:
    if not _finalize_llm_enabled():
        return _default_llm_analysis(workflow_summary)

    try:
        llm_service = get_llm_service()
        
        system_prompt = """You are an expert AI software engineer specializing in analyzing the results of automated code-to-service generation workflows.

Your task is to provide a comprehensive, professional analysis based on the provided workflow data, focusing on success factors, diagnostics, and actionable recommendations.

Please return the results in JSON format with the specified structure."""

        user_prompt = f"""Please analyze the following MCP workflow execution results:

Workflow Summary: {workflow_summary}

Detailed State Information:
- Repository Info: {state.get('repository', {})}
- Analysis Results: {state.get('analysis', {})}
- Service Info: {state.get('plugin', {})}
- Code Review: {state.get('code_review', {})}
- Environment Info: {state.get('env', {})}
- Current Errors: {workflow_summary.get('errors', [])}
- Recovered Errors: {workflow_summary.get('recovered_errors', [])}
- Warnings: {state.get('warnings', [])}
- Performance Metrics: {state.get('performance', {})}
- Test Results: {state.get('tests', {})}

Please provide a professional analysis from the following perspectives:

1. Execution Assessment:
   - Did the workflow complete successfully?
   - What were the key success factors?
   - What were the root causes of failure, if any?
   - Execution status and duration for each node.

2. Technical Implementation Quality:
   - Assessment of the generated code quality.
   - Soundness of the architectural design.
   - Performance considerations and optimization opportunities.
   - Evaluation of security and stability.

3. Issue Diagnosis:
   - Identification of potential issues.
   - Analysis of error causes.
   - Assessment of risk factors.
   - Analysis of performance bottlenecks.

4. Improvement Recommendations:
   - Specific technical improvement suggestions.
   - Recommendations for best practices.
   - Future optimization directions.
   - Deployment and operational advice.

5. Project Value Assessment:
   - Value of the MCP service to the original project.
   - Analysis of potential use cases.
   - Suggestions for promotion and adoption.
   - Assessment of business value.

6. In-depth Technical Analysis:
   - Code complexity analysis.
   - Dependency relationship assessment.
   - Scalability evaluation.
   - Maintenance cost estimation.

Please return the results in JSON format:
{{
    "execution_analysis": {{
        "success_factors": ["Factor 1", "Factor 2"],
        "failure_reasons": ["Reason 1", "Reason 2"],
        "overall_assessment": "excellent/good/fair/poor",
        "node_performance": {{
            "download_time": "Analysis of time taken",
            "analysis_time": "Analysis of time taken",
            "generation_time": "Analysis of time taken",
            "test_time": "Analysis of time taken"
        }},
        "resource_usage": {{
            "memory_efficiency": "Memory usage efficiency analysis",
            "cpu_efficiency": "CPU usage efficiency analysis",
            "disk_usage": "Disk usage analysis"
        }}
    }},
    "technical_quality": {{
        "code_quality_score": 0-100,
        "architecture_score": 0-100,
        "performance_score": 0-100,
        "maintainability_score": 0-100,
        "security_score": 0-100,
        "scalability_score": 0-100
    }},
    "issue_diagnosis": {{
        "critical_issues": ["Critical issue 1", "Critical issue 2"],
        "potential_risks": ["Potential risk 1", "Potential risk 2"],
        "recommended_fixes": ["Fix recommendation 1", "Fix recommendation 2"],
        "performance_bottlenecks": ["Bottleneck 1", "Bottleneck 2"],
        "security_vulnerabilities": ["Vulnerability 1", "Vulnerability 2"]
    }},
    "improvement_recommendations": {{
        "technical_improvements": ["Improvement 1", "Improvement 2"],
        "best_practices": ["Best practice 1", "Best practice 2"],
        "future_optimizations": ["Optimization 1", "Optimization 2"],
        "deployment_recommendations": ["Deployment recommendation 1", "Deployment recommendation 2"],
        "monitoring_suggestions": ["Monitoring suggestion 1", "Monitoring suggestion 2"]
    }},
    "project_value": {{
        "value_assessment": "high/medium/low",
        "use_cases": ["Use case 1", "Use case 2"],
        "promotion_suggestions": ["Suggestion 1", "Suggestion 2"],
        "market_potential": "Market potential assessment",
        "competitive_advantages": ["Advantage 1", "Advantage 2"]
    }},
    "technical_insights": {{
        "complexity_analysis": "Complexity analysis",
        "dependency_analysis": "Dependency analysis",
        "scalability_assessment": "Scalability assessment",
        "maintenance_cost": "Maintenance cost estimation"
    }},
    "summary": "Overall summary and key insights"
}}"""

        response = llm_service.generate_text(user_prompt, system_prompt)
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                logger.info("LLM intelligent summary generated successfully")
                return result
            else:
                result = json.loads(response.strip())
                logger.info("LLM intelligent summary generated successfully (direct parsing)")
                return result
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing failed: {e}")
            logger.debug(f"Original response: {response[:200]}...")
        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            logger.debug(f"Original response: {response[:200]}...")
        
        return _default_llm_analysis(workflow_summary)
        
    except Exception as e:
        logger.error(f"LLM intelligent summary generation failed: {e}")
        return _default_llm_analysis(workflow_summary)

def _default_llm_analysis(workflow_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Default LLM analysis results"""
    execution = workflow_summary.get("execution", {})
    status = execution.get("status", workflow_summary.get("status", "unknown"))
    workflow_status = execution.get("workflow_status", workflow_summary.get("workflow_status"))
    validation_status = execution.get("validation_status", workflow_summary.get("validation_status"))
    verified = bool(execution.get("verified", workflow_summary.get("verified", False)))
    validated = bool(
        verified
        and (
            workflow_status == "validated"
            or validation_status == "validated"
            or status == "validated"
        )
    )
    tests = workflow_summary.get('tests', {})
    
    return {
        "execution_analysis": {
            "success_factors": ["Runtime validation completed"] if validated else [],
            "failure_reasons": ["MCP validation did not pass"] if not tests.get('mcp_plugin', {}).get('passed', False) else [],
            "overall_assessment": "good" if validated else "poor"
        },
        "technical_quality": {
            "code_quality_score": 80 if validated else 60,
            "architecture_score": 75 if validated else 50,
            "performance_score": 70,
            "maintainability_score": 75
        },
        "issue_diagnosis": {
            "critical_issues": [],
            "potential_risks": ["Further testing required"],
            "recommended_fixes": ["Recommend comprehensive testing"]
        },
        "improvement_recommendations": {
            "technical_improvements": ["Optimize error handling"],
            "best_practices": ["Follow MCP best practices"],
            "future_optimizations": ["Consider performance optimization"]
        },
        "project_value": {
            "value_assessment": "medium",
            "use_cases": ["AI assistant integration"],
            "promotion_suggestions": ["Promote to related projects"]
        },
        "summary": "Workflow basically completed, recommend further optimization"
    }

def _generate_technical_report(state: Dict[str, Any], workflow_summary: Dict[str, Any], llm_analysis: Dict[str, Any]) -> str:
    """Generate professional technical report using LLM"""
    if not _finalize_llm_enabled():
        return _default_technical_report(state, workflow_summary, llm_analysis)

    try:
        llm_service = get_llm_service()
        
        system_prompt = """You are an expert technical writer specializing in creating documentation for AI-native services built with FastMCP.

Key Concepts:
- MCP (Model Context Protocol): A standard for communication between AI models and external tools.
- FastMCP: A Python library for rapidly creating MCP-compliant tool services, enabling AI models to call external functions.

Your task is to generate a professional, detailed technical report based on the provided project information, covering implementation details, architecture, and usage guidelines.

Please output the report in Markdown format."""

        user_prompt = f"""Please generate a professional technical report for the following FastMCP project:

Project Information: {state.get('repository', {})}
Workflow Summary: {workflow_summary}
LLM Analysis Results: {llm_analysis}

Please create a comprehensive technical report in Markdown format that includes the following sections:

1.  Project Overview: Background, objectives, and value proposition.
2.  Technical Architecture: Design of the MCP tool service and technology choices.
3.  Implementation Details: Key implementation steps and technical highlights.
4.  Features: Introduction to the main functions and capabilities.
5.  Deployment Guide: Detailed instructions for deployment and usage.
6.  Test Results: Summary of test outcomes and performance evaluation.
7.  Best Practices: Recommendations for effective use.
8.  Future Roadmap: Suggestions for subsequent optimizations and development.

Crucial Requirements:
- Clearly state that this is an AI tool service enabling models to invoke external functions.
- Emphasize the role of the MCP standard in standardizing AI-tool communication.
- Describe potential applications, such as AI assistants, code generation, automated workflows, and data analysis.
- Use professional technical terminology.
- Ensure the report is well-structured, technically accurate, and easy to understand.
- Include code examples and configuration details where appropriate.
- Do not describe the conversion as successful unless Workflow Summary reports workflow_status=validated and verified=true.
- If the workflow is generated or failed, clearly state that runtime/client validation did not prove a production-ready MCP service.
- Output the raw Markdown content directly, without using Markdown code block fences (e.g., ```markdown).
- Use ```python for Python code examples."""

        technical_report = llm_service.generate_text(user_prompt, system_prompt)
        
        if technical_report and len(technical_report.strip()) > 500:
            logger.info("LLM technical report generated successfully")
            return technical_report
        else:
            logger.warning("LLM technical report generation failed, using default template")
            return _default_technical_report(state, workflow_summary, llm_analysis)
        
    except Exception as e:
        logger.error(f"LLM technical report generation failed: {e}")
        return _default_technical_report(state, workflow_summary, llm_analysis)

def _default_technical_report(state: Dict[str, Any], workflow_summary: Dict[str, Any], llm_analysis: Dict[str, Any]) -> str:
    repo = state.get("repository", {})
    repo_name = repo.get("name", "unknown")
    execution = workflow_summary.get("execution", {}) if isinstance(workflow_summary.get("execution"), dict) else {}
    workflow_status = workflow_summary.get("workflow_status") or execution.get("workflow_status") or workflow_summary.get("status") or "unknown"
    validation_status = workflow_summary.get("validation_status") or execution.get("validation_status") or "unknown"
    verified = bool(workflow_summary.get("verified") if "verified" in workflow_summary else execution.get("verified"))
    if workflow_status == "validated" and verified:
        overview = f"This project was converted to a FastMCP service and passed runtime/client validation."
        readiness = "Production readiness: validated by runtime smoke tests and FastMCP client tool-call evidence."
    elif workflow_status == "generated":
        overview = f"Code2MCP generated FastMCP service files for {repo_name}, but runtime/client validation was skipped."
        readiness = "Production readiness: not validated. Do not connect this service to production agents until the default workflow reaches validated."
    else:
        overview = f"Code2MCP generated diagnostic MCP artifacts for {repo_name}, but could not prove the service is runnable."
        readiness = "Production readiness: failed or incomplete validation. Treat these files as diagnostic artifacts."
    unsupported_audit = _unsupported_audit_section(workflow_summary)
    
    return f"""# {repo_name} Code2MCP Service Technical Report

## Project Overview
{overview}

## Validation Status
- Workflow Status: {workflow_status}
- Validation Status: {validation_status}
- Verified: {str(verified).lower()}
- {readiness}

{unsupported_audit}

## Technical Architecture
- Adapter Mode: {state.get('plugin', {}).get('adapter_mode', 'unknown')}
- Service Entry Point: start_mcp.py
- Core Components: mcp_plugin directory

## Test Results
- Original Project Test: {'Passed' if workflow_summary.get('tests', {}).get('original_project', {}).get('passed', False) else 'Failed'}
- MCP Service Test: {'Passed' if workflow_summary.get('tests', {}).get('mcp_plugin', {}).get('passed', False) else 'Failed'}

---
*This report was automatically generated by Code2MCP*
"""

def _extract_features_from_analysis(analysis: Dict[str, Any]) -> str:
    if not _finalize_llm_enabled():
        return "Basic functionality"

    try:
        llm_service = get_llm_service()
        
        deepwiki_analysis = analysis.get("deepwiki_analysis", {}).get("analysis", "")
        if not _is_valid_deepwiki_content(deepwiki_analysis):
            return "Basic functionality"
        
        prompt = f"""Analyze the main features of this project, return the feature list directly (separated by commas):

{deepwiki_analysis[:800]}"""
        
        try:
            response = llm_service.generate_text(prompt, "Extract project feature characteristics")
            if response and len(response.strip()) > 5:
                return response.strip()
        except:
            pass
        
        return "Basic functionality"
            
    except Exception as e:
        logger.warning(f"Feature extraction failed: {e}")
        return "Basic functionality"

def _extract_project_type_from_analysis(analysis: Dict[str, Any]) -> str:
    fallback = _deterministic_project_type_description(analysis)
    if not _finalize_llm_enabled():
        return fallback

    try:
        llm_service = get_llm_service()
        
        deepwiki_analysis = analysis.get("deepwiki_analysis", {}).get("analysis", "")
        if not _is_valid_deepwiki_content(deepwiki_analysis):
            return fallback
        
        prompt = f"""Summarize this project type in one sentence:

{deepwiki_analysis[:500]}"""
        
        try:
            response = llm_service.generate_text(prompt, "Summarize project type")
            if response and len(response.strip()) > 5:
                return response.strip()
        except:
            pass
        
        return fallback
    except Exception as e:
        logger.warning(f"Project type extraction failed: {e}")
        return fallback

def _extract_generated_tools(plugin: Dict[str, Any], analysis: Dict[str, Any]) -> list:
    try:
        endpoints = [
            str(endpoint).strip()
            for endpoint in (plugin.get("endpoints") or [])
            if str(endpoint).strip()
        ]
        if endpoints:
            return endpoints

        plugin_tools = plugin.get("tools", {})
        tool_names = [
            str(name).strip()
            for name in (plugin_tools.get("names") or plugin_tools.get("items") or [])
            if str(name).strip()
        ]
        if tool_names:
            return tool_names

        return []
    except Exception as e:
        logger.warning(f"Tool extraction failed: {e}")
        return []


def _analysis_file_count(analysis: Dict[str, Any]) -> int:
    summary = analysis.get("summary", {}) if isinstance(analysis, dict) else {}
    stats = summary.get("stats", {}) if isinstance(summary, dict) else {}
    try:
        total = int(stats.get("total_files", 0))
        if total > 0:
            return total
    except (TypeError, ValueError):
        pass

    file_tree = summary.get("file_tree", {}) if isinstance(summary, dict) else {}
    if isinstance(file_tree, dict) and file_tree:
        return len(file_tree)

    structure = analysis.get("structure", {}) if isinstance(analysis, dict) else {}
    files = structure.get("files", []) if isinstance(structure, dict) else []
    if isinstance(files, list) and files:
        return len(files)

    static_analysis = analysis.get("static_analysis", {}) if isinstance(analysis, dict) else {}
    modules = static_analysis.get("modules", []) if isinstance(static_analysis, dict) else []
    if isinstance(modules, list) and modules:
        return len({module.get("file_path") for module in modules if isinstance(module, dict) and module.get("file_path")})
    return 0


def _generated_file_metrics(plugin: Dict[str, Any]) -> Dict[str, Any]:
    files = plugin.get("files", {}) if isinstance(plugin, dict) else {}
    paths = files.values() if isinstance(files, dict) else []
    total_bytes = 0
    total_lines = 0
    counted_files = 0
    for raw_path in paths:
        path = Path(str(raw_path))
        if not path.is_file():
            continue
        counted_files += 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            total_lines += len(text.splitlines())
        except OSError:
            pass
    return {
        "file_count": counted_files,
        "total_lines": total_lines,
        "total_kb": round(total_bytes / 1024, 2),
    }

def _extract_tech_stack_from_analysis(analysis: Dict[str, Any]) -> str:
    if not _finalize_llm_enabled():
        return "Python"

    try:
        llm_service = get_llm_service()
        
        deepwiki_analysis = analysis.get("deepwiki_analysis", {}).get("analysis", "")
        if not _is_valid_deepwiki_content(deepwiki_analysis):
            return "Python"
        
        prompt = f"""Extract the main technology stack of this project (separated by commas):

{deepwiki_analysis[:800]}"""
        
        try:
            response = llm_service.generate_text(prompt, "Extract technology stack")
            if response and len(response.strip()) > 5:
                return response.strip()
        except:
            pass
        
        return "Python"
            
    except Exception as e:
        logger.warning(f"Tech stack extraction failed: {e}")
        return "Python"

def _generate_diff_report(state: Dict[str, Any]) -> str:
    repo = state.get("repository", {})
    repo_name = repo.get("name", "unknown")
    repo_url = repo.get("url", "")
    
    workflow_status = state.get('workflow_status', 'unknown')
    tests = state.get("tests", {})
    original_ok = tests.get("original", {}).get("passed", False)
    plugin_ok = _plugin_validation_matches_latest_run(state, tests.get("plugin"))
    
    standard_mcp_files = [
        "mcp_output/start_mcp.py",
        "mcp_output/mcp_plugin/__init__.py", 
        "mcp_output/mcp_plugin/mcp_service.py",
        "mcp_output/mcp_plugin/adapter.py",
        "mcp_output/mcp_plugin/main.py",
        "mcp_output/requirements.txt",
        "mcp_output/README_MCP.md",
        "mcp_output/tests_mcp/test_mcp_basic.py"
    ]
    
    analysis = state.get("analysis", {})
    project_type = _extract_project_type_from_analysis(analysis)
    main_features = _extract_features_from_analysis(analysis)
    unsupported_error = _unsupported_repository_error(state)
    unsupported_audit = _unsupported_audit_section(state)
    
    llm_analysis = analysis.get("llm_analysis", {})
    core_modules_list = [m.get("module", "") for m in llm_analysis.get("core_modules", [])]
    core_modules = ", ".join(core_modules_list) or "Unidentified"
    
    dependencies_list = llm_analysis.get("dependencies", {}).get("required", [])
    dependencies = ", ".join(dependencies_list) or "Unidentified"
    
    intrusiveness = "None"
    added_files_count = len(standard_mcp_files)
    modified_files_count = 0

    if _finalize_llm_enabled() and not unsupported_error:
        try:
            llm_service = get_llm_service()

            prompt = f"""Generate difference report for {repo_name} project:

Repository: {repo_name}
Project type: {project_type}
Main features: {main_features}
Time: {time.strftime('%Y-%m-%d %H:%M:%S')}
Intrusiveness: {intrusiveness}
New files: {added_files_count}
Modified files: {modified_files_count}
        Workflow status: {workflow_status}
        Test status: {'Passed' if plugin_ok else 'Failed'}

Please generate a professional Markdown format difference report, including project overview, difference analysis, technical analysis, recommendations and improvements, deployment information, future planning and other sections."""

            response = llm_service.generate_text(prompt, "Generate difference report")
            if response and len(response.strip()) > 200:
                return response.strip()
        except:
            pass
    
    if unsupported_error:
        status_label = "Unsupported (audited)"
        test_label = "No MCP service was generated; runtime/client validation was not applicable"
        quality_assessment = "Unsupported repository audit completed; no runnable MCP service was generated."
        unsupported_message = _unsupported_audit_text(
            unsupported_error.get("message"),
            "no supported generation target was found",
        )
        final_assessment = f"Code2MCP audited {repo_name} as unsupported: {unsupported_message}."
        recommendations_md = "\n".join(
            f"{index}. {recommendation}"
            for index, recommendation in enumerate(_unsupported_recommendations(state), start=1)
        )
        future_planning_md = "- Re-run Code2MCP after the audited unsupported reason is addressed.\n- Keep generated artifacts diagnostic until strict client validation succeeds."
    else:
        status_label = "Validated" if workflow_status == "validated" else "Generated (unvalidated)" if workflow_status == "generated" else "Failed"
        test_label = "MCP runtime/client validation passed" if plugin_ok else "MCP runtime/client validation failed or was not run"
        quality_assessment = (
            "Runtime/client validation passed with usable tool-call evidence"
            if plugin_ok
            else "Validation evidence is incomplete; do not treat generated files as production-ready"
        )
        final_assessment = (
            f"Based on runtime/client validation, the {repo_name} service is ready for controlled agent connection and further hardening."
            if plugin_ok
            else f"Code2MCP could not prove the {repo_name} service is ready. Continue review/fix/regenerate before connecting it to agents."
        )
        recommendations_md = f"""1. Strengthen exception handling, especially in service startup and critical function implementation.
2. Use data validation libraries for strict input validation to ensure data security.
3. Clarify dependency version ranges to ensure environment consistency.
4. Conduct regular security audits to identify and fix potential security vulnerabilities.
5. Consider splitting {repo_name} into independent microservices.
6. Develop RESTful API to enable {repo_name} functionality to be called over the network.
7. Use Docker to containerize {repo_name} services for easy deployment and scaling on cloud platforms.
8. Develop plugin mechanisms to allow users to customize components or integrate other libraries."""
        future_planning_md = f"""- Develop plugin mechanisms to allow users to customize components or integrate other libraries.
- Consider splitting {repo_name} into independent microservices.
- Promote in relevant communities, emphasizing ease of use and rich functionality.
- Collaborate with educational institutions as teaching tools."""

    md_content = f"""# {repo_name} Project Difference Report

## Project Overview

- **Repository Name**: [{repo_name}]({repo_url})
- **Project Type**: {project_type}
- **Main Features**: {main_features}

## Difference Analysis

### Timeline

- **Report Generation Time**: {time.strftime('%Y-%m-%d %H:%M:%S')}

### Changes

- **Intrusiveness**: {intrusiveness}
- **New Files**: {added_files_count}
- Modified Files: {modified_files_count}

### Project Status

        - **Analysis Status**: {status_label}
        - **Workflow Status**: {workflow_status}
        - **Test Results**: {test_label}

{unsupported_audit}

### New File Details

- **mcp_output/start_mcp.py** - MCP service startup entry
- **mcp_output/mcp_plugin/__init__.py** - Plugin package initialization file
- **mcp_output/mcp_plugin/mcp_service.py** - Core MCP service implementation
- **mcp_output/mcp_plugin/adapter.py** - Adapter implementation
- **mcp_output/mcp_plugin/main.py** - Plugin main entry
- **mcp_output/requirements.txt** - Dependency package list
- **mcp_output/README_MCP.md** - Service documentation
- **mcp_output/tests_mcp/test_mcp_basic.py** - Basic test file

## Technical Analysis

### Code Structure

- **Core Modules**: {core_modules}
- **Dependencies**: {dependencies}

### Risk Assessment

- **Import Feasibility**: 0.8
- **Intrusiveness Risk**: Low
- **Complexity**: {'Medium' if repo_name.lower() in ['textblob', 'sympy'] else 'Simple'}

### Code Quality

- **Overall Score**: 75
- **Issues Found**: 3
- **Quality Assessment**: {quality_assessment}

## Recommendations and Improvements

{recommendations_md}

## Deployment Information

- **Supported Platforms**: Linux, Windows, macOS
- **Python Versions**: 3.8, 3.9, 3.10, 3.11, 3.12
- **Deployment Methods**: Docker, pip, conda

## Future Planning

{future_planning_md}

{final_assessment}
"""
    
    return md_content

def _readme_status_block(summary: dict | None) -> str:
    summary = summary or {}
    execution = summary.get("execution", {}) if isinstance(summary.get("execution", {}), dict) else {}
    workflow_status = summary.get("workflow_status") or execution.get("workflow_status") or "unknown"
    validation_status = summary.get("validation_status") or execution.get("validation_status") or "unknown"
    verified = bool(summary.get("verified") if "verified" in summary else execution.get("verified"))
    tests = summary.get("tests", {}) if isinstance(summary.get("tests", {}), dict) else {}
    mcp_plugin = tests.get("mcp_plugin", {}) if isinstance(tests.get("mcp_plugin", {}), dict) else {}
    details = mcp_plugin.get("details", {}) if isinstance(mcp_plugin.get("details", {}), dict) else {}
    tool_count = details.get("tool_count", mcp_plugin.get("tool_count", "unknown"))

    if workflow_status == "validated" and verified:
        guidance = "This service passed runtime smoke tests and FastMCP client validation."
    elif workflow_status == "generated":
        guidance = "Files were generated, but runtime validation was skipped. Do not connect this service to production agents until the default workflow reaches `validated`."
    elif workflow_status == "failed":
        guidance = "Code2MCP could not prove this service runs. Treat the generated files as failed diagnostic artifacts."
    else:
        guidance = "Validation evidence is unavailable or incomplete. Treat this service as unverified until `workflow_summary.json` reports `validated`."

    return (
        "## Validation Status\n\n"
        f"- Workflow status: `{workflow_status}`\n"
        f"- Validation status: `{validation_status}`\n"
        f"- Verified: `{str(verified).lower()}`\n"
        f"- Registered tool count: `{tool_count}`\n\n"
        f"{guidance}\n"
    )


def _generate_readme_mcp(analysis: dict, summary: dict | None = None) -> str:
    status_block = _readme_status_block(summary)
    if not _finalize_llm_enabled():
        return f"# MCP (Model Context Protocol) Service Documentation\n\n{status_block}\n## Project Introduction\nThis service exposes repository functions as MCP tools only when validation succeeds.\n\n## Installation Method\nInstall the generated requirements and run `start_mcp.py` from the generated `mcp_output` directory.\n\n## Quick Start\nUse `agent_connect.html` or `agent_connection.json` to copy the configuration for your MCP client after validation passes.\n\n## Available Tools and Endpoints\nSee `workflow_summary.json` for the exact generated and validated tool list.\n\n## Common Issues and Notes\n- Verify the virtual environment Python path.\n- Some repository functions may require project-specific input files or data.\n- A service is production-ready only when the workflow status is `validated` and `verified` is `true`.\n\n## Reference Documentation\n- Model Context Protocol\n- FastMCP"

    try:
        llm_service = get_llm_service()
        prompt = f"""Based on the following analysis results, generate a concise, practical, developer-oriented MCP (Model Context Protocol) service README in English:

Workflow summary:
{summary or {}}

Analysis:
{analysis}

Content should include:
1. Project Introduction (brief description of service purpose and main functions)
2. Installation Method (dependencies, pip commands, etc.)
3. Quick Start (code examples, how to call main functions)
4. Available Tools and Endpoints List (brief description of each endpoint)
5. Common Issues and Notes (dependencies, environment, performance, etc.)
6. Reference Links or Documentation

Please output Markdown content directly, change all "plugins" to "services", add parentheses (Model Context Protocol) when "MCP" appears, use only English, no code block markers."""
        response = llm_service.generate_text(prompt, "Generate English README")
        if response and len(response.strip()) > 100:
            return response.strip()
    except:
        pass
    return f"# MCP (Model Context Protocol) Service Documentation\n\n{status_block}\n## Project Introduction\nThis generated service exposes repository functions as MCP tools when runtime validation succeeds.\n\n## Installation Method\nInstall the generated requirements and run `start_mcp.py` from the generated `mcp_output` directory.\n\n## Quick Start\nUse `agent_connect.html` or `agent_connection.json` to copy the configuration for your MCP client after validation passes.\n\n## Available Tools and Endpoints\nSee `workflow_summary.json` for the exact generated and validated tool list.\n\n## Common Issues and Notes\n- Some tools may require project-specific input files or data.\n- A service is production-ready only when the workflow status is `validated` and `verified` is `true`.\n\n## Reference Documentation\n- Model Context Protocol\n- FastMCP"


def _plugin_client_validation(plugin_result: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(plugin_result, dict):
        return {}
    client_validation = plugin_result.get("client_validation")
    if isinstance(client_validation, dict):
        return client_validation
    details = plugin_result.get("details")
    if isinstance(details, dict) and isinstance(details.get("client_validation"), dict):
        return details["client_validation"]
    return {}


def _plugin_semantic_success_count(plugin_result: Dict[str, Any] | None) -> int:
    return _client_semantic_success_count(_plugin_client_validation(plugin_result))


def _client_semantic_success_count(client_validation: Dict[str, Any] | None) -> int:
    calls = client_validation.get("calls") if isinstance(client_validation, dict) else []
    if not isinstance(calls, list):
        return 0
    return sum(
        1
        for call in calls
        if isinstance(call, dict)
        and call.get("passed") is True
        and call.get("is_error") is not True
        and call.get("semantic_success") is True
    )


def _plugin_meaningful_success_count(plugin_result: Dict[str, Any] | None) -> int:
    return _client_meaningful_success_count(_plugin_client_validation(plugin_result))


def _client_meaningful_success_count(client_validation: Dict[str, Any] | None) -> int:
    calls = client_validation.get("calls") if isinstance(client_validation, dict) else []
    if not isinstance(calls, list):
        return 0
    return sum(
        1
        for call in calls
        if isinstance(call, dict)
        and call.get("passed") is True
        and call.get("is_error") is not True
        and call.get("semantic_success") is True
        and call.get("semantic_evidence") is True
    )


def _client_validation_has_runtime_evidence(client_validation: Dict[str, Any] | None) -> bool:
    tool_count = client_validation.get("tool_count") if isinstance(client_validation, dict) else None
    return bool(
        isinstance(client_validation, dict)
        and client_validation.get("passed") is True
        and isinstance(tool_count, int)
        and not isinstance(tool_count, bool)
        and tool_count > 0
        and _client_semantic_success_count(client_validation) > 0
        and _client_meaningful_success_count(client_validation) > 0
    )


def _plugin_validation_passed(plugin_result: Dict[str, Any] | None) -> bool:
    client_validation = _plugin_client_validation(plugin_result)
    return bool(
        isinstance(plugin_result, dict)
        and plugin_result.get("passed") is True
        and _client_validation_has_runtime_evidence(client_validation)
    )


def _plugin_validation_matches_latest_run(state: Dict[str, Any], plugin_result: Dict[str, Any] | None) -> bool:
    if not _plugin_validation_passed(plugin_result):
        return False
    run_result = state.get("run_result")
    if not isinstance(run_result, dict) or not run_result:
        return True
    if run_result.get("success") is not True:
        return False
    run_client_validation = run_result.get("client_validation")
    if not _client_validation_has_runtime_evidence(run_client_validation):
        return False
    plugin_attempt = plugin_result.get("attempt") if isinstance(plugin_result, dict) else None
    run_attempt = run_result.get("attempt")
    if run_attempt is not None and plugin_attempt is None:
        return False
    if plugin_attempt is not None and run_attempt is not None and plugin_attempt != run_attempt:
        return False
    return True


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def _has_unsupported_repository_error(errors: list) -> bool:
    return any(isinstance(error, dict) and error.get("type") == "UnsupportedRepository" for error in errors)


def _unsupported_repository_error(source: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    for error in _as_list(source.get("errors", [])):
        if isinstance(error, dict) and error.get("type") == "UnsupportedRepository":
            return error
    summary = source.get("summary")
    if isinstance(summary, dict):
        return _unsupported_repository_error(summary)
    return None


def _unsupported_audit_text(value: Any, default: str = "") -> str:
    if value is None or value == "":
        value = default
    return redact_sensitive_text(value)


def _unsupported_audit_section(source: Dict[str, Any] | None) -> str:
    error = _unsupported_repository_error(source)
    if not error:
        return ""

    details = error.get("details", {}) if isinstance(error.get("details", {}), dict) else {}
    lines = [
        "## Unsupported Repository Audit",
        "",
        f"- Error: {_unsupported_audit_text(error.get('message'), 'Unsupported repository')}",
        f"- Likely reason: `{_unsupported_audit_text(details.get('likely_reason'), 'unknown')}`",
        f"- Project type: `{_unsupported_audit_text(details.get('project_type'), 'unknown')}`",
        f"- Stage: `{_unsupported_audit_text(details.get('stage'), 'unknown')}`",
        (
            "- Original candidates: "
            f"{details.get('original_core_module_count', details.get('core_module_count', 0))} modules, "
            f"{details.get('original_function_count', 0)} functions, "
            f"{details.get('original_class_count', 0)} classes"
        ),
        (
            "- Filtered candidates: "
            f"{details.get('filtered_core_module_count', 0)} modules, "
            f"{details.get('filtered_function_count', 0)} functions, "
            f"{details.get('filtered_class_count', 0)} classes"
        ),
        f"- Action taken: `{_unsupported_audit_text(error.get('action_taken'), 'unknown')}`",
    ]

    rejected_targets = details.get("rejected_targets", [])
    if isinstance(rejected_targets, list) and rejected_targets:
        lines.extend(["", "### Rejected Candidate Targets"])
        for target in rejected_targets[:10]:
            if not isinstance(target, dict):
                continue
            module = _unsupported_audit_text(target.get("module")).strip()
            name = _unsupported_audit_text(target.get("name")).strip()
            symbol = f"{module}.{name}" if module and name else module or name or "unknown"
            file_path = _unsupported_audit_text(target.get("file_path"), "unknown path").strip()
            reasons = target.get("reasons", [])
            reason_text = (
                "; ".join(_unsupported_audit_text(reason) for reason in reasons)
                if isinstance(reasons, list)
                else _unsupported_audit_text(reasons)
            )
            kind = _unsupported_audit_text(target.get("kind"), "target")
            lines.append(f"- `{kind}` `{symbol}` ({file_path}): {reason_text or 'no reason recorded'}")
        rejected_count = details.get("rejected_target_count")
        if isinstance(rejected_count, int) and rejected_count > len(rejected_targets[:10]):
            lines.append(f"- {rejected_count - len(rejected_targets[:10])} additional rejected targets omitted from this report.")
    else:
        lines.extend([
            "",
            "### Rejected Candidate Targets",
            "- No rejected AST-backed public functions/classes were recorded; no supported build target reached generation.",
        ])

    return "\n".join(lines)


def _unsupported_recommendations(source: Dict[str, Any] | None) -> list:
    error = _unsupported_repository_error(source)
    if not error:
        return []
    details = error.get("details", {}) if isinstance(error.get("details", {}), dict) else {}
    project_type = _unsupported_audit_text(details.get("project_type"), "this project type")
    likely_reason = _unsupported_audit_text(details.get("likely_reason"), "unsupported_repository")
    recommendations = [
        "Keep this run classified as `unsupported_audited` until a safe public API target exists.",
        f"Address the audited reason `{likely_reason}` before attempting runtime validation.",
    ]
    if likely_reason == "unsupported_project_type":
        recommendations.append(f"Add Code2MCP generator support for `{project_type}` or provide a supported Python/C++ wrapper layer.")
    else:
        recommendations.append("Expose side-effect-free functions/classes with explicit parameters and avoid listeners, file writes, stdin, or control-plane behavior.")
    return recommendations


def _prepare_agent_connection(state: Dict[str, Any], validation_status: str, verified: bool) -> Dict[str, Any]:
    repo = state.get("repository", {})
    repo_root = repo.get("local_paths", {}).get("repo_root")
    if not repo_root:
        return {}

    start_mcp = Path(repo_root) / "mcp_output" / "start_mcp.py"
    if not start_mcp.exists():
        return {}

    tests = state.get("tests", {})
    plugin_result = tests.get("plugin") or {}
    client_validation = _plugin_client_validation(plugin_result)
    env_info = state.get("env", {}) or {}
    exec_prefix = env_info.get("exec_prefix") if isinstance(env_info, dict) else None
    python_executable = exec_prefix[0] if isinstance(exec_prefix, list) and exec_prefix else None
    validation = {
        "workflow_status": state.get("workflow_status"),
        "validation_status": validation_status,
        "verified": verified,
        "mcp_test_passed": bool(plugin_result.get("passed")),
        "client_validation_passed": bool(client_validation.get("passed")),
        "client_call_count": len(client_validation.get("calls", [])) if isinstance(client_validation.get("calls"), list) else 0,
        "client_semantic_success_count": _plugin_semantic_success_count(plugin_result),
        "client_meaningful_success_count": _plugin_meaningful_success_count(plugin_result),
        "warnings": client_validation.get("warnings", []) if isinstance(client_validation.get("warnings"), list) else [],
        "tool_count": client_validation.get("tool_count"),
    }

    try:
        profile = build_connection_profile(
            repo_root,
            server_name=repo.get("name"),
            python_executable=python_executable,
            validation=validation,
        )
        files = write_connection_files(profile, repo_root)
        return {
            "server_name": profile["server_name"],
            "profile_path": files["profile"],
            "generic_config_path": files["generic_config"],
            "cursor_config_snippet_path": files["cursor_config_snippet"],
            "connection_guide_html": files["connection_guide_html"],
            "cursor_config_path": profile["clients"]["cursor"]["config_path"],
            "local_transport": "stdio",
            "local_server": profile["local"]["server"],
            "quick_commands": profile["quick_commands"],
            "write_requires_validated": True,
        }
    except QuickConnectError as exc:
        state.setdefault("warnings", []).append(f"Agent connection profile was not generated: {exc}")
        return {}


def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    tests = state.get("tests", {})
    original_ok = tests.get("original", {}).get("passed", False)
    plugin_result = tests.get("plugin")
    plugin_ok = _plugin_validation_matches_latest_run(state, plugin_result)
    generate_only = bool((state.get("options") or {}).get("generate_only", False))
    
    repo = state.get("repository", {})
    repo_url = repo.get("url", "")
    repo_name = repo.get("name") or (derive_repo_name(repo_url) if repo_url else "unknown")
    
    analysis = state.get("analysis", {})
    plugin = state.get("plugin", {})
    historical_errors = _as_list(state.get("errors", []))
    unsupported_audited = _has_unsupported_repository_error(historical_errors)
    files_created = list(plugin.get("files", {}).keys()) if plugin.get("files") else []
    generated_ok = bool(files_created)
    generated_tools = _extract_generated_tools(plugin, analysis)
    generated_metrics = _generated_file_metrics(plugin)
    tool_endpoint_count = len(generated_tools)
    plugin_test_tool_count = tests.get("plugin", {}).get("tool_count")
    if not tool_endpoint_count and isinstance(plugin_test_tool_count, int):
        tool_endpoint_count = plugin_test_tool_count
    original_test_details = tests.get("original", {}) if isinstance(tests.get("original", {}), dict) else {}
    original_test_coverage = original_test_details.get("coverage") or original_test_details.get("test_coverage") or "not measured"
    project_description = _extract_project_type_from_analysis(analysis)
    project_features = _extract_features_from_analysis(analysis)
    tech_stack = _extract_tech_stack_from_analysis(analysis)
    recommendations = _generate_recommendations(state)

    if plugin_ok:
        state["status"] = "validated"
        state["workflow_status"] = "validated"
        validation_status = "validated"
        verified = True
        logger.info(f"Workflow validated successfully! {repo_name} has been converted to a runnable MCP service")
    elif generate_only and generated_ok:
        state["status"] = "generated"
        state["workflow_status"] = "generated"
        validation_status = "generated_unvalidated"
        verified = False
        logger.warning(f"Workflow generated MCP files for {repo_name}, but runtime validation was skipped")
    else:
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        validation_status = "unsupported_audited" if unsupported_audited else "failed"
        verified = False
        logger.error(f"Workflow execution failed! {repo_name} conversion failed")
    state["validation_status"] = validation_status

    unresolved_errors = [] if plugin_ok else historical_errors
    recovered_errors = historical_errors if plugin_ok else _as_list(state.get("recovered_errors", []))
    
    workflow_summary = {
        "status": state["status"],
        "workflow_status": state["workflow_status"],
        "validation_status": validation_status,
        "verified": verified,
        "success": state["workflow_status"] == "validated" and verified,
        "repository": {
            "name": repo_name,
            "url": repo_url,
            "local_path": repo.get("local_paths", {}).get("repo_root", ""),
            "description": project_description,
            "features": project_features,
            "tech_stack": tech_stack,
            "stars": analysis.get("deepwiki_analysis", {}).get("stars", 0),
            "forks": analysis.get("deepwiki_analysis", {}).get("forks", 0),
            "language": _repository_language_from_analysis(analysis),
            "last_updated": analysis.get("deepwiki_analysis", {}).get("last_updated", ""),
            "complexity": analysis.get("risk", {}).get("complexity", "medium"),
            "intrusiveness_risk": analysis.get("risk", {}).get("intrusiveness_risk", "low")
        },
        "execution": {
            "start_time": state.get("workflow_start_time"),
            "end_time": time.time(),
            "duration": time.time() - (state.get("workflow_start_time", time.time())),
            "status": state["status"],
            "workflow_status": state["workflow_status"],
            "validation_status": validation_status,
            "verified": verified,
            "generate_only": generate_only,
            "nodes_executed": ["download", "analysis", "env", "generate", "run", "review", "finalize"],
            "total_files_processed": _analysis_file_count(analysis),
            "environment_type": state.get("env", {}).get("type", "unknown"),
            "llm_calls": state.get("llm_statistics", {}).get("total_calls", 0),
            "deepwiki_calls": state.get("deepwiki_statistics", {}).get("total_calls", 0),
            "unresolved_error_count": len(unresolved_errors),
            "recovered_error_count": len(recovered_errors)
        },
        "tests": {
            "original_project": {
                "passed": original_ok,
                "details": original_test_details,
                "test_coverage": original_test_coverage,
                "execution_time": original_test_details.get("execution_time", 0),
                "test_files": original_test_details.get("test_files", [])
            },
            "mcp_plugin": {
                "passed": plugin_ok,
                "details": tests.get("plugin", {}),
                "service_health": "healthy" if plugin_ok else "unhealthy",
                "startup_time": tests.get("plugin", {}).get("startup_time", 0),
                "transport_mode": tests.get("plugin", {}).get("transport", "stdio"),
                "fastmcp_version": tests.get("plugin", {}).get("fastmcp_version", "unknown"),
                "mcp_version": tests.get("plugin", {}).get("mcp_version", "unknown")
            }
        },
        "analysis": {
            "structure": analysis.get("structure", {}),
            "dependencies": analysis.get("dependencies", {}),
            "entry_points": analysis.get("entry_points", {}),
            "risk_assessment": analysis.get("risk", {}),
            "deepwiki_analysis": analysis.get("deepwiki_analysis", {}),
            "code_complexity": {
                "cyclomatic_complexity": analysis.get("complexity", {}).get("cyclomatic", "medium"),
                "cognitive_complexity": analysis.get("complexity", {}).get("cognitive", "medium"),
                "maintainability_index": analysis.get("complexity", {}).get("maintainability", 75)
            },
            "security_analysis": {
                "vulnerabilities_found": analysis.get("security", {}).get("vulnerabilities", 0),
                "security_score": analysis.get("security", {}).get("score", 85),
                "recommendations": analysis.get("security", {}).get("recommendations", [])
            }
        },
        "plugin_generation": {
            "files_created": files_created,
            "main_entry": plugin.get("main_entry", ""),
            "requirements": plugin.get("requirements", []),
            "readme_path": plugin.get("readme_path", ""),
            "adapter_mode": plugin.get("adapter_mode", "import"),
            "total_lines_of_code": generated_metrics["total_lines"],
            "generated_files_size": generated_metrics["total_kb"],
            "tool_endpoints": tool_endpoint_count,
            "supported_features": _extract_features_from_analysis(analysis).split(", "),
            "generated_tools": generated_tools
        },
        "code_review": state.get("code_review", {}),
        "errors": unresolved_errors,
        "recovered_errors": recovered_errors,
        "warnings": state.get("warnings", []),
        "recommendations": recommendations,
        "performance_metrics": {
            "memory_usage_mb": state.get("performance", {}).get("memory_usage", 0),
            "cpu_usage_percent": state.get("performance", {}).get("cpu_usage", 0),
            "response_time_ms": state.get("performance", {}).get("response_time", 0),
            "throughput_requests_per_second": state.get("performance", {}).get("throughput", 0)
        },
        "deployment_info": {
            "supported_platforms": ["Linux", "Windows", "macOS"],
            "python_versions": ["3.10", "3.11", "3.12", "3.13"],
            "deployment_methods": ["Docker", "pip", "conda"],
            "monitoring_support": "basic_healthcheck",
            "logging_configuration": "structured"
        }
    }

    agent_connection = _prepare_agent_connection(state, validation_status, verified)
    if agent_connection:
        workflow_summary["agent_connection"] = agent_connection
        state["agent_connection"] = agent_connection
    
    if generate_only:
        logger.info("Generate-only mode: using deterministic final summary without extra LLM report calls")
        llm_analysis = _default_llm_analysis(workflow_summary)
    else:
        logger.info(_finalize_summary_log_message())
        llm_analysis = _generate_llm_summary(state, workflow_summary)
    workflow_summary["execution_analysis"] = llm_analysis.get("execution_analysis", {})
    workflow_summary["technical_quality"] = llm_analysis.get("technical_quality", {})
    
    technical_report = (
        _default_technical_report(state, workflow_summary, llm_analysis)
        if generate_only
        else _generate_technical_report(state, workflow_summary, llm_analysis)
    )
    
    state["summary"] = workflow_summary
    state["technical_report"] = technical_report
    
    _save_final_reports(state, workflow_summary, technical_report)
    
    if state.get("workflow_status") == "validated":
        deploy_target = (state.get("options") or {}).get("deploy_target", "local")
        try:
            repo = state.get("repository", {})
            repo_root = repo.get("local_paths", {}).get("repo_root")
            repo_name = repo.get("name")
            auto_deploy_hf = os.getenv("AUTO_DEPLOY_HF", "false").lower() == "true"
            if repo_root and (deploy_target == "hf" or auto_deploy_hf):
                do_push = (os.getenv("AUTO_DEPLOY_HF", "false").lower() == "true") and (os.getenv("HF_PUSH", "false").lower() == "true")
                result = deploy_to_huggingface(repo_root, push=do_push)
                if result.get("success"):
                    state["huggingface_deployment"] = result
                    if do_push and result.get("url"):
                        logger.info(f"HuggingFace deployment successful: {result.get('url')}")
                        auto_connect = os.getenv("AUTO_CONNECT_CLIENT", "").lower()
                        if auto_connect:
                            state["auto_connect"] = _connect_mcp_client(auto_connect, repo_name, result.get("url"), repo_root)
                else:
                    logger.warning(f"HuggingFace deployment failed: {result.get('error')}")
        except Exception as e:
            logger.warning(f"Deployment scaffolding/push step failed: {e}")

        try:
            repo = state.get("repository", {})
            repo_root = repo.get("local_paths", {}).get("repo_root")
            if repo_root:
                deploy_target = (state.get("options") or {}).get("deploy_target", "local")
                generate_only = bool((state.get("options") or {}).get("generate_only"))
                autorun = False if deploy_target == "hf" or generate_only else os.getenv("CODE2MCP_LOCAL_AUTORUN", "false").lower() == "true"
                create_and_run_local_scripts(repo_root, autorun=autorun)
        except Exception as e:
            logger.warning(f"Generate/run local scripts failed: {e}")
    
    logger.info(f"Workflow summary generated, status: {state['status']}")
    if unresolved_errors:
        logger.warning(f"Found {len(unresolved_errors)} unresolved errors, please check logs")
    elif recovered_errors:
        logger.info(f"Recovered from {len(recovered_errors)} earlier errors during validation")
    
    return state

def _generate_recommendations(state: Dict[str, Any]) -> list:
    unsupported_recommendations = _unsupported_recommendations(state)
    if unsupported_recommendations:
        return unsupported_recommendations

    if not _finalize_llm_enabled():
        return [
            "Run client-level MCP validation against representative tool calls",
            "Review tools that require project-specific files or datasets",
            "Document safe example inputs for generated tools",
        ]

    try:
        llm_service = get_llm_service()
        
        prompt = f"""Based on the following project status, generate improvement suggestions:

Test status: {state.get('tests', {})}
Analysis results: {state.get('analysis', {})}
Plugin information: {state.get('plugin', {})}
Code review: {state.get('code_review', {})}
Performance metrics: {state.get('performance', {})}

Please return the suggestion list directly, separated by commas"""
        
        response = llm_service.generate_text(prompt, "Generate improvement suggestions")
        if response and len(response.strip()) > 5:
            return [rec.strip() for rec in response.split(',')]
    except:
        pass
    
    return ["Workflow execution smooth, recommend further functional testing"]

def _connect_mcp_client(client_type: str, mcp_name: str, mcp_url: str, repo_root: str):
    normalized_client = (client_type or "").lower().replace("_", "-")
    write_supported = normalized_client in {"cursor", "claude", "claude-code"}
    try:
        remote_probe_timeout = float(os.getenv("CODE2MCP_REMOTE_PROBE_TIMEOUT", "30"))
    except ValueError:
        remote_probe_timeout = 30.0
    try:
        result = connect_agent(
            repo_root,
            client=client_type,
            server_name=mcp_name,
            remote_url=mcp_url,
            write=write_supported,
            remote=True,
            probe_remote=True,
            remote_probe_timeout=remote_probe_timeout,
        )
        if write_supported:
            logger.info(f"Auto-connected {mcp_name} to {client_type}")
        else:
            logger.info(f"Prepared {client_type} connection payload for {mcp_name}")
        return {
            "success": True,
            "client": client_type,
            "write_attempted": write_supported,
            "mode": "installed" if write_supported else "copy_config",
            "result": result.get("connection", {}),
            "files": result.get("files", {}),
        }
    except QuickConnectError as e:
        message = redact_sensitive_text(e)
        logger.warning(f"Auto-connect to {client_type} failed: {message}")
        return {"success": False, "client": client_type, "error": message}
    except Exception as e:
        message = redact_sensitive_text(e)
        logger.warning(f"Auto-connect to {client_type} failed: {message}")
        return {"success": False, "client": client_type, "error": message}


def _save_final_reports(state: Dict[str, Any], summary: Dict[str, Any], technical_report: str, generate_only: bool = False):
    repo = state.get("repository", {})
    repo_root = repo.get("local_paths", {}).get("repo_root")
    generate_only = bool((state.get("options") or {}).get("generate_only", generate_only))
    
    if not repo_root or not os.path.isdir(repo_root):
        return
    
    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    os.makedirs(mcp_output_dir, exist_ok=True)
    
    try:
        summary_path = os.path.join(mcp_output_dir, "workflow_summary.json")
        write_file(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))

        if generate_only:
            diff_report_path = os.path.join(mcp_output_dir, "diff_report.md")
            write_file(diff_report_path, technical_report)
            return
        
        diff_report_content = _generate_diff_report(state)
        diff_report_path = os.path.join(mcp_output_dir, "diff_report.md")
        write_file(diff_report_path, diff_report_content)
        
        readme_mcp_content = _generate_readme_mcp(state.get("analysis", {}), summary)
        readme_mcp_path = os.path.join(mcp_output_dir, "README_MCP.md")
        write_file(readme_mcp_path, readme_mcp_content)

        _mirror_reports_to_output_dir(
            state,
            summary,
            technical_report,
            {
                "workflow_summary": summary_path,
                "diff_report": diff_report_path,
                "readme_mcp": readme_mcp_path,
                "agent_connection": os.path.join(mcp_output_dir, "agent_connection.json"),
                "agent_connect_html": os.path.join(mcp_output_dir, "agent_connect.html"),
                "agent_mcp_config": os.path.join(mcp_output_dir, "agent_mcp_config.json"),
                "cursor_mcp_config": os.path.join(mcp_output_dir, "cursor_mcp_config.json"),
            },
        )
        
    except Exception as e:
        logger.warning(f"Failed to save final reports: {e}")


def _mirror_reports_to_output_dir(
    state: Dict[str, Any],
    summary: Dict[str, Any],
    technical_report: str,
    artifacts: Dict[str, str],
) -> None:
    output_dir = (state.get("options") or {}).get("output_dir")
    repo = state.get("repository", {})
    repo_name = repo.get("name") or summary.get("repository", {}).get("name") or "code2mcp-output"
    repo_root = repo.get("local_paths", {}).get("repo_root", "")
    if not output_dir:
        return

    target_dir = Path(output_dir).expanduser().resolve() / re.sub(r"[^A-Za-z0-9_.-]+", "-", str(repo_name)).strip(".-")
    target_dir.mkdir(parents=True, exist_ok=True)

    mirrored: Dict[str, str] = {}
    for label, source in artifacts.items():
        if not source or not os.path.isfile(source):
            continue
        destination = target_dir / Path(source).name
        shutil.copy2(source, destination)
        mirrored[label] = str(destination)

    technical_report_path = target_dir / "technical_report.md"
    technical_report_path.write_text(technical_report or "", encoding="utf-8")
    mirrored["technical_report"] = str(technical_report_path)

    index = {
        "repository": repo_name,
        "workspace_repo_root": repo_root,
        "workspace_mcp_output": str(Path(repo_root) / "mcp_output") if repo_root else "",
        "workflow_status": summary.get("workflow_status") or summary.get("execution", {}).get("workflow_status"),
        "validation_status": summary.get("validation_status") or summary.get("execution", {}).get("validation_status"),
        "verified": bool(summary.get("verified") if "verified" in summary else summary.get("execution", {}).get("verified")),
        "artifacts": mirrored,
    }
    index_path = target_dir / "artifact_index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
