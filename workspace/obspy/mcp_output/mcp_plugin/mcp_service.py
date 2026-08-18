from fastmcp import FastMCP
from obspy import Stream, Trace, UTCDateTime, read, read_inventory, read_events
from obspy.clients.fdsn import Client
from obspy.signal import filter, cross_correlation, trigger, spectral_estimation
from obspy.taup import TauPyModel

mcp = FastMCP("obspy_service")

@mcp.tool(name="read_waveform", description="Read waveform data from a file.")
def read_waveform(file_path: str) -> dict:
    """
    Reads waveform data from a file.

    Parameters:
        file_path (str): Path to the waveform file.

    Returns:
        dict: Contains success, result (Stream object), or error message.
    """
    try:
        stream = read(file_path)
        return {"success": True, "result": stream}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="read_inventory", description="Read station metadata from a file.")
def read_station_metadata(file_path: str) -> dict:
    """
    Reads station metadata from a file.

    Parameters:
        file_path (str): Path to the station metadata file.

    Returns:
        dict: Contains success, result (Inventory object), or error message.
    """
    try:
        inventory = read_inventory(file_path)
        return {"success": True, "result": inventory}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="read_events", description="Read seismic event data from a file.")
def read_event_data(file_path: str) -> dict:
    """
    Reads seismic event data from a file.

    Parameters:
        file_path (str): Path to the event data file.

    Returns:
        dict: Contains success, result (Catalog object), or error message.
    """
    try:
        events = read_events(file_path)
        return {"success": True, "result": events}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="apply_filter", description="Apply a filter to a waveform stream.")
def apply_filter(stream: Stream, filter_type: str, freqmin: float, freqmax: float) -> dict:
    """
    Applies a filter to a waveform stream.

    Parameters:
        stream (Stream): ObsPy Stream object containing waveform data.
        filter_type (str): Type of filter to apply (e.g., 'bandpass', 'lowpass', 'highpass').
        freqmin (float): Minimum frequency for the filter.
        freqmax (float): Maximum frequency for the filter.

    Returns:
        dict: Contains success, result (filtered Stream object), or error message.
    """
    try:
        filtered_stream = stream.copy()
        filtered_stream.filter(filter_type, freqmin=freqmin, freqmax=freqmax)
        return {"success": True, "result": filtered_stream}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="cross_correlation", description="Perform cross-correlation on two traces.")
def perform_cross_correlation(trace1: Trace, trace2: Trace, shift: int) -> dict:
    """
    Performs cross-correlation on two traces.

    Parameters:
        trace1 (Trace): First ObsPy Trace object.
        trace2 (Trace): Second ObsPy Trace object.
        shift (int): Maximum shift in samples for cross-correlation.

    Returns:
        dict: Contains success, result (cross-correlation value), or error message.
    """
    try:
        correlation = cross_correlation.correlate(trace1.data, trace2.data, shift)
        return {"success": True, "result": correlation}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="trigger_detection", description="Detect triggers in a waveform trace.")
def detect_triggers(trace: Trace, algorithm: str, sta: float, lta: float, threshold_on: float, threshold_off: float) -> dict:
    """
    Detects triggers in a waveform trace using a specified algorithm.

    Parameters:
        trace (Trace): ObsPy Trace object containing waveform data.
        algorithm (str): Trigger algorithm to use (e.g., 'classic_sta_lta', 'recursive_sta_lta').
        sta (float): Short-term average window length in seconds.
        lta (float): Long-term average window length in seconds.
        threshold_on (float): Trigger on threshold.
        threshold_off (float): Trigger off threshold.

    Returns:
        dict: Contains success, result (list of triggers), or error message.
    """
    try:
        triggers = trigger.classic_sta_lta(trace.data, int(sta * trace.stats.sampling_rate), int(lta * trace.stats.sampling_rate))
        on_off = trigger.trigger_onset(triggers, threshold_on, threshold_off)
        return {"success": True, "result": on_off}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="spectral_analysis", description="Perform spectral analysis on a waveform trace.")
def perform_spectral_analysis(trace: Trace, method: str, nfft: int, overlap: int) -> dict:
    """
    Performs spectral analysis on a waveform trace.

    Parameters:
        trace (Trace): ObsPy Trace object containing waveform data.
        method (str): Spectral analysis method (e.g., 'welch', 'multitaper').
        nfft (int): Number of FFT points.
        overlap (int): Overlap between segments.

    Returns:
        dict: Contains success, result (spectral analysis data), or error message.
    """
    try:
        if method == "welch":
            result = spectral_estimation.psd(trace.data, nfft=nfft, overlap=overlap, sampling_rate=trace.stats.sampling_rate)
        elif method == "multitaper":
            result = spectral_estimation.psd_multitaper(trace.data, nfft=nfft, overlap=overlap, sampling_rate=trace.stats.sampling_rate)
        else:
            raise ValueError("Unsupported spectral analysis method.")
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="calculate_travel_times", description="Calculate seismic travel times using TauPy model.")
def calculate_travel_times(model_name: str, source_depth_km: float, distance_deg: float, phase_list: list) -> dict:
    """
    Calculates seismic travel times using TauPy model.

    Parameters:
        model_name (str): Name of the velocity model (e.g., 'iasp91', 'ak135').
        source_depth_km (float): Depth of the source in kilometers.
        distance_deg (float): Distance between source and receiver in degrees.
        phase_list (list): List of seismic phases to calculate travel times for.

    Returns:
        dict: Contains success, result (list of travel times), or error message.
    """
    try:
        model = TauPyModel(model=model_name)
        travel_times = model.get_travel_times(source_depth_km=source_depth_km, distance_in_degree=distance_deg, phase_list=phase_list)
        return {"success": True, "result": travel_times}
    except Exception as e:
        return {"success": False, "error": str(e)}

def create_app() -> FastMCP:
    """
    Creates and returns the FastMCP application instance.

    Returns:
        FastMCP: The FastMCP application instance.
    """
    return mcp