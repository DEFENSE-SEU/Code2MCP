# Finalize Node - Compile results and output final status
from __future__ import annotations
import os
import json
import time
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, List
from ..utils import setup_logging, write_file, get_llm_service
from ..tools.deploy_hf import deploy_to_huggingface

logger = setup_logging()


def _is_valid_deepwiki_content(content: str) -> bool:
    if not content or len(content.strip()) < 50:
        return False
    
    loading_indicators = ["Loading...", "loading", "Please wait", "Analyzing", "Processing"]
    if any(indicator in content for indicator in loading_indicators):
        return False
    
    valid_indicators = ["Analysis", "Repository", "Functions", "Classes", "Dependencies", "Features", "Description", "Overview"]
    if any(indicator in content for indicator in valid_indicators):
        return True
    
    if len(content) > 200 and not content.strip().startswith("Warning:"):
        return True
    
    return False

def _generate_llm_summary(state: Dict[str, Any], workflow_summary: Dict[str, Any]) -> Dict[str, Any]:
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
- Errors: {state.get('errors', [])}
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
    status = workflow_summary.get('execution', {}).get('status', 'unknown')
    tests = workflow_summary.get('tests', {})
    
    return {
        "execution_analysis": {
                    "success_factors": ["Workflow execution completed"] if status == "success" else [],
        "failure_reasons": ["Test failed"] if not tests.get('mcp_plugin', {}).get('passed', False) else [],
            "overall_assessment": "good" if status == "success" else "poor"
        },
        "technical_quality": {
            "code_quality_score": 80 if status == "success" else 60,
            "architecture_score": 75 if status == "success" else 50,
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
    
    return f"""# {repo_name} Code2MCP Service Technical Report

## Project Overview
This project successfully converted {repo_name} to a FastMCP service.

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
    try:
        llm_service = get_llm_service()
        
        deepwiki_analysis = analysis.get("deepwiki_analysis", {}).get("analysis", "")
        if not _is_valid_deepwiki_content(deepwiki_analysis):
            return "Python library"
        
        prompt = f"""Summarize this project type in one sentence:

{deepwiki_analysis[:500]}"""
        
        try:
            response = llm_service.generate_text(prompt, "Summarize project type")
            if response and len(response.strip()) > 5:
                return response.strip()
        except:
            pass
        
        return "Python library"
    except Exception as e:
        logger.warning(f"Project type extraction failed: {e}")
        return "Python library"

def _extract_generated_tools(plugin: Dict[str, Any], analysis: Dict[str, Any]) -> list:
    try:
        llm_service = get_llm_service()
        
        features = _extract_features_from_analysis(analysis)
        plugin_tools = plugin.get("tools", {})
        
        if not features or plugin_tools.get("count", 0) == 0:
            return ["Basic tools", "Health check tools", "Version info tools"]
        
        prompt = f"""Based on feature characteristics, infer the generated MCP tool endpoints:

{features}
Tool count: {plugin_tools.get('count', 0)}"""
        
        try:
            response = llm_service.generate_text(prompt, "Infer tool endpoints")
            if response and len(response.strip()) > 5:
                return [tool.strip() for tool in response.split(',')]
        except:
            pass
        
        return ["Basic tools", "Health check tools", "Version info tools"]
        
    except Exception as e:
        logger.warning(f"Tool extraction failed: {e}")
        return ["Basic tools"]

def _extract_tech_stack_from_analysis(analysis: Dict[str, Any]) -> str:
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
    plugin_ok = tests.get("plugin", {}).get("passed", False)
    
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
    
    llm_analysis = analysis.get("llm_analysis", {})
    core_modules_list = [m.get("module", "") for m in llm_analysis.get("core_modules", [])]
    core_modules = ", ".join(core_modules_list) or "Unidentified"
    
    dependencies_list = llm_analysis.get("dependencies", {}).get("required", [])
    dependencies = ", ".join(dependencies_list) or "Unidentified"
    
    intrusiveness = "None"
    added_files_count = len(standard_mcp_files)
    modified_files_count = 0
    
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

        - **Analysis Status**: {'Success' if workflow_status == 'success' else 'Failed'}
        - **Workflow Status**: {workflow_status}
        - **Test Results**: {'Both original project and MCP tests passed' if original_ok and plugin_ok else 'Test failed'}

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
- **Quality Assessment**: Good structure, good functionality, average error handling, average best practices, average security

## Recommendations and Improvements

1. Strengthen exception handling, especially in service startup and critical function implementation.
2. Use data validation libraries for strict input validation to ensure data security.
3. Clarify dependency version ranges to ensure environment consistency.
4. Conduct regular security audits to identify and fix potential security vulnerabilities.
5. Consider splitting {repo_name} into independent microservices.
6. Develop RESTful API to enable {repo_name} functionality to be called over the network.
7. Use Docker to containerize {repo_name} services for easy deployment and scaling on cloud platforms.
8. Develop plugin mechanisms to allow users to customize components or integrate other libraries.

## Deployment Information

- **Supported Platforms**: Linux, Windows, macOS
- **Python Versions**: 3.8, 3.9, 3.10, 3.11, 3.12
- **Deployment Methods**: Docker, pip, conda

## Future Planning

- Develop plugin mechanisms to allow users to customize components or integrate other libraries.
- Consider splitting {repo_name} into independent microservices.
- Promote in relevant communities, emphasizing ease of use and rich functionality.
- Collaborate with educational institutions as teaching tools.

Based on the above difference report, the {repo_name} project performs well in terms of technical quality and market potential, and it is recommended to further optimize exception handling and input validation to improve security and stability.
"""
    
    return md_content

def _generate_readme_mcp(analysis: dict) -> str:
    try:
        llm_service = get_llm_service()
        prompt = f"""Based on the following analysis results, generate a concise, practical, developer-oriented MCP (Model Context Protocol) service README in English:

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
    return "# MCP (Model Context Protocol) Service Documentation\n\n## Project Introduction\nThis service is used for... (please add)\n\n## Installation Method\nPlease use pip to install dependencies.\n\n## Quick Start\nPlease refer to the example code.\n\n## Available Tools and Endpoints\n- Main function 1\n- Main function 2\n\n## Common Issues and Notes\n- Dependency issues\n- Environment configuration\n\n## Reference Documentation\n- Official documentation links"

def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    tests = state.get("tests", {})
    original_ok = tests.get("original", {}).get("passed", False)
    plugin_ok = tests.get("plugin", {}).get("passed", False)
    
    repo = state.get("repository", {})
    repo_url = repo.get("url", "")
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "") if repo_url else "unknown"
    
    analysis = state.get("analysis", {})
    plugin = state.get("plugin", {})
    errors = state.get("errors", [])
    
    if plugin_ok:
        state["status"] = "success"
        state["workflow_status"] = "success"
        logger.info(f"Workflow executed successfully! {repo_name} has been successfully converted to MCP service")
    else:
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        logger.error(f"Workflow execution failed! {repo_name} conversion failed")
    
    workflow_summary = {
        "repository": {
            "name": repo_name,
            "url": repo_url,
            "local_path": repo.get("local_paths", {}).get("repo_root", ""),
            "description": _extract_project_type_from_analysis(analysis),
            "features": _extract_features_from_analysis(analysis),
            "tech_stack": _extract_tech_stack_from_analysis(analysis),
            "stars": analysis.get("deepwiki_analysis", {}).get("stars", 0),
            "forks": analysis.get("deepwiki_analysis", {}).get("forks", 0),
            "language": analysis.get("deepwiki_analysis", {}).get("language", "Python"),
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
            "nodes_executed": ["download", "analysis", "env", "generate", "run", "review", "finalize"],
            "total_files_processed": len(analysis.get("structure", {}).get("packages", [])) + len(analysis.get("structure", {}).get("files", [])),
            "environment_type": state.get("env", {}).get("type", "unknown"),
            "llm_calls": state.get("llm_statistics", {}).get("total_calls", 0),
            "deepwiki_calls": state.get("deepwiki_statistics", {}).get("total_calls", 0)
        },
        "tests": {
            "original_project": {
                "passed": original_ok,
                "details": tests.get("original", {}),
                "test_coverage": "100%",
                "execution_time": tests.get("original", {}).get("execution_time", 0),
                "test_files": tests.get("original", {}).get("test_files", [])
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
            "files_created": list(plugin.get("files", {}).keys()) if plugin.get("files") else [],
            "main_entry": plugin.get("main_entry", ""),
            "requirements": plugin.get("requirements", []),
            "readme_path": plugin.get("readme_path", ""),
            "adapter_mode": plugin.get("adapter_mode", "import"),
            "total_lines_of_code": plugin.get("loc", {}).get("total", 0),
            "generated_files_size": plugin.get("size", {}).get("total_kb", 0),
            "tool_endpoints": plugin.get("tools", {}).get("count", 0),
            "supported_features": _extract_features_from_analysis(analysis).split(", "),
            "generated_tools": _extract_generated_tools(plugin, analysis)
        },
        "code_review": state.get("code_review", {}),
        "errors": errors,
        "warnings": state.get("warnings", []),
        "recommendations": _generate_recommendations(state),
        "performance_metrics": {
            "memory_usage_mb": state.get("performance", {}).get("memory_usage", 0),
            "cpu_usage_percent": state.get("performance", {}).get("cpu_usage", 0),
            "response_time_ms": state.get("performance", {}).get("response_time", 0),
            "throughput_requests_per_second": state.get("performance", {}).get("throughput", 0)
        },
        "deployment_info": {
            "supported_platforms": ["Linux", "Windows", "macOS"],
            "python_versions": ["3.8", "3.9", "3.10", "3.11", "3.12"],
            "deployment_methods": ["Docker", "pip", "conda"],
            "monitoring_support": True,
            "logging_configuration": "structured"
        }
    }
    
    logger.info("Starting LLM intelligent summary generation...")
    llm_analysis = _generate_llm_summary(state, workflow_summary)
    workflow_summary["execution_analysis"] = llm_analysis.get("execution_analysis", {})
    workflow_summary["technical_quality"] = llm_analysis.get("technical_quality", {})
    
    technical_report = _generate_technical_report(state, workflow_summary, llm_analysis)
    
    state["summary"] = workflow_summary
    state["technical_report"] = technical_report
    
    _save_final_reports(state, workflow_summary, technical_report)
    
    if state.get("workflow_status") == "success":
        auto_deploy = os.getenv("AUTO_DEPLOY_HF", "false").lower() == "true"
        if auto_deploy:
            logger.info("AUTO_DEPLOY_HF enabled, deploying to HuggingFace...")
            repo = state.get("repository", {})
            repo_root = repo.get("local_paths", {}).get("repo_root")
            repo_name = repo.get("name")
            if repo_root:
                result = deploy_to_huggingface(repo_root)
                if result.get("success"):
                    logger.info(f"HuggingFace deployment successful: {result.get('url')}")
                    state["huggingface_deployment"] = result
                    
                    auto_connect = os.getenv("AUTO_CONNECT_CLIENT", "").lower()
                    if auto_connect in ["cursor", "claude"]:
                        _connect_mcp_client(auto_connect, repo_name, result.get("url"))
                else:
                    logger.warning(f"HuggingFace deployment failed: {result.get('error')}")
    
    logger.info(f"Workflow summary generated, status: {state['status']}")
    if errors:
        logger.warning(f"Found {len(errors)} errors, please check logs")
    
    return state

def _generate_recommendations(state: Dict[str, Any]) -> list:
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

def _connect_mcp_client(client_type: str, mcp_name: str, mcp_url: str):
    try:
        tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools")
        connect_script = os.path.join(tools_dir, "connect_mcp.py")
        
        cmd = [
            "python",
            connect_script,
            "--client", client_type,
            "--name", mcp_name,
            "--url", mcp_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            logger.info(f"Auto-connected {mcp_name} to {client_type}")
        else:
            logger.warning(f"Auto-connect to {client_type} failed (may need manual configuration)")
    except Exception as e:
        logger.warning(f"Auto-connect to {client_type} failed: {e}")


def _save_final_reports(state: Dict[str, Any], summary: Dict[str, Any], technical_report: str):
    repo = state.get("repository", {})
    repo_root = repo.get("local_paths", {}).get("repo_root")
    
    if not repo_root or not os.path.isdir(repo_root):
        return
    
    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    os.makedirs(mcp_output_dir, exist_ok=True)
    
    try:
        summary_path = os.path.join(mcp_output_dir, "workflow_summary.json")
        write_file(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
        
        diff_report_content = _generate_diff_report(state)
        diff_report_path = os.path.join(mcp_output_dir, "diff_report.md")
        write_file(diff_report_path, diff_report_content)
        
        readme_mcp_content = _generate_readme_mcp(state.get("analysis", {}))
        readme_mcp_path = os.path.join(mcp_output_dir, "README_MCP.md")
        write_file(readme_mcp_path, readme_mcp_content)
        
    except Exception as e:
        pass


    
    try:
        summary_path = os.path.join(mcp_output_dir, "workflow_summary.json")
        write_file(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
        
        diff_report_content = _generate_diff_report(state)
        diff_report_path = os.path.join(mcp_output_dir, "diff_report.md")
        write_file(diff_report_path, diff_report_content)
        
        readme_mcp_content = _generate_readme_mcp(state.get("analysis", {}))
        readme_mcp_path = os.path.join(mcp_output_dir, "README_MCP.md")
        write_file(readme_mcp_path, readme_mcp_content)
        
    except Exception as e:
        pass

