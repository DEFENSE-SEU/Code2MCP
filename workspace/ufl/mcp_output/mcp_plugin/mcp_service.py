import os
import sys

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from ufl import (
    Form, AbstractFiniteElement, as_tensor, 
    H1, H2, HCurl, HDiv, 
    triangle, tetrahedron, quadrilateral,
    grad, div, curl, sin, cos, exp,
    dx, ds, TestFunction, TrialFunction,
    FunctionSpace, Constant, SpatialCoordinate,
    Coefficient, Argument
)
from ufl.tensors import ListTensor

mcp = FastMCP("ufl_service")

@mcp.tool(name="create_form", description="Create a mathematical form using UFL with user-specified expression.")
def create_form(data):
    try:
        if isinstance(data, dict):
            expression = data.get("expression", "u*v")
            cell_type = data.get("cell", "triangle")
            degree = data.get("degree", 1)
            family = data.get("family", "CG")
        else:
            expression = str(data) if data else "u*v"
            cell_type = "triangle"
            degree = 1
            family = "CG"
        
        if cell_type == "triangle":
            cell = triangle
        elif cell_type == "tetrahedron":
            cell = tetrahedron
        elif cell_type == "quadrilateral":
            cell = quadrilateral
        else:
            cell = triangle
        
        V = FunctionSpace(cell, family, degree)
        u = TestFunction(V)
        v = TrialFunction(V)
        x = SpatialCoordinate(cell)
        f = Constant(1.0)
        
        expr_env = {
            'u': u, 'v': v, 'x': x, 'f': f,
            'grad': grad, 'div': div, 'curl': curl,
            'sin': sin, 'cos': cos, 'exp': exp,
            'dx': dx, 'ds': ds,
            'Constant': Constant,
            'TestFunction': TestFunction,
            'TrialFunction': TrialFunction
        }
        
        try:
            form_expr = eval(expression, {"__builtins__": {}}, expr_env)
            return {"success": True, "result": f"Created form: {form_expr} on {cell}", "error": None}
        except Exception as eval_error:
            return {"success": False, "result": None, "error": f"Expression evaluation error: {str(eval_error)}"}
        
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="finite_element", description="Define a finite element using UFL.")
def finite_element_tool(data):
    try:
        if isinstance(data, dict):
            family = data.get("family", "CG")
            cell_type = data.get("cell", "triangle")
            degree = data.get("degree", 1)
        else:
            family = "CG"
            cell_type = "triangle"
            degree = 1
        
        if cell_type == "triangle":
            cell = triangle
        elif cell_type == "tetrahedron":
            cell = tetrahedron
        elif cell_type == "quadrilateral":
            cell = quadrilateral
        else:
            cell = triangle
        
        V = FunctionSpace(cell, family, degree)
        
        return {"success": True, "result": f"FunctionSpace({cell}, '{family}', {degree})", "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="tensor_operations", description="Create and manipulate tensors using UFL with user-specified components.")
def tensor_operations(data):
    try:
        if isinstance(data, dict):
            components = data.get("components", [1, 2, 3])
            expression = data.get("expression", None)
            cell_type = data.get("cell", "triangle")
        else:
            components = [1, 2, 3]
            expression = None
            cell_type = "triangle"
        
        if cell_type == "triangle":
            cell = triangle
        elif cell_type == "tetrahedron":
            cell = tetrahedron
        elif cell_type == "quadrilateral":
            cell = quadrilateral
        else:
            cell = triangle
        
        x = SpatialCoordinate(cell)
        expr_env = {
            'x': x, 'components': components,
            'as_tensor': as_tensor, 'ListTensor': ListTensor,
            'Constant': Constant, 'sin': sin, 'cos': cos, 'exp': exp,
            'grad': grad, 'div': div, 'curl': curl
        }
        
        if expression:
            try:
                tensor = eval(expression, {"__builtins__": {}}, expr_env)
                return {"success": True, "result": f"Tensor from expression '{expression}': {tensor}", "error": None}
            except Exception as eval_error:
                return {"success": False, "result": None, "error": f"Expression evaluation error: {str(eval_error)}"}
        else:
            tensor = as_tensor(components)
            return {"success": True, "result": f"Tensor from components {components}: {tensor}", "error": None}
        
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="sobolev_space", description="Define a Sobolev space using UFL.")
def sobolev_space_tool(data):
    try:
        if isinstance(data, dict):
            space_name = data.get("name", "H1")
        else:
            space_name = "H1"
        
        if space_name == "H1":
            space = H1
        elif space_name == "H2":
            space = H2
        elif space_name == "HCurl":
            space = HCurl
        elif space_name == "HDiv":
            space = HDiv
        else:
            space = H1
        
        return {"success": True, "result": f"Sobolev space: {space}", "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="utility_function", description="Perform differential and algebraic operations using UFL with user expressions.")
def utility_function(data):
    try:
        if isinstance(data, dict):
            expression = data.get("expression", "x[0]")
            cell_type = data.get("cell", "triangle")
            degree = data.get("degree", 1)
        else:
            expression = str(data) if data else "x[0]"
            cell_type = "triangle"
            degree = 1
        
        if cell_type == "triangle":
            cell = triangle
        elif cell_type == "tetrahedron":
            cell = tetrahedron
        elif cell_type == "quadrilateral":
            cell = quadrilateral
        else:
            cell = triangle
        
        x = SpatialCoordinate(cell)
        V = FunctionSpace(cell, "CG", degree)
        u = TestFunction(V)
        v = TrialFunction(V)
        
        expr_env = {
            'x': x, 'u': u, 'v': v,
            'grad': grad, 'div': div, 'curl': curl,
            'sin': sin, 'cos': cos, 'exp': exp,
            'Constant': Constant, 'dx': dx, 'ds': ds,
            'TestFunction': TestFunction, 'TrialFunction': TrialFunction,
            'FunctionSpace': FunctionSpace
        }
        
        try:
            result_expr = eval(expression, {"__builtins__": {}}, expr_env)
            return {"success": True, "result": f"Expression '{expression}' evaluates to: {result_expr}", "error": None}
        except Exception as eval_error:
            return {"success": False, "result": None, "error": f"Expression evaluation error: {str(eval_error)}"}
        
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="core_computation", description="Perform computational operations using UFL with user expressions.")
def core_computation(data):
    try:
        if isinstance(data, dict):
            expression = data.get("expression", "x[0] + x[1]")
            cell_type = data.get("cell", "triangle")
            degree = data.get("degree", 1)
        else:
            expression = str(data) if data else "x[0] + x[1]"
            cell_type = "triangle"
            degree = 1
        
        if cell_type == "triangle":
            cell = triangle
        elif cell_type == "tetrahedron":
            cell = tetrahedron
        elif cell_type == "quadrilateral":
            cell = quadrilateral
        else:
            cell = triangle
        
        x = SpatialCoordinate(cell)
        V = FunctionSpace(cell, "CG", degree)
        u = TestFunction(V)
        v = TrialFunction(V)
        
        expr_env = {
            'x': x, 'u': u, 'v': v,
            'grad': grad, 'div': div, 'curl': curl,
            'sin': sin, 'cos': cos, 'exp': exp,
            'dx': dx, 'ds': ds, 'Constant': Constant,
            'as_tensor': as_tensor, 'ListTensor': ListTensor
        }
        
        try:
            result_expr = eval(expression, {"__builtins__": {}}, expr_env)
            return {"success": True, "result": f"Computation '{expression}' = {result_expr}", "error": None}
        except Exception as eval_error:
            return {"success": False, "result": None, "error": f"Expression evaluation error: {str(eval_error)}"}
        
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="algorithm_execution", description="Execute mathematical algorithms using UFL with user expressions.")
def algorithm_execution(data):
    try:
        if isinstance(data, dict):
            expression = data.get("expression", "x[0]**2")
            cell_type = data.get("cell", "triangle")
            degree = data.get("degree", 1)
        else:
            expression = str(data) if data else "x[0]**2"
            cell_type = "triangle"
            degree = 1
        
        if cell_type == "triangle":
            cell = triangle
        elif cell_type == "tetrahedron":
            cell = tetrahedron
        elif cell_type == "quadrilateral":
            cell = quadrilateral
        else:
            cell = triangle
        
        x = SpatialCoordinate(cell)
        V = FunctionSpace(cell, "CG", degree)
        u = TestFunction(V)
        v = TrialFunction(V)
        
        expr_env = {
            'x': x, 'u': u, 'v': v,
            'grad': grad, 'div': div, 'curl': curl,
            'sin': sin, 'cos': cos, 'exp': exp,
            'dx': dx, 'ds': ds, 'Constant': Constant,
            'as_tensor': as_tensor, 'ListTensor': ListTensor,
            'pow': pow
        }
        
        try:
            result_expr = eval(expression, {"__builtins__": {}}, expr_env)
            return {"success": True, "result": f"Algorithm '{expression}' executed: {result_expr}", "error": None}
        except Exception as eval_error:
            return {"success": False, "result": None, "error": f"Expression evaluation error: {str(eval_error)}"}
        
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="health_check", description="Check the health of the service.")
def health_check():
    try:
        return {"success": True, "result": "Service is healthy.", "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="version_info", description="Get the version information of the service.")
def version_info():
    try:
        return {"success": True, "result": "UFL Service v1.0.0", "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

def create_app():
    return mcp