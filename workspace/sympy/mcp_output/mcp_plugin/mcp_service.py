import os
import sys

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP

from sympy.core import symbols, expand, Basic, Expr
from sympy.simplify import simplify
from sympy.solvers import solve, linsolve
from sympy.calculus import diff
from sympy.integrals import integrate
from sympy.polys import Poly, factor
from sympy.functions import sin, cos, exp
import random
from datetime import datetime
import time
from typing import Any, Dict

mcp = FastMCP("sympy_service")

active_streams: Dict[str, bool] = {}

@mcp.tool
def create_symbol(name):
    """Create symbolic variable"""
    return symbols(name)

@mcp.tool
def expand_expression(expr):
    """Expand expression"""
    return expand(expr)

@mcp.tool
def simplify_expression(expr):
    """Simplify expression"""
    return simplify(expr)

@mcp.tool
def solve_equation(equation, variable):
    """Solve equation"""
    return solve(equation, variable)

@mcp.tool
def solve_linear_system(system, variables):
    """Solve linear system of equations"""
    return linsolve(system, variables)

@mcp.tool
def differentiate(expr, variable):
    """Differentiate"""
    return diff(expr, variable)

@mcp.tool
def integrate_expression(expr, variable):
    """Integrate"""
    return integrate(expr, variable)

@mcp.tool
def create_polynomial(coeffs, variable):
    """Create polynomial"""
    return Poly(coeffs, variable)

@mcp.tool
def factor_polynomial(poly):
    """Factor polynomial"""
    return factor(poly)

@mcp.tool
def calculate_sin(angle):
    """Calculate sine value"""
    return sin(angle)

@mcp.tool
def calculate_cos(angle):
    """Calculate cosine value"""
    return cos(angle)

@mcp.tool
def calculate_exp(value):
    """Calculate exponential value"""
    return exp(value)

@mcp.tool
async def get_forecast(latitude: float, longitude: float) -> dict[str, Any]:
    """Get weather forecast for a location."""
    return {
        "latitude": latitude,
        "longitude": longitude,
        "forecast": {
            "temperature": random.uniform(-10.0, 35.0),
            "condition": random.choice(["sunny", "cloudy", "rainy", "snowy"]),
            "wind_speed": random.uniform(0.0, 25.0),
        }
    }

@mcp.tool
def start_monitoring() -> dict[str, Any]:
    """Start a long-running monitoring task"""
    task_id = f"monitor_{int(time.time())}"
    active_streams[task_id] = True
    return {"task_id": task_id, "status": "started"}

@mcp.tool
def get_current_metrics() -> dict[str, Any]:
    """Get current system metrics"""
    return {
        "timestamp": datetime.now().isoformat(),
        "cpu_percent": random.uniform(5.0, 15.0),
        "memory_percent": random.uniform(40.0, 60.0),
        "disk_io_read": random.randint(100, 500),
        "disk_io_write": random.randint(50, 200),
    }

@mcp.tool
def analyze_sentiment(text):
    """Analyze the sentiment of the given text and output a single word"""
    positive_words = ["good", "great", "excellent", "amazing", "wonderful", "fantastic", "love", "like", "happy", "joy"]
    negative_words = ["bad", "terrible", "awful", "hate", "dislike", "sad", "angry", "frustrated", "disappointed"]
    
    text_lower = text.lower()
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    if positive_count > negative_count:
        return "positive"
    elif negative_count > positive_count:
        return "negative"
    else:
        return "neutral"

@mcp.tool
def health_check():
    """Service health check"""
    return {"status": "healthy"}

@mcp.tool
def version_info():
    """Return service version information"""
    return {"version": "1.0.0"}

def create_app():
    """Create and return FastMCP application instance"""
    return mcp

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)