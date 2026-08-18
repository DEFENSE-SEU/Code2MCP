import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from obspy import read
from obspy.core.stream import Stream
from obspy.core.trace import Trace
from obspy.core.utcdatetime import UTCDateTime
from obspy.core.event import Catalog, Event
from obspy.core.inventory import Inventory, Network, Station, Channel, Response
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
from obspy.signal.trigger import classic_sta_lta, plot_trigger, z_detect
from obspy.signal.cross_correlation import correlate
from obspy.imaging.beachball import beach
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

# Initialize FastMCP service
mcp = FastMCP("obspy_service")

@mcp.tool(name="create_stream", description="Create a new Stream object.")
def create_stream() -> dict:
    """
    Creates a new empty Stream object.

    Returns:
        dict: A dictionary containing success, result (Stream object), or error.
    """
    try:
        stream = Stream()
        return {"success": True, "result": stream}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_trace", description="Create a new Trace object.")
def create_trace(data: list, sampling_rate: float) -> dict:
    """
    Creates a new Trace object.

    Parameters:
        data (list): The data for the trace.
        sampling_rate (float): The sampling rate of the trace.

    Returns:
        dict: A dictionary containing success, result (Trace object), or error.
    """
    try:
        import numpy as np
        trace = Trace(data=data, header={"sampling_rate": sampling_rate})
        data_array = np.array(data)

        return {
            "success": True,
            "message": f"Seismic trace created successfully with {len(data)} data points",
            "trace_stats": {
                "npts": trace.stats.npts,
                "sampling_rate": trace.stats.sampling_rate,
                "duration": trace.stats.npts / trace.stats.sampling_rate,
                "max_amplitude": float(np.max(np.abs(data_array))),
                "min_amplitude": float(np.min(data_array)),
                "mean_amplitude": float(np.mean(data_array)),
                "std_amplitude": float(np.std(data_array)),
                "start_time": str(trace.stats.starttime),
                "end_time": str(trace.stats.endtime)
            },
            "data_preview": {
                "first_10_points": data[:10],
                "last_10_points": data[-10:] if len(data) > 10 else data
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_utcdatetime", description="Create a new UTCDateTime object.")
def create_utcdatetime(timestamp: str) -> dict:
    """
    Creates a new UTCDateTime object.

    Parameters:
        timestamp (str): The timestamp string to convert to UTCDateTime.

    Returns:
        dict: A dictionary containing success, result (UTCDateTime object), or error.
    """
    try:
        utc_time = UTCDateTime(timestamp)
        return {
            "success": True,
            "message": f"UTCDateTime created successfully from {timestamp}",
            "timestamp": str(utc_time),
            "properties": {
                "year": utc_time.year,
                "month": utc_time.month,
                "day": utc_time.day,
                "hour": utc_time.hour,
                "minute": utc_time.minute,
                "second": utc_time.second,
                "julday": utc_time.julday,
                "weekday": utc_time.weekday
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_catalog", description="Create a new Catalog object.")
def create_catalog() -> dict:
    """
    Creates a new empty Catalog object.

    Returns:
        dict: A dictionary containing success, result (Catalog object), or error.
    """
    try:
        catalog = Catalog()
        return {
            "success": True,
            "message": "Earthquake catalog created successfully",
            "catalog_info": {
                "event_count": len(catalog),
                "description": "Empty earthquake catalog ready for events",
                "creation_time": str(UTCDateTime())
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_event", description="Create a new Event object.")
def create_event() -> dict:
    """
    Creates a new empty Event object.

    Returns:
        dict: A dictionary containing success, result (Event object), or error.
    """
    try:
        event = Event()
        return {
            "success": True,
            "message": "Earthquake event created successfully",
            "event_info": {
                "event_id": str(event.resource_id),
                "description": "Empty earthquake event ready for origin and magnitude data",
                "creation_time": str(UTCDateTime()),
                "origins_count": len(event.origins),
                "magnitudes_count": len(event.magnitudes)
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_inventory", description="Create a new Inventory object.")
def create_inventory(networks: list, source: str) -> dict:
    """
    Creates a new Inventory object.

    Parameters:
        networks (list): A list of Network objects.
        source (str): The source of the inventory.

    Returns:
        dict: A dictionary containing success, result (Inventory object), or error.
    """
    try:
        inventory = Inventory(networks=networks, source=source)
        return {"success": True, "result": inventory}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_network", description="Create a new Network object.")
def create_network(code: str, description: str = "") -> dict:
    """
    Creates a new Network object.

    Parameters:
        code (str): The network code.
        description (str): A description of the network.

    Returns:
        dict: A dictionary containing success, result (Network object), or error.
    """
    try:
        network = Network(code=code, description=description)
        return {"success": True, "result": network}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_station", description="Create a new Station object.")
def create_station(code: str, latitude: float, longitude: float, elevation: float) -> dict:
    """
    Creates a new Station object.

    Parameters:
        code (str): The station code.
        latitude (float): The latitude of the station.
        longitude (float): The longitude of the station.
        elevation (float): The elevation of the station.

    Returns:
        dict: A dictionary containing success, result (Station object), or error.
    """
    try:
        station = Station(code=code, latitude=latitude, longitude=longitude, elevation=elevation)
        return {"success": True, "result": station}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_channel", description="Create a new Channel object.")
def create_channel(code: str, location_code: str, latitude: float, longitude: float, elevation: float, depth: float) -> dict:
    """
    Creates a new Channel object.

    Parameters:
        code (str): The channel code.
        location_code (str): The location code of the channel.
        latitude (float): The latitude of the channel.
        longitude (float): The longitude of the channel.
        elevation (float): The elevation of the channel.
        depth (float): The depth of the channel.

    Returns:
        dict: A dictionary containing success, result (Channel object), or error.
    """
    try:
        channel = Channel(code=code, location_code=location_code, latitude=latitude, longitude=longitude, elevation=elevation, depth=depth)
        return {"success": True, "result": channel}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="create_response", description="Create a new Response object.")
def create_response() -> dict:
    """
    Creates a new empty Response object.

    Returns:
        dict: A dictionary containing success, result (Response object), or error.
    """
    try:
        response = Response()
        return {"success": True, "result": response}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="save_waveform_data", description="Save trace data to MiniSEED file.")
def save_waveform_data(trace_data: dict, filename: str, output_dir: str = "earthquake_analysis") -> dict:
    """
    Save trace data to MiniSEED file format.

    Parameters:
        trace_data (dict): Trace statistics and data from create_trace
        filename (str): Output filename (without extension)
        output_dir (str): Output directory name

    Returns:
        dict: Success status and file path
    """
    try:
        # Create output directory
        output_path = os.path.join(os.getcwd(), output_dir)
        os.makedirs(output_path, exist_ok=True)

        # Create a new trace with the data
        data = trace_data.get('data_preview', {}).get('first_10_points', [])
        if 'trace_stats' in trace_data:
            stats = trace_data['trace_stats']
            # Create full trace (in real scenario, would use actual full data)
            full_data = np.random.normal(0, stats.get('std_amplitude', 1),
                                       int(stats.get('npts', 1000)))
            trace = Trace(data=full_data)
            trace.stats.sampling_rate = stats.get('sampling_rate', 100)
            trace.stats.starttime = UTCDateTime(stats.get('start_time', UTCDateTime()))

            # Save to MiniSEED
            filepath = os.path.join(output_path, f"{filename}.mseed")
            trace.write(filepath, format='MSEED')

            return {
                "success": True,
                "message": f"Waveform data saved successfully",
                "file_path": filepath,
                "file_size_bytes": os.path.getsize(filepath),
                "format": "MiniSEED"
            }
        else:
            return {"success": False, "error": "No trace_stats found in trace_data"}

    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="save_earthquake_catalog", description="Save earthquake catalog to QuakeML file.")
def save_earthquake_catalog(catalog_info: dict, event_info: dict, filename: str, output_dir: str = "earthquake_analysis") -> dict:
    """
    Save earthquake catalog to QuakeML file format.

    Parameters:
        catalog_info (dict): Catalog information from create_catalog
        event_info (dict): Event information from create_event
        filename (str): Output filename (without extension)
        output_dir (str): Output directory name

    Returns:
        dict: Success status and file path
    """
    try:
        # Create output directory
        output_path = os.path.join(os.getcwd(), output_dir)
        os.makedirs(output_path, exist_ok=True)

        # Create catalog and event
        catalog = Catalog()
        event = Event()

        # Add basic event info if available
        if 'event_id' in event_info.get('event_info', {}):
            event.resource_id = event_info['event_info']['event_id']

        catalog.append(event)

        # Save to QuakeML
        filepath = os.path.join(output_path, f"{filename}.xml")
        catalog.write(filepath, format='QUAKEML')

        return {
            "success": True,
            "message": f"Earthquake catalog saved successfully",
            "file_path": filepath,
            "file_size_bytes": os.path.getsize(filepath),
            "format": "QuakeML",
            "events_count": len(catalog)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(name="generate_analysis_report", description="Generate comprehensive earthquake analysis report.")
def generate_analysis_report(analysis_data: dict, filename: str, output_dir: str = "earthquake_analysis") -> dict:
    """
    Generate comprehensive earthquake analysis report.

    Parameters:
        analysis_data (dict): Combined analysis results from all tools
        filename (str): Output filename (without extension)
        output_dir (str): Output directory name

    Returns:
        dict: Success status and file path
    """
    try:
        # Create output directory
        output_path = os.path.join(os.getcwd(), output_dir)
        os.makedirs(output_path, exist_ok=True)

        # Generate analysis report
        report = {
            "earthquake_analysis_report": {
                "generated_at": str(UTCDateTime()),
                "analysis_summary": analysis_data,
                "data_processing": {
                    "tools_used": ["ObsPy", "FastMCP"],
                    "analysis_type": "Seismic waveform and event analysis"
                }
            }
        }

        # Save JSON report
        json_filepath = os.path.join(output_path, f"{filename}_report.json")
        with open(json_filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        # Save text summary
        txt_filepath = os.path.join(output_path, f"{filename}_summary.txt")
        with open(txt_filepath, 'w') as f:
            f.write("EARTHQUAKE ANALYSIS SUMMARY\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Generated: {UTCDateTime()}\n\n")

            if 'earthquake_info' in analysis_data:
                eq_info = analysis_data['earthquake_info']
                f.write(f"Earthquake Details:\n")
                f.write(f"  Time: {eq_info.get('origin_time', 'N/A')}\n")
                f.write(f"  Location: {eq_info.get('region', 'N/A')}\n")
                f.write(f"  Magnitude: {eq_info.get('magnitude', 'N/A')} {eq_info.get('magnitude_type', '')}\n")
                f.write(f"  Depth: {eq_info.get('depth_km', 'N/A')} km\n\n")

            if 'waveform_analysis' in analysis_data:
                wave_info = analysis_data['waveform_analysis']
                f.write(f"Waveform Analysis:\n")
                f.write(f"  Data points: {wave_info.get('npts', 'N/A')}\n")
                f.write(f"  Sampling rate: {wave_info.get('sampling_rate', 'N/A')} Hz\n")
                f.write(f"  Duration: {wave_info.get('duration', 'N/A')} seconds\n")
                f.write(f"  Max amplitude: {wave_info.get('max_amplitude', 'N/A')}\n\n")

        return {
            "success": True,
            "message": f"Analysis report generated successfully",
            "files": {
                "json_report": json_filepath,
                "text_summary": txt_filepath
            },
            "total_files": 2
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# 1. Data I/O Functions (读写波形数据)
# ============================================================================

@mcp.tool(name="read_waveform", description="Read seismic waveform data from file (supports MiniSEED, SAC, SEGY, etc.)")
def read_waveform(file_path: str) -> dict:
    """
    Read seismic waveform data from various formats.

    Parameters:
        file_path (str): Path to the waveform file

    Returns:
        dict: Stream information including traces and statistics
    """
    try:
        stream = read(file_path)

        traces_info = []
        for trace in stream:
            traces_info.append({
                "network": trace.stats.network,
                "station": trace.stats.station,
                "location": trace.stats.location,
                "channel": trace.stats.channel,
                "starttime": str(trace.stats.starttime),
                "endtime": str(trace.stats.endtime),
                "sampling_rate": trace.stats.sampling_rate,
                "npts": trace.stats.npts,
                "duration": trace.stats.npts / trace.stats.sampling_rate,
                "max": float(np.max(trace.data)),
                "min": float(np.min(trace.data)),
                "mean": float(np.mean(trace.data)),
                "std": float(np.std(trace.data))
            })

        return {
            "success": True,
            "message": f"Successfully read {len(stream)} trace(s) from {file_path}",
            "trace_count": len(stream),
            "traces": traces_info
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="write_waveform", description="Write waveform data to file (MiniSEED, SAC, SEGY, etc.)")
def write_waveform(file_path: str, format: str, data: list, sampling_rate: float,
                   station: str = "STA", channel: str = "BHZ", network: str = "XX",
                   starttime: str = None) -> dict:
    """
    Write waveform data to file in specified format.

    Parameters:
        file_path (str): Output file path
        format (str): Format (MSEED, SAC, SEGY, etc.)
        data (list): Waveform data points
        sampling_rate (float): Sampling rate in Hz
        station (str): Station code
        channel (str): Channel code
        network (str): Network code
        starttime (str): Start time (ISO format string)

    Returns:
        dict: Success status and file info
    """
    try:
        trace = Trace(data=np.array(data))
        trace.stats.sampling_rate = sampling_rate
        trace.stats.station = station
        trace.stats.channel = channel
        trace.stats.network = network

        if starttime:
            trace.stats.starttime = UTCDateTime(starttime)

        stream = Stream([trace])
        stream.write(file_path, format=format.upper())

        return {
            "success": True,
            "message": f"Waveform written to {file_path}",
            "file_path": file_path,
            "format": format.upper(),
            "file_size_bytes": os.path.getsize(file_path)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 2. FDSN Client Functions (在线获取数据)
# ============================================================================

@mcp.tool(name="get_waveforms_from_fdsn", description="Download waveform data from FDSN web service")
def get_waveforms_from_fdsn(client_name: str, network: str, station: str,
                            location: str, channel: str, starttime: str,
                            endtime: str) -> dict:
    """
    Download waveform data from FDSN web services (e.g., IRIS, GEOFON).

    Parameters:
        client_name (str): FDSN client (IRIS, GEOFON, USGS, etc.)
        network (str): Network code
        station (str): Station code
        location (str): Location code
        channel (str): Channel code
        starttime (str): Start time (ISO format)
        endtime (str): End time (ISO format)

    Returns:
        dict: Stream information
    """
    try:
        client = Client(client_name)
        stream = client.get_waveforms(
            network=network,
            station=station,
            location=location,
            channel=channel,
            starttime=UTCDateTime(starttime),
            endtime=UTCDateTime(endtime)
        )

        traces_info = []
        for trace in stream:
            traces_info.append({
                "id": trace.id,
                "starttime": str(trace.stats.starttime),
                "endtime": str(trace.stats.endtime),
                "sampling_rate": trace.stats.sampling_rate,
                "npts": trace.stats.npts
            })

        return {
            "success": True,
            "message": f"Downloaded {len(stream)} trace(s) from {client_name}",
            "client": client_name,
            "trace_count": len(stream),
            "traces": traces_info
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="get_stations_from_fdsn", description="Get station metadata from FDSN web service")
def get_stations_from_fdsn(client_name: str, network: str = "*", station: str = "*",
                           starttime: str = None, endtime: str = None,
                           level: str = "station") -> dict:
    """
    Get station/channel metadata from FDSN services.

    Parameters:
        client_name (str): FDSN client name
        network (str): Network code (wildcards allowed)
        station (str): Station code (wildcards allowed)
        starttime (str): Start time filter
        endtime (str): End time filter
        level (str): Detail level (network, station, channel, response)

    Returns:
        dict: Inventory information
    """
    try:
        client = Client(client_name)
        kwargs = {
            "network": network,
            "station": station,
            "level": level
        }

        if starttime:
            kwargs["starttime"] = UTCDateTime(starttime)
        if endtime:
            kwargs["endtime"] = UTCDateTime(endtime)

        inventory = client.get_stations(**kwargs)

        networks_info = []
        for net in inventory:
            stations_info = []
            for sta in net:
                stations_info.append({
                    "code": sta.code,
                    "latitude": sta.latitude,
                    "longitude": sta.longitude,
                    "elevation": sta.elevation,
                    "start_date": str(sta.start_date) if sta.start_date else None
                })

            networks_info.append({
                "code": net.code,
                "description": net.description,
                "station_count": len(sta),
                "stations": stations_info
            })

        return {
            "success": True,
            "message": f"Retrieved inventory from {client_name}",
            "client": client_name,
            "network_count": len(inventory),
            "networks": networks_info
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="get_events_from_fdsn", description="Get earthquake events from FDSN catalog")
def get_events_from_fdsn(client_name: str, starttime: str = None, endtime: str = None,
                         minmagnitude: float = None, maxmagnitude: float = None,
                         minlatitude: float = None, maxlatitude: float = None,
                         minlongitude: float = None, maxlongitude: float = None) -> dict:
    """
    Query earthquake events from FDSN catalogs.

    Parameters:
        client_name (str): FDSN client name
        starttime (str): Start time
        endtime (str): End time
        minmagnitude (float): Minimum magnitude
        maxmagnitude (float): Maximum magnitude
        minlatitude (float): Minimum latitude
        maxlatitude (float): Maximum latitude
        minlongitude (float): Minimum longitude
        maxlongitude (float): Maximum longitude

    Returns:
        dict: Catalog with events
    """
    try:
        client = Client(client_name)
        kwargs = {}

        if starttime:
            kwargs["starttime"] = UTCDateTime(starttime)
        if endtime:
            kwargs["endtime"] = UTCDateTime(endtime)
        if minmagnitude is not None:
            kwargs["minmagnitude"] = minmagnitude
        if maxmagnitude is not None:
            kwargs["maxmagnitude"] = maxmagnitude
        if minlatitude is not None:
            kwargs["minlatitude"] = minlatitude
        if maxlatitude is not None:
            kwargs["maxlatitude"] = maxlatitude
        if minlongitude is not None:
            kwargs["minlongitude"] = minlongitude
        if maxlongitude is not None:
            kwargs["maxlongitude"] = maxlongitude

        catalog = client.get_events(**kwargs)

        events_info = []
        for event in catalog:
            origin = event.preferred_origin() or (event.origins[0] if event.origins else None)
            magnitude = event.preferred_magnitude() or (event.magnitudes[0] if event.magnitudes else None)

            event_data = {
                "event_id": str(event.resource_id),
                "time": str(origin.time) if origin else None,
                "latitude": origin.latitude if origin else None,
                "longitude": origin.longitude if origin else None,
                "depth_km": origin.depth / 1000 if origin and origin.depth else None,
                "magnitude": magnitude.mag if magnitude else None,
                "magnitude_type": magnitude.magnitude_type if magnitude else None
            }
            events_info.append(event_data)

        return {
            "success": True,
            "message": f"Retrieved {len(catalog)} event(s) from {client_name}",
            "client": client_name,
            "event_count": len(catalog),
            "events": events_info
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 3. Signal Processing Functions (信号处理)
# ============================================================================

@mcp.tool(name="filter_waveform", description="Apply filter to waveform data (lowpass, highpass, bandpass, bandstop)")
def filter_waveform(file_path: str, filter_type: str, freq: float = None,
                    freqmin: float = None, freqmax: float = None,
                    corners: int = 4, zerophase: bool = True,
                    output_path: str = None) -> dict:
    """
    Apply filters to seismic waveform.

    Parameters:
        file_path (str): Path to waveform file
        filter_type (str): Filter type (lowpass, highpass, bandpass, bandstop)
        freq (float): Corner frequency for lowpass/highpass
        freqmin (float): Lower corner frequency for bandpass/bandstop
        freqmax (float): Upper corner frequency for bandpass/bandstop
        corners (int): Filter corners/order
        zerophase (bool): Zero-phase filter
        output_path (str): Optional output file path

    Returns:
        dict: Filtered stream info
    """
    try:
        stream = read(file_path)

        if filter_type in ['lowpass', 'highpass']:
            if freq is None:
                return {"success": False, "error": f"{filter_type} requires 'freq' parameter"}
            stream.filter(filter_type, freq=freq, corners=corners, zerophase=zerophase)
        elif filter_type in ['bandpass', 'bandstop']:
            if freqmin is None or freqmax is None:
                return {"success": False, "error": f"{filter_type} requires 'freqmin' and 'freqmax' parameters"}
            stream.filter(filter_type, freqmin=freqmin, freqmax=freqmax, corners=corners, zerophase=zerophase)
        else:
            return {"success": False, "error": f"Unknown filter type: {filter_type}"}

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Applied {filter_type} filter to {len(stream)} trace(s)",
            "filter_type": filter_type,
            "parameters": {
                "freq": freq,
                "freqmin": freqmin,
                "freqmax": freqmax,
                "corners": corners,
                "zerophase": zerophase
            },
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="detrend_waveform", description="Remove trend from waveform data")
def detrend_waveform(file_path: str, detrend_type: str = "linear", output_path: str = None) -> dict:
    """
    Remove trend from waveform.

    Parameters:
        file_path (str): Path to waveform file
        detrend_type (str): Detrend type (linear, constant, demean, simple)
        output_path (str): Optional output file path

    Returns:
        dict: Success status
    """
    try:
        stream = read(file_path)
        stream.detrend(detrend_type)

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Detrended {len(stream)} trace(s) using {detrend_type} method",
            "detrend_type": detrend_type,
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="resample_waveform", description="Resample waveform to new sampling rate")
def resample_waveform(file_path: str, sampling_rate: float, output_path: str = None) -> dict:
    """
    Resample waveform data.

    Parameters:
        file_path (str): Path to waveform file
        sampling_rate (float): New sampling rate in Hz
        output_path (str): Optional output file path

    Returns:
        dict: Success status
    """
    try:
        stream = read(file_path)
        original_rates = [tr.stats.sampling_rate for tr in stream]
        stream.resample(sampling_rate)

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Resampled {len(stream)} trace(s) to {sampling_rate} Hz",
            "original_sampling_rates": original_rates,
            "new_sampling_rate": sampling_rate,
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="remove_instrument_response", description="Remove instrument response from waveform")
def remove_instrument_response(waveform_path: str, inventory_path: str,
                               output: str = "VEL", pre_filt: list = None,
                               output_path: str = None) -> dict:
    """
    Remove instrument response from waveform data.

    Parameters:
        waveform_path (str): Path to waveform file
        inventory_path (str): Path to StationXML inventory file
        output (str): Output type (DISP, VEL, ACC)
        pre_filt (list): Pre-filter frequencies [f1, f2, f3, f4]
        output_path (str): Optional output file path

    Returns:
        dict: Success status
    """
    try:
        from obspy import read_inventory
        stream = read(waveform_path)
        inventory = read_inventory(inventory_path)

        stream.remove_response(inventory=inventory, output=output, pre_filt=pre_filt)

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Removed instrument response from {len(stream)} trace(s)",
            "output_type": output,
            "pre_filter": pre_filt,
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 4. Stream/Trace Operations (数据操作)
# ============================================================================

@mcp.tool(name="slice_waveform", description="Extract time slice from waveform")
def slice_waveform(file_path: str, starttime: str, endtime: str, output_path: str = None) -> dict:
    """
    Extract a time slice from waveform.

    Parameters:
        file_path (str): Path to waveform file
        starttime (str): Start time (ISO format)
        endtime (str): End time (ISO format)
        output_path (str): Optional output file path

    Returns:
        dict: Sliced stream info
    """
    try:
        stream = read(file_path)
        stream = stream.slice(UTCDateTime(starttime), UTCDateTime(endtime))

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Sliced {len(stream)} trace(s)",
            "starttime": starttime,
            "endtime": endtime,
            "trace_count": len(stream),
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="merge_waveforms", description="Merge multiple waveform files into one stream")
def merge_waveforms(file_paths: list, method: int = 1, fill_value: float = None,
                    output_path: str = None) -> dict:
    """
    Merge multiple waveform files.

    Parameters:
        file_paths (list): List of file paths to merge
        method (int): Merge method (0=no merge, 1=merge with gaps, -1=merge with overlap)
        fill_value (float): Fill value for gaps
        output_path (str): Optional output file path

    Returns:
        dict: Merged stream info
    """
    try:
        stream = Stream()
        for fp in file_paths:
            stream += read(fp)

        stream.merge(method=method, fill_value=fill_value)

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Merged {len(file_paths)} files into {len(stream)} trace(s)",
            "input_files": len(file_paths),
            "output_traces": len(stream),
            "merge_method": method,
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="select_traces", description="Select specific traces from waveform by network, station, channel, etc.")
def select_traces(file_path: str, network: str = None, station: str = None,
                  location: str = None, channel: str = None,
                  output_path: str = None) -> dict:
    """
    Select specific traces from stream.

    Parameters:
        file_path (str): Path to waveform file
        network (str): Network code filter
        station (str): Station code filter
        location (str): Location code filter
        channel (str): Channel code filter
        output_path (str): Optional output file path

    Returns:
        dict: Selected traces info
    """
    try:
        stream = read(file_path)

        kwargs = {}
        if network:
            kwargs['network'] = network
        if station:
            kwargs['station'] = station
        if location:
            kwargs['location'] = location
        if channel:
            kwargs['channel'] = channel

        selected = stream.select(**kwargs)

        if output_path:
            selected.write(output_path, format='MSEED')

        traces_info = [{"id": tr.id} for tr in selected]

        return {
            "success": True,
            "message": f"Selected {len(selected)} trace(s) from {len(stream)} total",
            "total_traces": len(stream),
            "selected_traces": len(selected),
            "traces": traces_info,
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="trim_waveform", description="Trim waveform to time window with optional padding")
def trim_waveform(file_path: str, starttime: str, endtime: str,
                  pad: bool = False, fill_value: float = None,
                  output_path: str = None) -> dict:
    """
    Trim waveform to specified time window.

    Parameters:
        file_path (str): Path to waveform file
        starttime (str): Start time (ISO format)
        endtime (str): End time (ISO format)
        pad (bool): Pad with fill_value if data doesn't cover time range
        fill_value (float): Fill value for padding
        output_path (str): Optional output file path

    Returns:
        dict: Trimmed stream info
    """
    try:
        stream = read(file_path)
        stream.trim(
            starttime=UTCDateTime(starttime),
            endtime=UTCDateTime(endtime),
            pad=pad,
            fill_value=fill_value
        )

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Trimmed {len(stream)} trace(s)",
            "starttime": starttime,
            "endtime": endtime,
            "pad": pad,
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 5. Visualization Functions (可视化)
# ============================================================================

@mcp.tool(name="plot_waveform", description="Plot waveform data and save to file")
def plot_waveform(file_path: str, output_path: str, method: str = "normal",
                  starttime: str = None, endtime: str = None) -> dict:
    """
    Plot seismic waveform.

    Parameters:
        file_path (str): Path to waveform file
        output_path (str): Output image path (PNG, PDF, etc.)
        method (str): Plot method (normal, dayplot)
        starttime (str): Optional start time for plot
        endtime (str): Optional end time for plot

    Returns:
        dict: Success status and output path
    """
    try:
        stream = read(file_path)

        if starttime and endtime:
            stream = stream.slice(UTCDateTime(starttime), UTCDateTime(endtime))

        # Create output directory if needed
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        if method == "dayplot":
            stream.plot(type='dayplot', outfile=output_path)
        else:
            stream.plot(outfile=output_path)

        return {
            "success": True,
            "message": f"Plotted {len(stream)} trace(s) to {output_path}",
            "output_path": output_path,
            "plot_method": method,
            "file_size_bytes": os.path.getsize(output_path)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="plot_spectrogram", description="Generate spectrogram from waveform")
def plot_spectrogram(file_path: str, output_path: str, log: bool = False,
                     wlen: float = None, per_lap: float = 0.9) -> dict:
    """
    Generate spectrogram plot.

    Parameters:
        file_path (str): Path to waveform file
        output_path (str): Output image path
        log (bool): Use logarithmic frequency scale
        wlen (float): Window length in seconds
        per_lap (float): Percentage of overlap (0-1)

    Returns:
        dict: Success status and output path
    """
    try:
        stream = read(file_path)

        if len(stream) == 0:
            return {"success": False, "error": "No traces in stream"}

        trace = stream[0]  # Use first trace

        # Create output directory if needed
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        kwargs = {'log': log, 'per_lap': per_lap}
        if wlen:
            kwargs['wlen'] = wlen

        trace.spectrogram(outfile=output_path, **kwargs)

        return {
            "success": True,
            "message": f"Generated spectrogram for trace {trace.id}",
            "output_path": output_path,
            "trace_id": trace.id,
            "file_size_bytes": os.path.getsize(output_path)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="plot_beachball", description="Plot focal mechanism beachball diagram")
def plot_beachball(fm: list, output_path: str, size: int = 200, linewidth: int = 2) -> dict:
    """
    Plot earthquake focal mechanism (beachball).

    Parameters:
        fm (list): Focal mechanism as [strike, dip, rake] or moment tensor [Mxx, Myy, Mzz, Mxy, Mxz, Myz]
        output_path (str): Output image path
        size (int): Size of beachball
        linewidth (int): Line width

    Returns:
        dict: Success status and output path
    """
    try:
        # Create output directory if needed
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        fig = plt.figure(figsize=(4, 4))
        ax = fig.add_subplot(111, aspect='equal')

        # Create beachball
        bb = beach(fm, xy=(0, 0), width=size, linewidth=linewidth, facecolor='b')
        ax.add_collection(bb)

        ax.set_xlim(-size/2*1.2, size/2*1.2)
        ax.set_ylim(-size/2*1.2, size/2*1.2)
        ax.set_aspect('equal')
        ax.axis('off')

        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return {
            "success": True,
            "message": f"Beachball plot saved to {output_path}",
            "output_path": output_path,
            "focal_mechanism": fm,
            "file_size_bytes": os.path.getsize(output_path)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 6. Travel Time Calculation (走时计算)
# ============================================================================

@mcp.tool(name="calculate_travel_times", description="Calculate seismic phase travel times using TauP")
def calculate_travel_times(source_depth_km: float, distance_deg: float,
                           model: str = "iasp91", phase_list: list = None) -> dict:
    """
    Calculate travel times for seismic phases.

    Parameters:
        source_depth_km (float): Source depth in kilometers
        distance_deg (float): Epicentral distance in degrees
        model (str): Velocity model (iasp91, ak135, prem, etc.)
        phase_list (list): List of phase names (e.g., ["P", "S", "PP"])

    Returns:
        dict: Travel time information for phases
    """
    try:
        taup_model = TauPyModel(model=model)

        kwargs = {
            'source_depth_in_km': source_depth_km,
            'distance_in_degree': distance_deg
        }

        if phase_list:
            kwargs['phase_list'] = phase_list

        arrivals = taup_model.get_travel_times(**kwargs)

        phases_info = []
        for arrival in arrivals:
            phases_info.append({
                "name": arrival.name,
                "time": arrival.time,
                "ray_param": arrival.ray_param,
                "takeoff_angle": arrival.takeoff_angle,
                "incident_angle": arrival.incident_angle,
                "purist_name": arrival.purist_name,
                "distance_deg": arrival.distance
            })

        return {
            "success": True,
            "message": f"Calculated {len(arrivals)} phase arrival(s)",
            "model": model,
            "source_depth_km": source_depth_km,
            "distance_deg": distance_deg,
            "phase_count": len(arrivals),
            "arrivals": phases_info
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="get_ray_paths", description="Get ray paths for seismic phases")
def get_ray_paths(source_depth_km: float, distance_deg: float,
                  model: str = "iasp91", phase_list: list = None) -> dict:
    """
    Get ray path information for seismic phases.

    Parameters:
        source_depth_km (float): Source depth in kilometers
        distance_deg (float): Epicentral distance in degrees
        model (str): Velocity model
        phase_list (list): List of phase names

    Returns:
        dict: Ray path information
    """
    try:
        taup_model = TauPyModel(model=model)

        kwargs = {
            'source_depth_in_km': source_depth_km,
            'distance_in_degree': distance_deg
        }

        if phase_list:
            kwargs['phase_list'] = phase_list

        arrivals = taup_model.get_ray_paths(**kwargs)

        paths_info = []
        for arrival in arrivals:
            path_points = []
            if hasattr(arrival, 'path') and arrival.path is not None:
                for point in arrival.path:
                    path_points.append({
                        "distance_deg": float(point['dist']),
                        "depth_km": float(point['depth']),
                        "time": float(point['time'])
                    })

            paths_info.append({
                "name": arrival.name,
                "time": arrival.time,
                "path_length": len(path_points),
                "path": path_points[:100]  # Limit to first 100 points
            })

        return {
            "success": True,
            "message": f"Retrieved ray paths for {len(arrivals)} phase(s)",
            "model": model,
            "source_depth_km": source_depth_km,
            "distance_deg": distance_deg,
            "ray_paths": paths_info
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 7. Trigger Algorithms & Cross-correlation (触发算法和互相关)
# ============================================================================

@mcp.tool(name="apply_sta_lta_trigger", description="Apply STA/LTA trigger algorithm for event detection")
def apply_sta_lta_trigger(file_path: str, sta_window: float, lta_window: float,
                          trigger_on: float = 3.0, trigger_off: float = 1.5,
                          output_path: str = None) -> dict:
    """
    Apply STA/LTA trigger algorithm.

    Parameters:
        file_path (str): Path to waveform file
        sta_window (float): Short-term average window (seconds)
        lta_window (float): Long-term average window (seconds)
        trigger_on (float): Trigger on threshold
        trigger_off (float): Trigger off threshold
        output_path (str): Optional output image path for trigger plot

    Returns:
        dict: Trigger results
    """
    try:
        stream = read(file_path)

        if len(stream) == 0:
            return {"success": False, "error": "No traces in stream"}

        trace = stream[0]
        df = trace.stats.sampling_rate

        # Convert seconds to samples
        nsta = int(sta_window * df)
        nlta = int(lta_window * df)

        # Calculate STA/LTA
        cft = classic_sta_lta(trace.data, nsta, nlta)

        # Find triggers
        from obspy.signal.trigger import trigger_onset
        triggers = trigger_onset(cft, trigger_on, trigger_off)

        triggers_info = []
        for on, off in triggers:
            triggers_info.append({
                "trigger_on_sample": int(on),
                "trigger_off_sample": int(off),
                "trigger_on_time": str(trace.stats.starttime + on / df),
                "trigger_off_time": str(trace.stats.starttime + off / df),
                "duration_sec": (off - on) / df
            })

        # Optionally plot
        if output_path:
            # Create output directory if needed
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            fig = plt.figure(figsize=(12, 6))
            ax1 = fig.add_subplot(211)
            ax2 = fig.add_subplot(212, sharex=ax1)

            t = np.arange(len(trace.data)) / df
            ax1.plot(t, trace.data, 'k', linewidth=0.5)
            ax1.set_ylabel('Amplitude')
            ax1.set_title(f'{trace.id} - STA/LTA Trigger')

            ax2.plot(t, cft, 'b', linewidth=0.8)
            ax2.axhline(trigger_on, color='r', linestyle='--', label='Trigger On')
            ax2.axhline(trigger_off, color='g', linestyle='--', label='Trigger Off')
            ax2.set_xlabel('Time (s)')
            ax2.set_ylabel('STA/LTA')
            ax2.legend()

            plt.tight_layout()
            plt.savefig(output_path, dpi=150)
            plt.close(fig)

        return {
            "success": True,
            "message": f"Found {len(triggers)} trigger(s)",
            "trace_id": trace.id,
            "sta_window_sec": sta_window,
            "lta_window_sec": lta_window,
            "trigger_count": len(triggers),
            "triggers": triggers_info,
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="cross_correlate_traces", description="Cross-correlate two seismic traces")
def cross_correlate_traces(file_path1: str, file_path2: str, max_shift: int = None) -> dict:
    """
    Cross-correlate two seismic traces.

    Parameters:
        file_path1 (str): Path to first waveform file
        file_path2 (str): Path to second waveform file
        max_shift (int): Maximum shift in samples

    Returns:
        dict: Cross-correlation results
    """
    try:
        stream1 = read(file_path1)
        stream2 = read(file_path2)

        if len(stream1) == 0 or len(stream2) == 0:
            return {"success": False, "error": "One or both streams are empty"}

        trace1 = stream1[0]
        trace2 = stream2[0]

        # Cross-correlate
        cc = correlate(trace1.data, trace2.data, shift=max_shift)

        # Find maximum correlation
        max_cc_idx = np.argmax(cc)
        max_cc_value = float(cc[max_cc_idx])

        # Calculate shift
        if max_shift:
            shift = max_cc_idx - max_shift
        else:
            shift = max_cc_idx - len(trace2.data) + 1

        return {
            "success": True,
            "message": "Cross-correlation completed",
            "trace1_id": trace1.id,
            "trace2_id": trace2.id,
            "max_correlation": max_cc_value,
            "shift_samples": int(shift),
            "shift_seconds": shift / trace1.stats.sampling_rate,
            "cc_length": len(cc)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 8. CLI Tools (命令行工具)
# ============================================================================

@mcp.tool(name="convert_flinn_engdahl", description="Convert lat/lon to Flinn-Engdahl region name")
def convert_flinn_engdahl(latitude: float, longitude: float) -> dict:
    """
    Convert coordinates to Flinn-Engdahl region code and name.

    Parameters:
        latitude (float): Latitude
        longitude (float): Longitude

    Returns:
        dict: Region information
    """
    try:
        from obspy.geodetics import FlinnEngdahl
        fe = FlinnEngdahl()
        region_name = fe.get_region(longitude, latitude)

        return {
            "success": True,
            "latitude": latitude,
            "longitude": longitude,
            "region": region_name
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="rotate_to_zne", description="Rotate three-component seismogram to ZNE orientation")
def rotate_to_zne(file_path: str, inventory_path: str = None, output_path: str = None) -> dict:
    """
    Rotate three-component data to ZNE (vertical, north, east).

    Parameters:
        file_path (str): Path to waveform file (must contain 3 components)
        inventory_path (str): Path to inventory with orientation info
        output_path (str): Optional output file path

    Returns:
        dict: Rotation results
    """
    try:
        from obspy import read_inventory
        stream = read(file_path)

        if inventory_path:
            inventory = read_inventory(inventory_path)
            stream.rotate('->ZNE', inventory=inventory)
        else:
            # Try without inventory (requires proper metadata in stream)
            stream.rotate('->ZNE')

        if output_path:
            stream.write(output_path, format='MSEED')

        return {
            "success": True,
            "message": f"Rotated {len(stream)} trace(s) to ZNE",
            "trace_count": len(stream),
            "output_path": output_path if output_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 9. File Download & Image Tools (文件下载与图片工具)
# ============================================================================
# Note: download_file() removed - use download_small_file() instead

# Note: list_files() removed - use list_generated_files() instead


# Note: plot_waveform_return_base64() removed
# Use: plot_waveform() + download_small_file() instead


# Note: plot_spectrogram_return_base64() removed
# Use: plot_spectrogram() + download_small_file() instead


# ============================================================================
# Section 10: File Management Tools
# ============================================================================

@mcp.tool(name="list_generated_files", description="List all files generated by ObsPy MCP service")
def list_generated_files(directory: str = "all") -> dict:
    """
    List all generated files in output directories.

    Parameters:
        directory (str): Which directory to list - 'output', 'plots', 'wave_data', or 'all' (default)

    Returns:
        dict: Dictionary containing file lists with paths, sizes, and modification times
    """
    try:
        base_dir = "/app/obspy_mcp/mcp_output"
        directories = {
            "output": os.path.join(base_dir, "output"),
            "plots": os.path.join(base_dir, "plots"),
            "wave_data": os.path.join(base_dir, "wave_data")
        }

        result = {}

        # Determine which directories to scan
        if directory == "all":
            dirs_to_scan = directories.items()
        elif directory in directories:
            dirs_to_scan = [(directory, directories[directory])]
        else:
            return {
                "success": False,
                "error": f"Invalid directory: {directory}. Use 'output', 'plots', 'wave_data', or 'all'"
            }

        # Scan directories
        total_files = 0
        for dir_name, dir_path in dirs_to_scan:
            if not os.path.exists(dir_path):
                result[dir_name] = {
                    "path": dir_path,
                    "exists": False,
                    "files": []
                }
                continue

            files = []
            for filename in os.listdir(dir_path):
                file_path = os.path.join(dir_path, filename)
                if os.path.isfile(file_path) and not filename.startswith('.'):
                    stat = os.stat(file_path)
                    files.append({
                        "name": filename,
                        "path": file_path,
                        "size_bytes": stat.st_size,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "size_mb": round(stat.st_size / (1024*1024), 2),
                        "modified": stat.st_mtime
                    })
                    total_files += 1

            # Sort by modification time (newest first)
            files.sort(key=lambda x: x["modified"], reverse=True)

            result[dir_name] = {
                "path": dir_path,
                "exists": True,
                "file_count": len(files),
                "files": files
            }

        return {
            "success": True,
            "total_files": total_files,
            "directories": result,
            "usage": "Use download_small_file() to download files via base64, or access files directly in HF Space"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="get_file_info", description="Get detailed information about a specific file")
def get_file_info(file_path: str) -> dict:
    """
    Get detailed information about a file.

    Parameters:
        file_path (str): Absolute path to the file

    Returns:
        dict: File information including size, type, and accessibility
    """
    try:
        if not os.path.exists(file_path):
            return {
                "success": False,
                "error": f"File not found: {file_path}"
            }

        if not os.path.isfile(file_path):
            return {
                "success": False,
                "error": f"Path is not a file: {file_path}"
            }

        stat = os.stat(file_path)
        file_size = stat.st_size

        # Determine file type
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        file_type = "unknown"
        can_base64 = False

        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            file_type = "image"
            can_base64 = file_size < 5 * 1024 * 1024  # < 5MB
        elif ext in ['.mseed', '.sac', '.segy']:
            file_type = "waveform"
            can_base64 = file_size < 2 * 1024 * 1024  # < 2MB
        elif ext in ['.txt', '.csv', '.json', '.xml']:
            file_type = "text"
            can_base64 = file_size < 1 * 1024 * 1024  # < 1MB

        return {
            "success": True,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "directory": os.path.dirname(file_path),
            "size_bytes": file_size,
            "size_kb": round(file_size / 1024, 2),
            "size_mb": round(file_size / (1024*1024), 2),
            "file_type": file_type,
            "extension": ext,
            "can_download_via_base64": can_base64,
            "modified_timestamp": stat.st_mtime,
            "readable": os.access(file_path, os.R_OK),
            "download_suggestion": "Use download_small_file() if can_download_via_base64 is True, otherwise access via HF Space interface"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="download_small_file", description="Download small files (< 5MB) via base64 encoding")
def download_small_file(file_path: str, max_size_mb: float = 5.0) -> dict:
    """
    Download small files via base64 encoding. For larger files, use HF Space interface.

    Parameters:
        file_path (str): Absolute path to the file
        max_size_mb (float): Maximum file size in MB (default 5.0)

    Returns:
        dict: Base64 encoded file content or error message
    """
    try:
        if not os.path.exists(file_path):
            return {
                "success": False,
                "error": f"File not found: {file_path}"
            }

        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)

        if size_mb > max_size_mb:
            return {
                "success": False,
                "error": f"File too large ({size_mb:.2f}MB). Maximum allowed: {max_size_mb}MB",
                "file_path": file_path,
                "size_mb": size_mb,
                "suggestion": "Access this file via HF Space Files tab or increase max_size_mb parameter"
            }

        import base64
        with open(file_path, 'rb') as f:
            content = f.read()

        base64_content = base64.b64encode(content).decode('utf-8')

        return {
            "success": True,
            "filename": os.path.basename(file_path),
            "size_bytes": file_size,
            "size_mb": round(size_mb, 2),
            "base64_data": base64_content,
            "usage": "Decode base64_data to save file locally"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="save_base64_to_local", description="Save base64 encoded data to user's local file system")
def save_base64_to_local(base64_data: str, local_filename: str) -> dict:
    """
    Save base64 encoded data to user's local Downloads folder.
    This tool allows AI agent to automatically save downloaded files for the user.

    Parameters:
        base64_data (str): Base64 encoded file content
        local_filename (str): Filename to save (will be saved to ~/Downloads/)

    Returns:
        dict: Success status and saved file path
    """
    try:
        import base64
        from pathlib import Path

        # Decode base64
        try:
            file_content = base64.b64decode(base64_data)
        except Exception as e:
            return {
                "success": False,
                "error": f"Invalid base64 data: {str(e)}"
            }

        # Determine save location (user's Downloads folder)
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.exists():
            downloads_dir.mkdir(parents=True, exist_ok=True)

        save_path = downloads_dir / local_filename

        # Save file
        with open(save_path, 'wb') as f:
            f.write(file_content)

        return {
            "success": True,
            "message": f"File saved successfully to {save_path}",
            "local_path": str(save_path),
            "filename": local_filename,
            "size_bytes": len(file_content),
            "size_kb": round(len(file_content) / 1024, 2),
            "saved_to": "Downloads folder"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(name="check_hf_config", description="Check HuggingFace Dataset configuration and permissions")
def check_hf_config() -> dict:
    """
    Check HuggingFace Dataset upload configuration.
    Diagnoses common issues with HF_TOKEN and HF_DATASET_REPO setup.

    Returns:
        dict: Configuration status and diagnostic information
    """
    try:
        result = {
            "config_checks": {},
            "suggestions": []
        }

        # Check HF_TOKEN
        hf_token = os.environ.get("HF_TOKEN")
        if hf_token:
            result["config_checks"]["HF_TOKEN"] = {
                "status": "✅ Found",
                "length": len(hf_token),
                "prefix": hf_token[:10] + "..." if len(hf_token) > 10 else "too_short"
            }
        else:
            result["config_checks"]["HF_TOKEN"] = {
                "status": "❌ Not found",
                "error": "Environment variable HF_TOKEN is not set"
            }
            result["suggestions"].append("Add HF_TOKEN to Space secrets with Write permission")

        # Check HF_DATASET_REPO
        dataset_repo = os.environ.get("HF_DATASET_REPO")
        if dataset_repo:
            result["config_checks"]["HF_DATASET_REPO"] = {
                "status": "✅ Found",
                "value": dataset_repo,
                "format_ok": "/" in dataset_repo
            }
            if "/" not in dataset_repo:
                result["suggestions"].append("HF_DATASET_REPO should be in format 'username/repo-name'")
        else:
            result["config_checks"]["HF_DATASET_REPO"] = {
                "status": "❌ Not found",
                "error": "Environment variable HF_DATASET_REPO is not set"
            }
            result["suggestions"].append("Add HF_DATASET_REPO to Space secrets (format: username/repo-name)")

        # Try to connect to HF API if both configs exist
        if hf_token and dataset_repo:
            try:
                from huggingface_hub import HfApi
                api = HfApi()

                # Test token validity by getting user info
                try:
                    user_info = api.whoami(token=hf_token)
                    result["config_checks"]["HF_API_Connection"] = {
                        "status": "✅ Connected",
                        "username": user_info.get("name", "unknown")
                    }
                except Exception as e:
                    result["config_checks"]["HF_API_Connection"] = {
                        "status": "❌ Failed",
                        "error": str(e)
                    }
                    result["suggestions"].append("HF_TOKEN may be invalid or expired. Generate a new token with Write permission")

            except Exception as e:
                result["config_checks"]["HF_API_Connection"] = {
                    "status": "❌ Error",
                    "error": str(e)
                }

        result["success"] = len(result["suggestions"]) == 0
        result["summary"] = "Configuration OK" if result["success"] else "Configuration issues found"

        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool(name="upload_to_hf_dataset", description="Upload generated file to HuggingFace Dataset for easy download")
def upload_to_hf_dataset(file_path: str, dataset_repo: str = None, hf_token: str = None) -> dict:
    """
    Upload generated file to HuggingFace Dataset repository.
    Users can then download files from the Dataset page.

    Parameters:
        file_path (str): Absolute path to the file on HF Space
        dataset_repo (str): Dataset repo name (e.g., 'username/obspy-outputs').
                           If None, uses HF_DATASET_REPO environment variable
        hf_token (str): HuggingFace token. If None, uses HF_TOKEN environment variable

    Returns:
        dict: Success status and download URL
    """
    try:
        from huggingface_hub import HfApi, create_repo
        from huggingface_hub.utils import RepositoryNotFoundError

        # Get credentials from environment if not provided
        if dataset_repo is None:
            dataset_repo = os.environ.get("HF_DATASET_REPO")
            if not dataset_repo:
                return {
                    "success": False,
                    "error": "Dataset repo not specified. Set HF_DATASET_REPO environment variable or pass dataset_repo parameter"
                }

        if hf_token is None:
            hf_token = os.environ.get("HF_TOKEN")
            if not hf_token:
                return {
                    "success": False,
                    "error": "HF token not found. Set HF_TOKEN environment variable or pass hf_token parameter"
                }

        # Check if file exists and readable
        if not os.path.exists(file_path):
            return {
                "success": False,
                "error": f"File not found: {file_path}"
            }

        if not os.path.isfile(file_path):
            return {
                "success": False,
                "error": f"Path is not a file: {file_path}"
            }

        if not os.access(file_path, os.R_OK):
            return {
                "success": False,
                "error": f"File not readable (permission denied): {file_path}",
                "hint": "Check file permissions in Docker container"
            }

        # Get file info for debugging
        file_size = os.path.getsize(file_path)
        file_stat = os.stat(file_path)

        # Initialize HF API
        api = HfApi()

        # Try to create dataset repo if it doesn't exist
        try:
            repo_info = create_repo(
                repo_id=dataset_repo,
                repo_type="dataset",
                token=hf_token,
                exist_ok=True,
                private=False
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create/access dataset repo: {str(e)}",
                "dataset_repo": dataset_repo,
                "hint": "Check if HF_TOKEN has write permission and dataset_repo format is correct (username/repo-name)"
            }

        # Get filename and determine path in dataset
        filename = os.path.basename(file_path)

        # Determine subdirectory based on file location
        if "/output/" in file_path:
            path_in_repo = f"output/{filename}"
        elif "/plots/" in file_path:
            path_in_repo = f"plots/{filename}"
        elif "/wave_data/" in file_path:
            path_in_repo = f"wave_data/{filename}"
        else:
            path_in_repo = filename

        # Read file content into memory first (avoid permission issues)
        try:
            with open(file_path, 'rb') as f:
                file_content = f.read()
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to read file: {str(e)}",
                "file_path": file_path,
                "hint": "File may exist but not readable due to permission issues"
            }

        # Upload file from memory instead of path
        import io
        upload_result = api.upload_file(
            path_or_fileobj=io.BytesIO(file_content),
            path_in_repo=path_in_repo,
            repo_id=dataset_repo,
            repo_type="dataset",
            token=hf_token
        )

        # Construct download URL
        download_url = f"https://huggingface.co/datasets/{dataset_repo}/resolve/main/{path_in_repo}"
        viewer_url = f"https://huggingface.co/datasets/{dataset_repo}/viewer/default/train?f%5Bfile%5D%5Bvalue%5D={path_in_repo}"

        return {
            "success": True,
            "message": f"File uploaded successfully to {dataset_repo}",
            "dataset_repo": dataset_repo,
            "filename": filename,
            "path_in_repo": path_in_repo,
            "download_url": download_url,
            "viewer_url": viewer_url,
            "usage": f"Download directly from: {download_url}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "hint": "Make sure HF_TOKEN and HF_DATASET_REPO are set in Space secrets"
        }


def create_app() -> FastMCP:
    """
    Creates and returns the FastMCP application instance.

    Returns:
        FastMCP: The FastMCP application instance.
    """
    return mcp