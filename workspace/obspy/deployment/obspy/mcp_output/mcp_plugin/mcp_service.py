from fastmcp import FastMCP
from obspy.core.stream import Stream
from obspy.core.trace import Trace
from obspy.core.utcdatetime import UTCDateTime
from obspy.core.event import Event, Catalog
from obspy.core.inventory import Inventory
from obspy.signal.filter import bandpass
from obspy.signal.trigger import classic_sta_lta, trigger_onset
from obspy.taup import TauPyModel


mcp = FastMCP("obspy_service")


@mcp.tool(name="read_stream", description="Read seismic data into a Stream object.")
def read_stream(file_path: str) -> dict:
    """
    Reads seismic data from a file and returns a Stream object.

    Parameters:
        file_path (str): Path to the seismic data file.

    Returns:
        dict: Contains success (bool), result (Stream object), or error (str).
    """
    try:
        stream = Stream.read(file_path)
        return {"success": True, "result": stream, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="filter_stream", description="Apply bandpass filter to a Stream object.")
def filter_stream(stream: Stream, freqmin: float, freqmax: float, corners: int, zerophase: bool) -> dict:
    """
    Applies a bandpass filter to a Stream object.

    Parameters:
        stream (Stream): The Stream object to filter.
        freqmin (float): Minimum frequency for the bandpass filter.
        freqmax (float): Maximum frequency for the bandpass filter.
        corners (int): Number of corners for the filter.
        zerophase (bool): Whether to apply zero-phase filtering.

    Returns:
        dict: Contains success (bool), result (filtered Stream object), or error (str).
    """
    try:
        filtered_stream = stream.copy()
        filtered_stream.filter("bandpass", freqmin=freqmin, freqmax=freqmax, corners=corners, zerophase=zerophase)
        return {"success": True, "result": filtered_stream, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="detect_trigger", description="Detect triggers in a Stream object using STA/LTA algorithm.")
def detect_trigger(stream: Stream, sta: float, lta: float, threshold_on: float, threshold_off: float) -> dict:
    """
    Detects triggers in a Stream object using the STA/LTA algorithm.

    Parameters:
        stream (Stream): The Stream object to analyze.
        sta (float): Short-term average window length in seconds.
        lta (float): Long-term average window length in seconds.
        threshold_on (float): Trigger on threshold.
        threshold_off (float): Trigger off threshold.

    Returns:
        dict: Contains success (bool), result (list of trigger onsets), or error (str).
    """
    try:
        triggers = []
        for trace in stream:
            cft = classic_sta_lta(trace.data, int(sta * trace.stats.sampling_rate), int(lta * trace.stats.sampling_rate))
            onsets = trigger_onset(cft, threshold_on, threshold_off)
            triggers.append({"trace_id": trace.id, "onsets": onsets})
        return {"success": True, "result": triggers, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="calculate_travel_times", description="Calculate seismic travel times using TauPyModel.")
def calculate_travel_times(model_name: str, source_depth_km: float, distance_deg: float, phase_list: list) -> dict:
    """
    Calculates seismic travel times using the TauPyModel.

    Parameters:
        model_name (str): Name of the velocity model (e.g., "iasp91", "ak135").
        source_depth_km (float): Depth of the seismic source in kilometers.
        distance_deg (float): Distance between source and receiver in degrees.
        phase_list (list): List of seismic phases to calculate travel times for.

    Returns:
        dict: Contains success (bool), result (list of travel times), or error (str).
    """
    try:
        model = TauPyModel(model=model_name)
        arrivals = model.get_travel_times(source_depth_km=source_depth_km, distance_in_degree=distance_deg, phase_list=phase_list)
        travel_times = [{"phase": arrival.name, "time": arrival.time} for arrival in arrivals]
        return {"success": True, "result": travel_times, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="create_event_catalog", description="Create a seismic event catalog.")
def create_event_catalog(events: list) -> dict:
    """
    Creates a seismic event catalog.

    Parameters:
        events (list): List of Event objects to include in the catalog.

    Returns:
        dict: Contains success (bool), result (Catalog object), or error (str).
    """
    try:
        catalog = Catalog(events=events)
        return {"success": True, "result": catalog, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="create_inventory", description="Create a station inventory.")
def create_inventory(networks: list) -> dict:
    """
    Creates a station inventory.

    Parameters:
        networks (list): List of Network objects to include in the inventory.

    Returns:
        dict: Contains success (bool), result (Inventory object), or error (str).
    """
    try:
        inventory = Inventory(networks=networks, source="Generated Inventory")
        return {"success": True, "result": inventory, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="convert_to_utcdatetime", description="Convert a string to UTCDateTime.")
def convert_to_utcdatetime(date_string: str) -> dict:
    """
    Converts a date string to a UTCDateTime object.

    Parameters:
        date_string (str): Date string to convert.

    Returns:
        dict: Contains success (bool), result (UTCDateTime object), or error (str).
    """
    try:
        utc_datetime = UTCDateTime(date_string)
        return {"success": True, "result": utc_datetime, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


def create_app() -> FastMCP:
    """
    Creates and returns the FastMCP application instance.

    Returns:
        FastMCP: The FastMCP application instance.
    """
    return mcp