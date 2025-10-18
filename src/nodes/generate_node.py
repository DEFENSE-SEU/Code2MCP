# Code Generation Node - Use LLM to generate service code, adapters, and related files
from __future__ import annotations
import os
import time
from typing import Dict, Any
from ..utils import setup_logging, ensure_directory, write_file, get_llm_service

logger = setup_logging()

def _retry_generate_text(llm_service, user_prompt: str, system_prompt: str | None = None, retries: int = 2) -> str:
    delay = 1.0
    last = ""
    for i in range(retries + 1):
        try:
            resp = llm_service.generate_text(user_prompt, system_prompt) if system_prompt is not None else llm_service.generate_text(user_prompt)
            if resp:
                return resp
            last = ""
        except Exception as e:
            last = str(e)
        if i < retries:
            import time as _t
            _t.sleep(delay)
            delay = min(delay * 2, 4.0)
    return last
def _generate_mcp_py() -> str:
    content = """
\"\"\"
MCP Service Startup Entry
\"\"\"
import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
mcp_plugin_dir = os.path.join(project_root, "mcp_plugin")
if mcp_plugin_dir not in sys.path:
    sys.path.insert(0, mcp_plugin_dir)

from mcp_service import create_app

def main():
    \"\"\"Start FastMCP service\"\"\"
    app = create_app()
    # Use environment variable to configure port, default 8000
    port = int(os.environ.get("MCP_PORT", "8000"))
    
    # Choose transport mode based on environment variable
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        app.run(transport="http", host="0.0.0.0", port=port)
    else:
        # Default to STDIO mode
        app.run()

if __name__ == "__main__":
    main()
"""
    return content

def _analyze_retry_reason(errors: list, run_results: list) -> str:
    """Analyze retry reason"""
    reasons = []
    
    for error in errors:
        message = str(error.get("message", ""))
        if "No module named" in message:
            reasons.append("Module import failed")
        elif "ImportError" in message:
            reasons.append("Import error")
        elif "SyntaxError" in message:
            reasons.append("Syntax error")
        elif error.get("severity") == "high":
            reasons.append(f"High severity error: {error.get('type', 'Unknown')}")
    
    for result in run_results:
        if not result.get("success", False):
            error_type = result.get("error_type", "Unknown")
            reasons.append(f"Execution failed: {error_type}")
    
    return "; ".join(reasons) if reasons else "Unknown error"

def _detect_project_type(analysis_result: Dict[str, Any]) -> str:
    """Detect project type"""
    ci = analysis_result.get("cpp_info", {})
    if ci and ci.get("has_cpp_files"):
        return "C/C++"
    try:
        llm_analysis = analysis_result.get("llm_analysis", {})
        core_modules = llm_analysis.get("core_modules", [])
        
        cpp_files = []
        python_files = []
        
        for module in core_modules:
            package = module.get("package", "")
            if any(ext in package for ext in ['.cpp', '.hpp', '.c', '.h']):
                cpp_files.append(package)
            elif any(ext in package for ext in ['.py']):
                python_files.append(package)
        

        repo_name = analysis_result.get("repository_name", "")
        source_dir = f"workspace/{repo_name}/source" if repo_name else ""
        
        if source_dir and os.path.exists(source_dir):
            build_files = [
                "CMakeLists.txt", "Makefile", "configure", "build.sh",
                "Cargo.toml"
            ]
            
            for build_file in build_files:
                if os.path.exists(os.path.join(source_dir, build_file)):
                    if build_file in ["CMakeLists.txt", "Makefile", "configure", "build.sh"]:
                        cpp_files.append(f"Build file: {build_file}")
                    elif build_file == "Cargo.toml":
                        cpp_files.append(f"Build file: {build_file}")  
        if cpp_files:
            return "C/C++"
        elif python_files:
            return "Python"
        else:
            return "Unknown"
            
    except Exception as e:
        logger.warning(f"Project type detection failed: {e}")
        return "Unknown"

def _generate_mcp_service(analysis_result: Dict[str, Any], retry_info: Dict[str, Any] = None, loop_summary: Dict[str, Any] | None = None) -> str:
    try:
        llm_service = get_llm_service()
        
        project_type = _detect_project_type(analysis_result)
        deps = analysis_result.get("dependencies", {})
        has_pyproject = bool(deps.get("pyproject"))
        packages = (analysis_result.get("structure") or {}).get("packages") or []
        core_modules = (analysis_result.get("llm_analysis") or {}).get("core_modules", [])
        has_signatures = any(isinstance(m.get("function_signatures"), dict) and m.get("function_signatures") for m in core_modules)

        if project_type != "C/C++" and (not has_pyproject or not packages or has_signatures):
            return _generate_mcp_service_fallback(analysis_result)
        
        system_prompt = """You are a professional Python code generation expert.

Please generate Python code directly, do not include any Markdown tags, code block tags, or other format instructions.

Focus on generating clean, functional Python code that follows best practices."""
        
        if project_type == "C/C++":
            base_prompt = f"""Generate MCP (Model Context Protocol) service code for C/C++ projects:

Analysis result: {analysis_result}

Project type: C/C++ project

Requirements:
1. Generate a complete MCP service file using fastmcp library
2. Do not try to directly import C++ source code, but create a Python wrapper
3. Use subprocess to call the compiled executable file, or use ctypes/cffi to call dynamic libraries
4. Include necessary import statements: from fastmcp import FastMCP, subprocess, ctypes
5. Use FastMCP class to create the service application: mcp = FastMCP("service_name")
6. Create tool endpoints for each core function, using @mcp.tool decorator
7. Focus on core functionality endpoints only
8. Must include create_app() function, which returns FastMCP instance
9. Tool functions must return a standard dictionary, containing success/result/error fields
10. Do not use *args or **kwargs in any @mcp.tool function; all parameters must be explicit and typed

C/C++ project specific requirements:
- Create a Python wrapper, do not directly import C++ code
- Use subprocess to call executable files or ctypes to call dynamic libraries
- Provide compilation status check and error handling
- If compilation fails, provide a fallback
- For C++ module import errors, provide a simulated implementation or comment out the import
- Support multiple build systems: CMake, Makefile, configure, etc."""

        else:
            base_prompt = f"""Generate MCP (Model Context Protocol) service code:

Analysis result: {analysis_result}

Project type: {project_type} project

Requirements:
1. Generate a complete MCP (Model Context Protocol) service file using fastmcp library
2. Include necessary import statements: from fastmcp import FastMCP
3. ALWAYS add path settings at the top to include the local source directory on sys.path:
   - import os, import sys
   - source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
   - if source_path not in sys.path: sys.path.insert(0, source_path)
4. Use FastMCP class to create the service application: mcp = FastMCP("service_name")
5. Generate rich tool endpoints for each core module, using @mcp.tool decorator, including name and description parameters
6. Focus on core functionality endpoints only
7. Must include create_app() function, which returns FastMCP instance
8. Tool functions must return a standard dictionary, containing success/result/error fields, do not add description or other extra fields
9. Do not use *args or **kwargs in any @mcp.tool function; all parameters must be explicit and typed

CRITICAL Import Requirements:
- If pyproject.toml exists with a valid package name, you may import using that package name.
- If pyproject.toml does NOT exist or the package cannot be imported, import modules using local paths after sys.path injection (e.g., "from scripts.SequencePatternMatching import ...").
- Do NOT invent new top-level package names that do not exist.
- You may remove any leading "source." or "src." prefix from analysis results when importing locally after sys.path injection.
- All imports must work out-of-the-box without requiring packaging when pyproject.toml is absent."""

        if retry_info:
            error_analysis = retry_info.get('error_analysis', {})
            fix_strategy = retry_info.get('fix_strategy', {})
            specific_fixes = retry_info.get('specific_fixes', [])
            
            retry_guidance = f"""

Smart Error Fix Guidance

Retry Information:
- Retry Count: {retry_info.get('retry_count', 0)}
- Error Type: {error_analysis.get('error_analysis', {}).get('error_type', 'Unknown')}
- Severity: {error_analysis.get('error_analysis', {}).get('severity', 'Unknown')}
- Root Cause: {error_analysis.get('error_analysis', {}).get('root_cause', 'Unknown')}

Specific Fix Strategy:
Fix Approach: {fix_strategy.get('approach', 'Generic Fix')}

Specific Modifications to be Executed:"""

            for i, fix in enumerate(specific_fixes, 1):
                retry_guidance += f"""
{i}. File: {fix.get('file', 'unknown')}
    Action: {fix.get('action', 'modify')}
    Content: {fix.get('content', 'Not specified')}
    Reason: {fix.get('reason', 'Not specified')}"""

            import_fixes = fix_strategy.get('import_fixes', [])
            if import_fixes:
                retry_guidance += f"""

Import Statement Fix Requirements:
{chr(10).join(f'- {fix}' for fix in import_fixes)}"""

            path_fixes = fix_strategy.get('path_fixes', [])
            if path_fixes:
                retry_guidance += f"""

Path Configuration Fix Requirements:
{chr(10).join(f'- {fix}' for fix in path_fixes)}"""

            prevention = error_analysis.get('prevention', {})
            if prevention:
                retry_guidance += f"""

Required Preventive Measures:
- Error Handling: {', '.join(prevention.get('error_handling', []))}
- Validation Logic: {', '.join(prevention.get('validation', []))}
- Fallback Scheme: {', '.join(prevention.get('fallback', []))}"""

            retry_guidance += f"""

Key Requirements:
1. Must strictly follow the above repair strategy
2. Add module existence verification
3. Provide fallback import scheme
4. Ensure basic operation even when dependencies are missing

Confidence: {error_analysis.get('confidence', 0):.2f}
"""
            
            base_prompt += retry_guidance

        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        user_prompt = prefix + base_prompt + """

Decorator Usage Guidelines:
- Use @mcp.tool(name="tool_name", description="Tool description") format
- name parameter uses clear tool names
- description parameter provides a concise function description
- function docstring provides detailed parameter and return value descriptions

Note: Directly return Python code, do not include any Markdown format. Please generate a rich, high-quality MCP (Model Context Protocol) service, fully utilizing all functions from the analysis result!"""
        if state := locals().get('state'):
            loop_summary = state.get("loop_summary") if isinstance(state, dict) else None
        else:
            loop_summary = None
        if loop_summary:
            user_prompt = f"Loop summary: {loop_summary}\n\n" + user_prompt
        generated_code = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not generated_code or len(generated_code.strip()) < 100:
            logger.warning("LLM code generation failed, using fallback template")
            return _generate_mcp_service_fallback(analysis_result)
        return _strip_code_fences(generated_code)

    except Exception as e:
        logger.error(f"LLM code generation error: {e}")
        return _generate_mcp_service_fallback(analysis_result)

def _generate_mcp_service_fallback(analysis_result: Dict[str, Any]) -> str:
    llm_analysis = analysis_result.get("llm_analysis", {})
    core_modules = llm_analysis.get("core_modules", [])
    repo_name = analysis_result.get("repository_name", "unknown")
    service_name = f"{repo_name.lower()}_service"
    
    project_type = _detect_project_type(analysis_result)
    
    imports = []
    tools_code = ""
    
    # C/C++ project specific handling
    if project_type == "C/C++":
        imports.append("import subprocess")
        imports.append("import os")
        imports.append("import sys")
        
        for module in core_modules:
            package = module.get("package", "")
            functions = module.get("functions", [])
            classes = module.get("classes", [])
            
            if package:
                if package.startswith("source."):
                    package = package[7:]
                
                for func in functions:
                    if func.endswith("*"):
                        func = func[:-1]
                    
                    tools_code += f"""
@mcp.tool(name="{func}", description="{func} function (C++ wrapper)")
def {func}(*args, **kwargs):
    \"\"\"Call C++ function {func}\"\"\"
    try:
        # This needs to be adjusted based on the actual C++ executable file path
        executable_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source", "build", "{func}")
        
        if not os.path.exists(executable_path):
            return {{"success": False, "error": f"C++ executable file not found: {{executable_path}}", "result": None}}
        
        # Call C++ executable file
        result = subprocess.run([executable_path] + list(args), 
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            return {{"success": True, "result": result.stdout.strip(), "error": None}}
        else:
            return {{"success": False, "error": result.stderr.strip(), "result": None}}
            
    except Exception as e:
        return {{"success": False, "error": f"C++ function call failed: {{str(e)}}", "result": None}}
"""

    else:
        # Python project handling
        for module in core_modules:
            package = module.get("package", "")
            module_name = module.get("module", "")
            functions = module.get("functions", [])
            classes = module.get("classes", [])
            confidence = module.get("import_confidence", "medium")
        
            if package:
                if package.startswith("source."):
                    package = package[7:]
                if package.startswith("src."):
                    package = package[4:]  
                
                if module_name and module_name != package and not package.endswith(module_name):
                    import_path = f"{package}.{module_name}"
                else:
                    import_path = package
                
                clean_functions = []
                clean_classes = []
                
                for func in functions:
                    if func.endswith("*"):
                        clean_functions.append(func[:-1])
                    else:
                        clean_functions.append(func)
                        
                for cls in classes:
                    if cls.endswith("*"):
                        clean_classes.append(cls[:-1])
                    else:
                        clean_classes.append(cls)
                
                all_items = list(set(clean_functions + clean_classes))
                if all_items:
                    if confidence == "low":
                        imports.append(f"# Note: Import paths may need adjustment")
                        imports.append(f"try:")
                        imports.append(f"    from {import_path} import {', '.join(all_items)}")
                        imports.append(f"except ImportError as e:")
                        imports.append(f"    # Import failed, path may need adjustment")
                        imports.append(f"    print(f'Import warning: {{e}}')")
                        imports.append(f"    {', '.join(all_items)} = None")
                    else:
                        imports.append(f"from {import_path} import {', '.join(all_items)}")
                
                # Deterministic wrappers using function_signatures from analysis
                func_sigs = module.get("function_signatures", {})
                for func in clean_functions:
                    params = func_sigs.get(func, []) if isinstance(func_sigs, dict) else []
                    param_list = ", ".join(f"{p}: str" for p in params) if params else "payload: dict"
                    call_args = ", ".join(params) if params else "**payload"
                    tools_code += f"""
@mcp.tool(name="{func}", description="Auto-wrapped function {func}")
def {func}({param_list}):
    try:
        if {func} is None:
            return {{"success": False, "result": None, "error": "Function {func} is not available"}}
        result = {func}({call_args})
        return {{"success": True, "result": result, "error": None}}
    except Exception as e:
        return {{"success": False, "result": None, "error": str(e)}}
"""
                
                for cls in clean_classes:
                    tools_code += f"""
@mcp.tool(name="{cls.lower()}", description="{cls} class")
def {cls.lower()}(*args, **kwargs):
    \"\"\"{cls} class\"\"\"
    try:
        if {cls} is None:
            return {{"success": False, "result": None, "error": "Class {cls} is not available, path may need adjustment"}}
        
        # MCP parameter type conversion
        converted_args = []
        converted_kwargs = kwargs.copy()
        
        # Handle position argument type conversion
        for arg in args:
            if isinstance(arg, str):
                # Try to convert to numeric type
                try:
                    if '.' in arg:
                        converted_args.append(float(arg))
                    else:
                        converted_args.append(int(arg))
                except ValueError:
                    converted_args.append(arg)
            else:
                converted_args.append(arg)
        
        # Handle keyword argument type conversion
        for key, value in converted_kwargs.items():
            if isinstance(value, str):
                try:
                    if '.' in value:
                        converted_kwargs[key] = float(value)
                    else:
                        converted_kwargs[key] = int(value)
                except ValueError:
                    pass
        
        instance = {cls}(*converted_args, **converted_kwargs)
        return {{"success": True, "result": str(instance), "error": None}}
    except Exception as e:
        return {{"success": False, "result": None, "error": str(e)}}
"""

    
    if not imports:
        imports = ["# No imports available"]
        tools_code = """
    @mcp.tool(name="core", description="Default core function")
    def core(*args, **kwargs):
        return {"success": False, "result": None, "error": "no_import_available"}
"""
    
    if project_type == "C/C++":
        content = f"""import os
import sys
import subprocess
import ctypes
from pathlib import Path

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
if source_path not in sys.path:
    sys.path.insert(0, source_path)

from fastmcp import FastMCP

{chr(10).join(imports)}

mcp = FastMCP("{service_name}")

{tools_code}

@mcp.tool(name="compile_status", description="Check C++ compilation status")
def compile_status():
    \"\"\"Check C++ compilation status\"\"\"
    try:
        build_dir = os.path.join(source_path, "build")
        if os.path.exists(build_dir):
            return {{"success": True, "result": {{"status": "compiled", "build_dir": build_dir}}}}
        else:
            return {{"success": True, "result": {{"status": "not_compiled", "message": "C++ code needs to be compiled"}}}}
    except Exception as e:
        return {{"success": False, "error": f"Compilation status check failed: {{str(e)}}"}}

def create_app():
    \"\"\"Create and return FastMCP application instance\"\"\"
    return mcp

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
"""

    else:
        content = f"""import os
import sys

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
if source_path not in sys.path:
    sys.path.insert(0, source_path)

from fastmcp import FastMCP

{chr(10).join(imports)}

mcp = FastMCP("{service_name}")

{tools_code}


def create_app():
    \"\"\"Create and return FastMCP application instance\"\"\"
    return mcp

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
"""
    return content

def _generate_adapter_import(analysis_result: Dict[str, Any], loop_summary: Dict[str, Any] | None = None) -> str:
    
    try:
        llm_service = get_llm_service()
        
        system_prompt = """You are a professional Python code generation expert.

Please generate Python code directly, do not include any Markdown tags, code block tags, or other format instructions.

Focus on generating clean, functional Python code that follows best practices."""
        
        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        user_prompt = prefix + f"""Generate Import mode adapter code for MCP plugin:

Analysis result: {analysis_result}

Important: Please fully utilize DeepWiki analysis and LLM analysis results to generate a rich, high-quality adapter!

Important requirements:
1. Generate a complete adapter class, the class name must be Adapter
2. Add path settings at the beginning of the file: import os, import sys, source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source"), sys.path.insert(0, source_path)
3. Import statements must use the full package path from the analysis result, do not use simplified package names
4. Create corresponding methods for each identified class and function to ensure full utilization of all functions
5. Include error handling and status return
6. Handle import failure cases, provide graceful fallback
7. The class must include a mode attribute, initialized to "import"
8. The code structure must be clear, use separators to group different functional modules
9. All methods must return a unified dictionary format, containing the status field
10. Error messages must be in English only; provide clear, concise, actionable guidance.
11. Module management, organize code by function

Function generation requirements:
- Generate corresponding methods based on the functions and classes fields in the analysis result
- Create an instance method for each identified class
- Create a call method for each identified function
- Fully utilize all functional features described in DeepWiki analysis
- Generate rich, comprehensive methods
- Each method must have a detailed docstring and parameter description
- Include complete error handling and status return

Import path requirements:
- Since sys.path is already pointing to the source directory, import statements should remove the "source." prefix from the package field
- Import all identified classes and functions in the analysis result
- Do not simplify to short package names
- Ensure the call is the actual implementation of the original repository, not an external package installation

Method implementation requirements:
- Create a dedicated instance method for each imported class
- Create a dedicated call method for each imported function
- Each method must have a clear parameter definition and return value description
- Include complete error handling and exception capture
- Provide friendly prompts in fallback mode
- Ensure all imported functions have corresponding method implementations

Code structure requirements:
- Add a clear module description at the beginning of the file
- Use separators to group different functional modules
- Each method must have a detailed docstring
- Unified error handling pattern
- Friendly prompts in fallback mode
- Clear code structure, easy to maintain and extend

Note: Directly return Python code, do not include any Markdown format. The class name must be Adapter. The code must be clear and readable, with a reasonable structure. Please generate a rich, high-quality adapter, fully utilizing all functions from the analysis result!"""
        
        generated_code = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not generated_code or len(generated_code.strip()) < 100:
            logger.warning("LLM adapter code generation failed, using fallback template")
            return _generate_adapter_import_fallback(analysis_result)
        return _strip_code_fences(generated_code)
        
    except Exception as e:
        logger.error(f"LLM adapter code generation error: {e}")
        return _generate_adapter_import_fallback(analysis_result)

def _generate_adapter_import_fallback(analysis_result: Dict[str, Any]) -> str:
    llm_analysis = analysis_result.get("llm_analysis", {})
    core_modules = llm_analysis.get("core_modules", [])
    
    imports = []
    methods = []
    
    for module in core_modules:
        package = module.get("package", "")
        module_name = module.get("module", "")
        functions = module.get("functions", [])
        classes = module.get("classes", [])
        
        if package:

            if package.startswith("source."):
                package = package[7:] 
            
            if module_name and module_name != package and not package.endswith(module_name):
                import_path = f"{package}.{module_name}"
            else:
                import_path = package
            
            all_items = list(set(functions + classes))
            if all_items:
                imports.append(f"""try:
        from {import_path} import {', '.join(all_items)}
        {', '.join(all_items)} = None""")
            
            for func in functions:
                methods.append(f"""
    def {func}(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Call {import_path}.{func}\"\"\"
        try:
            # Check if function is available
            if {func} is None:
                return {{"error": "Function {func} is not available", "status": "error"}}
            result = {func}(**payload)
            return {{"result": result, "status": "success"}}
        except Exception as e:
            return {{"error": str(e), "status": "error"}}
""")
            
            for cls in classes:
                methods.append(f"""
    def {cls.lower()}(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Call {import_path}.{cls}\"\"\"
        try:
            # Check if class is available
            if {cls} is None:
                return {{"error": "Class {cls} is not available", "status": "error"}}
            instance = {cls}(**payload)
            return {{"result": str(instance), "status": "success"}}
        except Exception as e:
            return {{"error": str(e), "status": "error"}}
""")
    
    if not imports:
        imports = []
        methods = ["""
    def core(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Default core function\"\"\"
        return {"result": "no_import_available", "status": "warning"}
"""]
    
    content = f"""
\"\"\"
FastMCP Import mode adapter
Provides module import and function call services
\"\"\"

import json
import logging
import os
import sys
from typing import Dict, Any

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

class Adapter:
    \"\"\"Import mode adapter, supports dynamic module import and function call\"\"\"
    
    def __init__(self):
        \"\"\"Initialize adapter\"\"\"
        self.mode = "import"
        self._initialize_imports()
    
    def _initialize_imports(self):
        \"\"\"Initialize module imports\"\"\"
        # Modules required will be dynamically imported here
        pass

{chr(10).join(imports)}

    # ==================== Function Methods ====================
{chr(10).join(methods)}
    
    def get_status(self) -> Dict[str, Any]:
        \"\"\"Get adapter status\"\"\"
        return {{
            "mode": self.mode,
            "status": "success",
            "available_functions": {len([m for m in methods if "def " in m])}
        }}
"""
    return content

def _generate_adapter_cli(analysis_result: Dict[str, Any], loop_summary: Dict[str, Any] | None = None) -> str:
    """Generate CLI mode adapter code using LLM"""
    try:
        llm_service = get_llm_service()
        
        system_prompt = """You are a professional Python code generation expert.

Please generate Python code directly, do not include any Markdown tags, code block tags, or other format instructions.

Focus on generating clean, functional Python code that follows best practices."""
        
        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        user_prompt = prefix + f"""Generate CLI mode adapter code for MCP plugin:

Analysis result: {analysis_result}

Requirements:
1. Generate a complete CLI mode adapter class
2. Add path settings at the beginning of the file: import os, import sys, source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source"), sys.path.insert(0, source_path)
3. Include necessary import statements
4. Generate corresponding methods for each CLI command
5. Include error handling and status return
6. Use subprocess to execute CLI commands

Note: Directly return Python code, do not include any Markdown format."""
        
        generated_code = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not generated_code or len(generated_code.strip()) < 100:
            logger.warning("LLM CLI adapter code generation failed, using fallback template")
            return _generate_adapter_cli_fallback(analysis_result)
        return _strip_code_fences(generated_code)
        
    except Exception as e:
        logger.error(f"LLM CLI adapter code generation error: {e}")
        return _generate_adapter_cli_fallback(analysis_result)

def _generate_adapter_cli_fallback(analysis_result: Dict[str, Any]) -> str:
    """Fallback CLI mode adapter generation function"""
    llm_analysis = analysis_result.get("llm_analysis", {})
    cli_commands = llm_analysis.get("cli_commands", [])
    
    methods = []
    for cmd in cli_commands:
        name = cmd.get("name", "unknown")
        module = cmd.get("module", "")
        methods.append(f"""
    def {name}(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Execute CLI command: {name}\"\"\"
        try:
            import subprocess
            cmd = ["python", "-m", "{module}"]
            if payload:
                cmd.extend(["--input", json.dumps(payload)])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return {{"result": result.stdout, "status": "success"}}
            else:
                return {{"error": result.stderr, "status": "error"}}
        except Exception as e:
            return {{"error": str(e), "status": "error"}}
""")
    
    if not methods:
        methods = ["""
    def core(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Default CLI function\"\"\"
        return {"result": "no_cli_available", "status": "warning"}
"""]
    
    content = f"""import json
import subprocess
from typing import Dict, Any

class Adapter:
    \"\"\"CLI mode adapter\"\"\"
    
    def __init__(self):
        self.mode = "cli"
{chr(10).join(methods)}
"""
    return content

def _generate_adapter_blackbox(analysis_result: Dict[str, Any]) -> str:
    content = """import json
import subprocess
import os
import sys
from typing import Dict, Any

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

class Adapter:
    \"\"\"Blackbox mode adapter\"\"\"
    
    def __init__(self):
        self.mode = "blackbox"
    
    def core(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Blackbox mode core function\"\"\"
        try:
            scripts = [
                ["python", "main.py"],
                ["python", "-m", "pytest", "--help"],
                ["python", "setup.py", "test"]
            ]
            
            for script in scripts:
                try:
                    result = subprocess.run(script, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        return {"result": f"Script {script} executed successfully", "status": "success"}
                except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as script_error:
                    print(f"Script execution failed {script}: {script_error}")
                    continue
            
            return {"result": "no_executable_script_found", "status": "warning"}
        except Exception as e:
            return {"error": str(e), "status": "error"}
"""
    return content

def _generate_requirements_txt(analysis_result: Dict[str, Any]) -> str:
    llm_analysis = analysis_result.get("llm_analysis", {})
    dependencies = llm_analysis.get("dependencies", {})
    
    required = dependencies.get("required", [])
    optional = dependencies.get("optional", [])
    
    content = """fastmcp>=0.1.0
pydantic>=2.0.0
"""
    
    for dep in required:
        if dep and isinstance(dep, str):
            content += f"{dep}\n"
    
    if optional:
        content += "\n# Optional Dependencies\n"
        for dep in optional:
            if dep and isinstance(dep, str):
                content += f"# {dep}\n"
    
    return content


def _generate_readme_mcp(analysis_result: Dict[str, Any], loop_summary: Dict[str, Any] | None = None) -> str:
    """Generate README document using LLM"""
    try:
        llm_service = get_llm_service()
        
        system_prompt = """You are a professional technical documentation writer.

Please generate Markdown documentation directly, do not include any code block tags or other format instructions.

Focus on creating clear, well-structured Markdown documentation."""
        
        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        user_prompt = prefix + f"""Generate MCP plugin README:

Analysis result: {analysis_result}

Requirements:
1. Generate a complete README.md document
2. Include project overview, installation instructions, and usage methods
3. List all available tool endpoints
4. Include notes and troubleshooting
5. Use Markdown format, clear structure

Note: Directly return Markdown document content, do not include any code block tags."""
        
        generated_doc = _retry_generate_text(llm_service, user_prompt, system_prompt)
        
        if not generated_doc or len(generated_doc.strip()) < 100:
            logger.warning("LLM README generation failed, using fallback template")
            return _generate_readme_mcp_fallback(analysis_result)
        return generated_doc.strip()
        
    except Exception as e:
        logger.error(f"LLM README generation error: {e}")
        return _generate_readme_mcp_fallback(analysis_result)

def _generate_readme_mcp_fallback(analysis_result: Dict[str, Any]) -> str:
    """Fallback README generation function"""
    repo_name = analysis_result.get("repository_name", "unknown")
    llm_analysis = analysis_result.get("llm_analysis", {})
    import_strategy = llm_analysis.get("import_strategy", {})
    
    content = f"""# {repo_name} MCP Plugin

## Overview
This is an MCP plugin generated for the {repo_name} project, implemented using {import_strategy.get('primary', 'unknown')} mode.

## Installation Dependencies
```bash
pip install -r requirements.txt
```

## Start Service
```bash
python start_mcp.py
```

## Usage
After the service starts, you can call the following tools via MCP client:

"""
    
    core_modules = llm_analysis.get("core_modules", [])
    for module in core_modules:
        functions = module.get("functions", [])
        classes = module.get("classes", [])
        
        for func in functions:
            content += f"- `{func}(payload)`: {module.get('description', '')} - {func} function\n"
        
        for cls in classes:
            content += f"- `{cls.lower()}(payload)`: {module.get('description', '')} - {cls} class\n"
    
    content += """
## Notes
- Plugin adopts minimal invasive design, does not modify original project code
- If issues arise, please check if the original project is running normally
"""
    
    return content

def _strip_code_fences(content: str) -> str:
    import re
    content = re.sub(r'^```(?:python)?\s*\n?', '', content)
    content = re.sub(r'\n?\s*```\s*$', '', content)
    return content.strip()

def _prune_analysis_for_generation(analysis_result: Dict[str, Any], repo_root: str, max_total: int = 12) -> Dict[str, Any]:
    llm = analysis_result.get("llm_analysis", {})
    core_modules = llm.get("core_modules", [])
    src_dir = os.path.join(repo_root, "source")
    kept = []
    total = 0
    for m in core_modules:
        pkg = m.get("package", "")
        conf = m.get("import_confidence", "medium")
        if not pkg or "tests" in pkg.lower():
            continue
        rel_pkg = pkg[7:].replace(".", os.sep) if pkg.startswith("source.") else pkg.replace(".", os.sep)
        mod_file_pkg = os.path.join(src_dir, rel_pkg + ".py")
        init_file = os.path.join(src_dir, rel_pkg, "__init__.py")
        module_name = m.get("module", "")
        rel_mod = (pkg + "." + module_name) if module_name and pkg else module_name or pkg
        rel_mod_path = rel_mod.replace(".", os.sep) if rel_mod else ""
        mod_file_mod = os.path.join(src_dir, rel_mod_path + ".py") if rel_mod_path else None
        target_file = None
        if mod_file_pkg and os.path.isfile(mod_file_pkg):
            target_file = mod_file_pkg
        elif init_file and os.path.isfile(init_file):
            target_file = init_file
        elif mod_file_mod and os.path.isfile(mod_file_mod):
            target_file = mod_file_mod
        if not target_file:
            continue
        try:
            import ast
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read() or "")
            defs_funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
            defs_classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef) and not n.name.startswith("_")}
        except Exception:
            defs_funcs, defs_classes = set(), set()
        cand_funcs = [x.rstrip("*") for x in m.get("functions", []) if x and not x.startswith("_")]
        cand_classes = [x.rstrip("*") for x in m.get("classes", []) if x and not x.startswith("_")]
        inter_funcs = [x for x in cand_funcs if x in defs_funcs and "test" not in x.lower() and "example" not in x.lower()]
        inter_classes = [x for x in cand_classes if x in defs_classes and "test" not in x.lower() and "example" not in x.lower()]
        cap = 5 if conf == "high" else 3 if conf == "medium" else 1
        inter_funcs = inter_funcs[:cap]
        inter_classes = inter_classes[:cap]
        if not inter_funcs and not inter_classes:
            continue
        if total + len(inter_funcs) + len(inter_classes) > max_total:
            remain = max_total - total
            if remain <= 0:
                break
            take_f = min(len(inter_funcs), remain)
            inter_funcs = inter_funcs[:take_f]
            remain -= take_f
            inter_classes = inter_classes[:remain]
        kept.append({
            "package": m.get("package", ""),
            "module": m.get("module", ""),
            "functions": inter_funcs,
            "classes": inter_classes,
            "description": m.get("description", ""),
            "import_confidence": conf
        })
        total += len(inter_funcs) + len(inter_classes)
        if total >= max_total:
            break
    pruned_llm = dict(llm)
    pruned_llm["core_modules"] = kept
    out = dict(analysis_result)
    out["llm_analysis"] = pruned_llm
    return out

def generate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    repo = state.get("repository", {})
    repo_root = repo.get("local_paths", {}).get("repo_root")
    mcp_plugin_dir = repo.get("local_paths", {}).get("mcp_plugin")
    tests_mcp_dir = repo.get("local_paths", {}).get("tests_mcp")
    analysis = state.get("analysis", {})
    analysis_pruned = _prune_analysis_for_generation(analysis, repo_root)
    
    retry_count = state.get("generation_retry_count", 0)
    previous_errors = state.get("errors", [])
    previous_run_results = state.get("previous_run_results", [])
    
    if retry_count > 0:
        logger.info(f"Starting {retry_count}th generation attempt, improving based on previous errors")
        retry_reason = _analyze_retry_reason(previous_errors, previous_run_results)
        state.setdefault("retry_reasons", []).append({
            "retry_count": retry_count,
            "reason": retry_reason,
            "timestamp": time.time()
        })
    
    if not repo_root:
        state.setdefault("errors", []).append({
            "node": "GenerateNode",
            "type": "InvalidInput",
            "message": "repo_root path missing, attempting to use default path",
            "action_taken": "continue"
        })
        repo_root = os.path.join("workspace", repo.get("name", "unknown"))
        repo["local_paths"] = repo.get("local_paths", {})
        repo["local_paths"]["repo_root"] = repo_root

    llm_analysis = analysis_pruned.get("llm_analysis", {})
    import_strategy = llm_analysis.get("import_strategy", {})
    adapter_mode = import_strategy.get("primary", "import")
    
    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    ensure_directory(mcp_output_dir)
    
    mcp_plugin_dir = os.path.join(mcp_output_dir, "mcp_plugin")
    tests_mcp_dir = os.path.join(mcp_output_dir, "tests_mcp")
    
    ensure_directory(mcp_plugin_dir)
    
    source_dir = os.path.join(repo_root, "source")
    
    source_init_path = os.path.join(source_dir, "__init__.py")
    if not os.path.exists(source_init_path):
        repo_name = repo.get("name", "unknown")
        write_file(source_init_path, f"# -*- coding: utf-8 -*-\n\"\"\"\n{repo_name} Project Package Initialization File\n\"\"\"\n")
    
    # Dynamically ensure package __init__.py along core module import paths
    try:
        llm_analysis = analysis.get("llm_analysis", {})
        core_modules = llm_analysis.get("core_modules", [])
        def _ensure_pkg_inits(abs_dir: str):
            if not abs_dir or not abs_dir.startswith(source_dir):
                return
            parts = []
            rel = os.path.relpath(abs_dir, source_dir)
            if rel == ".":
                return
            for segment in rel.split(os.sep):
                parts.append(segment)
                cur = os.path.join(source_dir, *parts)
                if os.path.isdir(cur):
                    init_p = os.path.join(cur, "__init__.py")
                    if not os.path.exists(init_p):
                        write_file(init_p, "# -*- coding: utf-8 -*-\n")
        for m in core_modules:
            pkg = m.get("package", "") or ""
            mod = m.get("module", "") or ""
            # Normalize prefixed paths
            if pkg.startswith("source."):
                pkg = pkg[7:]
            if pkg.startswith("src."):
                pkg = pkg[4:]
            pkg_path = os.path.join(source_dir, *[p for p in pkg.split(".") if p]) if pkg else None
            if pkg_path and os.path.exists(pkg_path):
                _ensure_pkg_inits(pkg_path)
            # If module is a submodule under package
            if mod and mod not in (pkg or ""):
                mod_path = os.path.join(source_dir, *[p for p in mod.split(".") if p])
                if os.path.exists(mod_path):
                    _ensure_pkg_inits(mod_path)
    except Exception:
        # Best-effort; do not fail generation on init creation
        pass
    
    llm_analysis = analysis.get("llm_analysis", {})
    core_modules = llm_analysis.get("core_modules", [])
    
    for module in core_modules:
        package = module.get("package", "")
        if package and "src." in package:
            source_src_dir = os.path.join(source_dir, "src")
            source_src_init_path = os.path.join(source_src_dir, "__init__.py")
            if not os.path.exists(source_src_init_path):
                write_file(source_src_init_path, "# -*- coding: utf-8 -*-\n\"\"\"\nsrc Package Initialization File\n\"\"\"\n")
            break
    
    files = {}
    
    mcp_py_path = os.path.join(mcp_output_dir, "start_mcp.py")
    write_file(mcp_py_path, _generate_mcp_py())
    files["mcp_output/start_mcp.py"] = mcp_py_path
    
    init_path = os.path.join(mcp_plugin_dir, "__init__.py")
    write_file(init_path, "")
    files["mcp_output/mcp_plugin/__init__.py"] = init_path
    
    service_path = os.path.join(mcp_plugin_dir, "mcp_service.py")
    retry_info = None
    
    error_analysis = state.get("error_analysis", {})
    if error_analysis:
        retry_info = {
            "retry_count": retry_count,
            "reason": state.get("retry_reasons", [])[-1].get("reason", "Unknown") if state.get("retry_reasons") else "Unknown",
            "previous_errors": previous_errors,
            "previous_run_results": previous_run_results,
            "error_analysis": error_analysis,  
            "fix_strategy": error_analysis.get("fix_strategy", {}),
            "specific_fixes": error_analysis.get("fix_strategy", {}).get("specific_changes", [])
        }
    elif retry_count > 0:
        retry_info = {
            "retry_count": retry_count,
            "reason": state.get("retry_reasons", [])[-1].get("reason", "Unknown") if state.get("retry_reasons") else "Unknown",
            "previous_errors": previous_errors,
            "previous_run_results": previous_run_results,
            "error_analysis": {},
            "fix_strategy": {},
            "specific_fixes": []
        }
    
    loop_summary = state.get("loop_summary")
    write_file(service_path, _strip_code_fences(_generate_mcp_service(analysis_pruned, retry_info, loop_summary)))
    files["mcp_output/mcp_plugin/mcp_service.py"] = service_path
    
    adapter_path = os.path.join(mcp_plugin_dir, "adapter.py")
    if adapter_mode == "import":
        adapter_content = _generate_adapter_import(analysis_pruned, loop_summary)
    elif adapter_mode == "cli":
        adapter_content = _generate_adapter_cli(analysis_pruned, loop_summary)
    else:
        adapter_content = _generate_adapter_blackbox(analysis_pruned)
    
    write_file(adapter_path, _strip_code_fences(adapter_content))
    files["mcp_output/mcp_plugin/adapter.py"] = adapter_path
    
    main_path = os.path.join(mcp_plugin_dir, "main.py")
    main_content = '''"""
MCP Service Auto-Wrapper - Auto-generated
"""
from mcp_service import create_app

def main():
    """Main entry point"""
    app = create_app()
    return app

if __name__ == "__main__":
    app = main()
    app.run()
'''
    write_file(main_path, _strip_code_fences(main_content))
    files["mcp_output/mcp_plugin/main.py"] = main_path
    
    req_path = os.path.join(mcp_output_dir, "requirements.txt")
    if not os.path.exists(req_path):
        write_file(req_path, _generate_requirements_txt(analysis))
        files["mcp_output/requirements.txt"] = req_path
    
    readme_path = os.path.join(mcp_output_dir, "README_MCP.md")
    analysis["repository_name"] = repo.get("name", "unknown")
    write_file(readme_path, _generate_readme_mcp(analysis_pruned, loop_summary))
    files["mcp_output/README_MCP.md"] = readme_path
    
    # removed tests generation block per user request
    
    endpoints = []
    core_modules = llm_analysis.get("core_modules", [])
    for module in core_modules:
        functions = module.get("functions", [])
        classes = module.get("classes", [])
        endpoints.extend(functions)
        endpoints.extend([cls.lower() for cls in classes])
    
    state["plugin"] = {
        "files": files,
        "adapter_mode": adapter_mode,
        "endpoints": endpoints,
        "mcp_dir": mcp_plugin_dir,
        "tests_dir": tests_mcp_dir,
        "main_entry": "start_mcp.py",
        "readme_path": readme_path,
        "requirements": ["fastmcp>=0.1.0", "pydantic>=2.0.0"]
    }
    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state