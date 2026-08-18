import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Necessary imports
from fastmcp import FastMCP
from src.dateutil.relativedelta import relativedelta
from src.dateutil.rrule import rrule, rruleset
from src.dateutil.easter import easter
from src.dateutil.zoneinfo import get_zonefile_instance, ZoneInfoFile

# Create MCP instance
mcp = FastMCP("dateutil_service")

@mcp.tool(name="calculate_relative_date", description="Perform relative date arithmetic.")
def calculate_relative_date(year: int, month: int, day: int, delta_years: int, delta_months: int, delta_days: int) -> dict:
    """
    Calculate a new date by applying relative delta adjustments.

    Parameters:
        year (int): The base year.
        month (int): The base month.
        day (int): The base day.
        delta_years (int): Number of years to add/subtract.
        delta_months (int): Number of months to add/subtract.
        delta_days (int): Number of days to add/subtract.

    Returns:
        dict: A dictionary containing success, result (new date), or error.
    """
    try:
        base_date = datetime.date(year, month, day)
        delta = relativedelta(years=delta_years, months=delta_months, days=delta_days)
        new_date = base_date + delta
        return {"success": True, "result": str(new_date), "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="generate_recurrence_rule", description="Generate recurrence rules based on iCalendar RFC 5545.")
def generate_recurrence_rule(freq: str, count: int, interval: int) -> dict:
    """
    Generate a list of recurrence dates based on specified rules.

    Parameters:
        freq (str): Frequency of recurrence (e.g., 'DAILY', 'WEEKLY', 'MONTHLY').
        count (int): Number of occurrences.
        interval (int): Interval between occurrences.

    Returns:
        dict: A dictionary containing success, result (list of dates), or error.
    """
    try:
        rule = rrule(freq=freq, count=count, interval=interval)
        dates = list(rule)
        return {"success": True, "result": [str(date) for date in dates], "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="calculate_easter_date", description="Calculate the date of Easter Sunday for a given year.")
def calculate_easter_date(year: int) -> dict:
    """
    Calculate the date of Easter Sunday for a given year.

    Parameters:
        year (int): The year for which to calculate Easter.

    Returns:
        dict: A dictionary containing success, result (Easter date), or error.
    """
    try:
        easter_date = easter(year)
        return {"success": True, "result": str(easter_date), "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="get_timezone_metadata", description="Retrieve timezone metadata from the database.")
def get_timezone_metadata() -> dict:
    """
    Retrieve metadata from the timezone database.

    Returns:
        dict: A dictionary containing success, result (metadata), or error.
    """
    try:
        zonefile_instance = get_zonefile_instance()
        metadata = zonefile_instance.metadata
        return {"success": True, "result": metadata, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

def create_app() -> FastMCP:
    """
    Create and return the FastMCP application instance.

    Returns:
        FastMCP: The MCP application instance.
    """
    return mcp