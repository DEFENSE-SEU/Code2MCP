import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Import statements
from obspy.scripts.runtests import runtests
from obspy.scripts.flinnengdahl import flinnengdahl
from obspy.scripts.reftekrescue import reftekrescue
from obspy.scripts.sds_html_report import sds_html_report
from obspy.core.stream import Stream
from obspy.core.trace import Trace
from obspy.core.utcdatetime import UTCDateTime
from obspy.core.event import Event, Catalog
from obspy.core.inventory import Inventory
from obspy.signal.interpolation import lanczos_interpolation
from obspy.signal.trigger import classic_sta_lta, recursive_sta_lta
from obspy.signal.filter import bandpass
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel

# Adapter class
class Adapter:
    """
    Adapter class for integrating and utilizing functionalities from the ObsPy plugin.
    This class provides methods to interact with various ObsPy modules and functions.
    """

    def __init__(self):
        """
        Initialize the Adapter class with default mode set to 'import'.
        """
        self.mode = "import"

    # -------------------------------------------------------------------------
    # Module: Scripts
    # -------------------------------------------------------------------------

    def run_tests(self):
        """
        Run the test suite for ObsPy.

        Returns:
            dict: A dictionary containing the status and any error messages.
        """
        try:
            runtests()
            return {"status": "success", "message": "Tests executed successfully."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to run tests. Error: {str(e)}"}

    def generate_flinn_engdahl_region(self, latitude, longitude):
        """
        Generate Flinn-Engdahl region names for given coordinates.

        Args:
            latitude (float): Latitude of the location.
            longitude (float): Longitude of the location.

        Returns:
            dict: A dictionary containing the status and the region name or error message.
        """
        try:
            region = flinnengdahl(latitude, longitude)
            return {"status": "success", "region": region}
        except Exception as e:
            return {"status": "error", "message": f"Failed to generate Flinn-Engdahl region. Error: {str(e)}"}

    def rescue_reftek_data(self, input_file, output_dir):
        """
        Rescue data from Reftek files.

        Args:
            input_file (str): Path to the Reftek file.
            output_dir (str): Directory to save the rescued data.

        Returns:
            dict: A dictionary containing the status and any error messages.
        """
        try:
            reftekrescue(input_file, output_dir)
            return {"status": "success", "message": "Reftek data rescued successfully."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to rescue Reftek data. Error: {str(e)}"}

    def generate_sds_html_report(self, sds_path, output_file):
        """
        Generate an HTML report for SDS archives.

        Args:
            sds_path (str): Path to the SDS archive.
            output_file (str): Path to save the HTML report.

        Returns:
            dict: A dictionary containing the status and any error messages.
        """
        try:
            sds_html_report(sds_path, output_file)
            return {"status": "success", "message": "SDS HTML report generated successfully."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to generate SDS HTML report. Error: {str(e)}"}

    # -------------------------------------------------------------------------
    # Module: Core
    # -------------------------------------------------------------------------

    def create_stream(self, traces=None):
        """
        Create an ObsPy Stream object.

        Args:
            traces (list): List of Trace objects to include in the Stream.

        Returns:
            dict: A dictionary containing the status and the Stream object or error message.
        """
        try:
            stream = Stream(traces=traces)
            return {"status": "success", "stream": stream}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Stream object. Error: {str(e)}"}

    def create_trace(self, data, header=None):
        """
        Create an ObsPy Trace object.

        Args:
            data (numpy.ndarray): Time series data.
            header (dict): Metadata for the Trace.

        Returns:
            dict: A dictionary containing the status and the Trace object or error message.
        """
        try:
            trace = Trace(data=data, header=header)
            return {"status": "success", "trace": trace}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Trace object. Error: {str(e)}"}

    def create_utcdatetime(self, time_string):
        """
        Create an ObsPy UTCDateTime object.

        Args:
            time_string (str): Time string to initialize the UTCDateTime object.

        Returns:
            dict: A dictionary containing the status and the UTCDateTime object or error message.
        """
        try:
            utc_datetime = UTCDateTime(time_string)
            return {"status": "success", "utc_datetime": utc_datetime}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create UTCDateTime object. Error: {str(e)}"}

    def create_event(self, **kwargs):
        """
        Create an ObsPy Event object.

        Args:
            **kwargs: Metadata for the Event.

        Returns:
            dict: A dictionary containing the status and the Event object or error message.
        """
        try:
            event = Event(**kwargs)
            return {"status": "success", "event": event}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Event object. Error: {str(e)}"}

    def create_catalog(self, events=None):
        """
        Create an ObsPy Catalog object.

        Args:
            events (list): List of Event objects to include in the Catalog.

        Returns:
            dict: A dictionary containing the status and the Catalog object or error message.
        """
        try:
            catalog = Catalog(events=events)
            return {"status": "success", "catalog": catalog}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Catalog object. Error: {str(e)}"}

    def create_inventory(self, networks=None, source=None):
        """
        Create an ObsPy Inventory object.

        Args:
            networks (list): List of Network objects to include in the Inventory.
            source (str): Source of the Inventory.

        Returns:
            dict: A dictionary containing the status and the Inventory object or error message.
        """
        try:
            inventory = Inventory(networks=networks, source=source)
            return {"status": "success", "inventory": inventory}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Inventory object. Error: {str(e)}"}

    # -------------------------------------------------------------------------
    # Module: Signal Processing
    # -------------------------------------------------------------------------

    def apply_lanczos_interpolation(self, data, factor):
        """
        Apply Lanczos interpolation to the given data.

        Args:
            data (numpy.ndarray): Input data for interpolation.
            factor (int): Interpolation factor.

        Returns:
            dict: A dictionary containing the status and the interpolated data or error message.
        """
        try:
            interpolated_data = lanczos_interpolation(data, factor)
            return {"status": "success", "interpolated_data": interpolated_data}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply Lanczos interpolation. Error: {str(e)}"}

    def apply_classic_sta_lta(self, data, nsta, nlta):
        """
        Apply classic STA/LTA algorithm to detect seismic events.

        Args:
            data (numpy.ndarray): Input time series data.
            nsta (int): Number of samples for the short-term average.
            nlta (int): Number of samples for the long-term average.

        Returns:
            dict: A dictionary containing the status and the STA/LTA result or error message.
        """
        try:
            result = classic_sta_lta(data, nsta, nlta)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply classic STA/LTA algorithm. Error: {str(e)}"}

    def apply_recursive_sta_lta(self, data, nsta, nlta):
        """
        Apply recursive STA/LTA algorithm to detect seismic events.

        Args:
            data (numpy.ndarray): Input time series data.
            nsta (int): Number of samples for the short-term average.
            nlta (int): Number of samples for the long-term average.

        Returns:
            dict: A dictionary containing the status and the STA/LTA result or error message.
        """
        try:
            result = recursive_sta_lta(data, nsta, nlta)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply recursive STA/LTA algorithm. Error: {str(e)}"}

    def apply_bandpass_filter(self, data, freqmin, freqmax, df, corners=4, zerophase=False):
        """
        Apply a bandpass filter to the given data.

        Args:
            data (numpy.ndarray): Input time series data.
            freqmin (float): Minimum frequency of the bandpass filter.
            freqmax (float): Maximum frequency of the bandpass filter.
            df (float): Sampling rate of the data.
            corners (int): Number of corners for the filter.
            zerophase (bool): Whether to apply a zero-phase filter.

        Returns:
            dict: A dictionary containing the status and the filtered data or error message.
        """
        try:
            filtered_data = bandpass(data, freqmin, freqmax, df, corners, zerophase)
            return {"status": "success", "filtered_data": filtered_data}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply bandpass filter. Error: {str(e)}"}

    # -------------------------------------------------------------------------
    # Module: Client Interfaces
    # -------------------------------------------------------------------------

    def create_fdsn_client(self, base_url=None):
        """
        Create an FDSN client to access remote data centers.

        Args:
            base_url (str): Base URL of the FDSN web service (optional).

        Returns:
            dict: A dictionary containing the status and the Client object or error message.
        """
        try:
            client = Client(base_url=base_url)
            return {"status": "success", "client": client}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create FDSN client. Error: {str(e)}"}

    # -------------------------------------------------------------------------
    # Module: TauPy
    # -------------------------------------------------------------------------

    def create_taup_model(self, model_name):
        """
        Create a TauPyModel for seismic travel time calculations.

        Args:
            model_name (str): Name of the velocity model (e.g., 'iasp91', 'ak135').

        Returns:
            dict: A dictionary containing the status and the TauPyModel object or error message.
        """
        try:
            model = TauPyModel(model=model_name)
            return {"status": "success", "model": model}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create TauPyModel. Error: {str(e)}"}