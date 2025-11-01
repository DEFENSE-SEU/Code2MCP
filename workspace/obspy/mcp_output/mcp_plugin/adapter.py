import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Import statements
from obspy.core.stream import Stream
from obspy.core.trace import Trace
from obspy.core.utcdatetime import UTCDateTime
from obspy.core.event import Event, Catalog
from obspy.core.inventory import Inventory
from obspy.signal.interpolation import lanczos_interpolation
from obspy.signal.trigger import classic_sta_lta, recursive_sta_lta, trigger_onset
from obspy.signal.filter import bandpass
from obspy.taup.taup_time import get_travel_times
from obspy.clients.fdsn.client import Client
from obspy.io.mseed.core import read as read_mseed
from obspy.io.stationxml.core import read_stationxml
from obspy.io.quakeml.core import read_events

class Adapter:
    """
    Adapter class for MCP plugin integration with ObsPy functionalities.
    Provides methods to interact with ObsPy's core classes and functions.
    """

    def __init__(self):
        """
        Initialize the Adapter class with default mode set to 'import'.
        """
        self.mode = "import"

    # -------------------------------------------------------------------------
    # Core Data Structures
    # -------------------------------------------------------------------------

    def create_stream(self, traces=None):
        """
        Create an instance of the Stream class.

        Parameters:
            traces (list): List of Trace objects to initialize the Stream.

        Returns:
            dict: A dictionary containing the status and the Stream instance.
        """
        try:
            stream = Stream(traces=traces)
            return {"status": "success", "stream": stream}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Stream: {str(e)}"}

    def create_trace(self, data, header=None):
        """
        Create an instance of the Trace class.

        Parameters:
            data (numpy.ndarray): Time series data.
            header (dict): Metadata for the Trace.

        Returns:
            dict: A dictionary containing the status and the Trace instance.
        """
        try:
            trace = Trace(data=data, header=header)
            return {"status": "success", "trace": trace}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Trace: {str(e)}"}

    def create_utcdatetime(self, time_string):
        """
        Create an instance of the UTCDateTime class.

        Parameters:
            time_string (str): Time string to initialize the UTCDateTime.

        Returns:
            dict: A dictionary containing the status and the UTCDateTime instance.
        """
        try:
            utc_datetime = UTCDateTime(time_string)
            return {"status": "success", "utc_datetime": utc_datetime}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create UTCDateTime: {str(e)}"}

    def create_event(self, **kwargs):
        """
        Create an instance of the Event class.

        Parameters:
            kwargs (dict): Event metadata.

        Returns:
            dict: A dictionary containing the status and the Event instance.
        """
        try:
            event = Event(**kwargs)
            return {"status": "success", "event": event}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Event: {str(e)}"}

    def create_catalog(self, events=None):
        """
        Create an instance of the Catalog class.

        Parameters:
            events (list): List of Event objects to initialize the Catalog.

        Returns:
            dict: A dictionary containing the status and the Catalog instance.
        """
        try:
            catalog = Catalog(events=events)
            return {"status": "success", "catalog": catalog}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Catalog: {str(e)}"}

    def create_inventory(self, networks=None, source=None):
        """
        Create an instance of the Inventory class.

        Parameters:
            networks (list): List of Network objects.
            source (str): Source of the inventory.

        Returns:
            dict: A dictionary containing the status and the Inventory instance.
        """
        try:
            inventory = Inventory(networks=networks, source=source)
            return {"status": "success", "inventory": inventory}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Inventory: {str(e)}"}

    # -------------------------------------------------------------------------
    # Signal Processing
    # -------------------------------------------------------------------------

    def apply_lanczos_interpolation(self, data, new_sampling_rate, method="linear"):
        """
        Apply Lanczos interpolation to the given data.

        Parameters:
            data (numpy.ndarray): Input data for interpolation.
            new_sampling_rate (float): Desired sampling rate.
            method (str): Interpolation method (default is 'linear').

        Returns:
            dict: A dictionary containing the status and the interpolated data.
        """
        try:
            interpolated_data = lanczos_interpolation(data, new_sampling_rate, method=method)
            return {"status": "success", "interpolated_data": interpolated_data}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply Lanczos interpolation: {str(e)}"}

    def apply_classic_sta_lta(self, data, nsta, nlta):
        """
        Apply classic STA/LTA algorithm to the given data.

        Parameters:
            data (numpy.ndarray): Input data for STA/LTA calculation.
            nsta (int): Number of samples for the short-term average.
            nlta (int): Number of samples for the long-term average.

        Returns:
            dict: A dictionary containing the status and the STA/LTA result.
        """
        try:
            result = classic_sta_lta(data, nsta, nlta)
            return {"status": "success", "sta_lta_result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply classic STA/LTA: {str(e)}"}

    def apply_recursive_sta_lta(self, data, nsta, nlta):
        """
        Apply recursive STA/LTA algorithm to the given data.

        Parameters:
            data (numpy.ndarray): Input data for STA/LTA calculation.
            nsta (int): Number of samples for the short-term average.
            nlta (int): Number of samples for the long-term average.

        Returns:
            dict: A dictionary containing the status and the STA/LTA result.
        """
        try:
            result = recursive_sta_lta(data, nsta, nlta)
            return {"status": "success", "sta_lta_result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply recursive STA/LTA: {str(e)}"}

    def detect_trigger_onset(self, sta_lta_result, threshold_on, threshold_off):
        """
        Detect trigger onset using STA/LTA results.

        Parameters:
            sta_lta_result (numpy.ndarray): STA/LTA result.
            threshold_on (float): Trigger on threshold.
            threshold_off (float): Trigger off threshold.

        Returns:
            dict: A dictionary containing the status and the detected triggers.
        """
        try:
            triggers = trigger_onset(sta_lta_result, threshold_on, threshold_off)
            return {"status": "success", "triggers": triggers}
        except Exception as e:
            return {"status": "error", "message": f"Failed to detect trigger onset: {str(e)}"}

    def apply_bandpass_filter(self, data, freqmin, freqmax, df, corners=4, zerophase=False):
        """
        Apply a bandpass filter to the given data.

        Parameters:
            data (numpy.ndarray): Input data for filtering.
            freqmin (float): Minimum frequency.
            freqmax (float): Maximum frequency.
            df (float): Sampling rate.
            corners (int): Number of corners for the filter (default is 4).
            zerophase (bool): Apply zero-phase filtering (default is False).

        Returns:
            dict: A dictionary containing the status and the filtered data.
        """
        try:
            filtered_data = bandpass(data, freqmin, freqmax, df, corners=corners, zerophase=zerophase)
            return {"status": "success", "filtered_data": filtered_data}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply bandpass filter: {str(e)}"}

    # -------------------------------------------------------------------------
    # Travel Time Calculation
    # -------------------------------------------------------------------------

    def calculate_travel_times(self, source_depth_in_km, distance_in_degree, phase_list=None):
        """
        Calculate travel times for seismic phases.

        Parameters:
            source_depth_in_km (float): Depth of the seismic source in kilometers.
            distance_in_degree (float): Distance in degrees.
            phase_list (list): List of seismic phases to calculate travel times for.

        Returns:
            dict: A dictionary containing the status and the travel times.
        """
        try:
            travel_times = get_travel_times(source_depth_in_km, distance_in_degree, phase_list=phase_list)
            return {"status": "success", "travel_times": travel_times}
        except Exception as e:
            return {"status": "error", "message": f"Failed to calculate travel times: {str(e)}"}

    # -------------------------------------------------------------------------
    # Data I/O
    # -------------------------------------------------------------------------

    def read_waveform_data(self, file_path):
        """
        Read waveform data from a MiniSEED file.

        Parameters:
            file_path (str): Path to the MiniSEED file.

        Returns:
            dict: A dictionary containing the status and the Stream object.
        """
        try:
            stream = read_mseed(file_path)
            return {"status": "success", "stream": stream}
        except Exception as e:
            return {"status": "error", "message": f"Failed to read waveform data: {str(e)}"}

    def read_station_metadata(self, file_path):
        """
        Read station metadata from a StationXML file.

        Parameters:
            file_path (str): Path to the StationXML file.

        Returns:
            dict: A dictionary containing the status and the Inventory object.
        """
        try:
            inventory = read_stationxml(file_path)
            return {"status": "success", "inventory": inventory}
        except Exception as e:
            return {"status": "error", "message": f"Failed to read station metadata: {str(e)}"}

    def read_event_data(self, file_path):
        """
        Read seismic event data from a QuakeML file.

        Parameters:
            file_path (str): Path to the QuakeML file.

        Returns:
            dict: A dictionary containing the status and the Catalog object.
        """
        try:
            catalog = read_events(file_path)
            return {"status": "success", "catalog": catalog}
        except Exception as e:
            return {"status": "error", "message": f"Failed to read event data: {str(e)}"}

    # -------------------------------------------------------------------------
    # Client Interfaces
    # -------------------------------------------------------------------------

    def create_fdsn_client(self, base_url=None):
        """
        Create an instance of the FDSN Client.

        Parameters:
            base_url (str): Base URL of the FDSN web service (optional).

        Returns:
            dict: A dictionary containing the status and the Client instance.
        """
        try:
            client = Client(base_url=base_url)
            return {"status": "success", "client": client}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create FDSN Client: {str(e)}"}