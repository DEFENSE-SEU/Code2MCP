import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Import statements
try:
    from obspy.scripts.runtests import runtests
    from obspy.scripts.sds_html_report import sds_html_report
    from obspy.scripts.flinnengdahl import flinnengdahl
    from obspy.core.stream import Stream
    from obspy.core.trace import Trace
    from obspy.core.utcdatetime import UTCDateTime
    from obspy.clients.fdsn.client import Client
    from obspy.clients.fdsn.mass_downloader import MassDownloader
    from obspy.signal.trigger import classic_sta_lta, z_detect
    from obspy.signal.cross_correlation import correlate
    from obspy.signal.spectral_estimation import PPSD
    from obspy.taup import TauPyModel
    from obspy.imaging.beachball import beach
    from obspy.io.mseed import core as mseed_core
    from obspy.io.stationxml.core import StationXML
except ImportError as e:
    print(f"Error importing modules: {e}. Falling back to limited functionality.")

# Adapter class
class Adapter:
    """
    Adapter class for integrating and utilizing functionalities from the ObsPy library.
    Provides methods for accessing core features, signal processing, client interfaces, and visualization.
    """

    def __init__(self):
        """
        Initialize the Adapter class with default mode and status.
        """
        self.mode = "import"
        self.status = {"status": "initialized"}

    # -------------------------------------------------------------------------
    # Core Functionalities
    # -------------------------------------------------------------------------

    def create_stream(self, traces=None):
        """
        Create an ObsPy Stream object.

        :param traces: List of Trace objects to include in the Stream.
        :return: Dictionary containing the status and the created Stream object.
        """
        try:
            stream = Stream(traces=traces)
            return {"status": "success", "stream": stream}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Stream: {e}"}

    def create_trace(self, data, header=None):
        """
        Create an ObsPy Trace object.

        :param data: Data array for the Trace.
        :param header: Optional header information.
        :return: Dictionary containing the status and the created Trace object.
        """
        try:
            trace = Trace(data=data, header=header)
            return {"status": "success", "trace": trace}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Trace: {e}"}

    def create_utcdatetime(self, time_string):
        """
        Create an ObsPy UTCDateTime object.

        :param time_string: Time string to convert to UTCDateTime.
        :return: Dictionary containing the status and the created UTCDateTime object.
        """
        try:
            utc_time = UTCDateTime(time_string)
            return {"status": "success", "utcdatetime": utc_time}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create UTCDateTime: {e}"}

    # -------------------------------------------------------------------------
    # Client Interfaces
    # -------------------------------------------------------------------------

    def create_fdsn_client(self, base_url):
        """
        Create an FDSN client for accessing seismic data.

        :param base_url: Base URL of the FDSN web service.
        :return: Dictionary containing the status and the created Client object.
        """
        try:
            client = Client(base_url)
            return {"status": "success", "client": client}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create FDSN Client: {e}"}

    def create_mass_downloader(self):
        """
        Create a MassDownloader object for downloading seismic data.

        :return: Dictionary containing the status and the created MassDownloader object.
        """
        try:
            downloader = MassDownloader()
            return {"status": "success", "downloader": downloader}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create MassDownloader: {e}"}

    # -------------------------------------------------------------------------
    # Signal Processing
    # -------------------------------------------------------------------------

    def apply_classic_sta_lta(self, data, nsta, nlta):
        """
        Apply the classic STA/LTA trigger algorithm.

        :param data: Data array to process.
        :param nsta: Short-term average window length.
        :param nlta: Long-term average window length.
        :return: Dictionary containing the status and the STA/LTA result.
        """
        try:
            result = classic_sta_lta(data, nsta, nlta)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply classic STA/LTA: {e}"}

    def apply_z_detect(self, data):
        """
        Apply the Z-detect trigger algorithm.

        :param data: Data array to process.
        :return: Dictionary containing the status and the Z-detect result.
        """
        try:
            result = z_detect(data)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to apply Z-detect: {e}"}

    def cross_correlate(self, trace1, trace2, shift):
        """
        Perform cross-correlation between two traces.

        :param trace1: First Trace object.
        :param trace2: Second Trace object.
        :param shift: Maximum shift for cross-correlation.
        :return: Dictionary containing the status and the cross-correlation result.
        """
        try:
            result = correlate(trace1, trace2, shift)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to perform cross-correlation: {e}"}

    # -------------------------------------------------------------------------
    # Visualization
    # -------------------------------------------------------------------------

    def plot_beachball(self, moment_tensor, size=200):
        """
        Plot a beachball diagram for a given moment tensor.

        :param moment_tensor: Moment tensor to visualize.
        :param size: Size of the beachball diagram.
        :return: Dictionary containing the status and the plot object.
        """
        try:
            plot = beach(moment_tensor, size=size)
            return {"status": "success", "plot": plot}
        except Exception as e:
            return {"status": "error", "message": f"Failed to plot beachball: {e}"}

    # -------------------------------------------------------------------------
    # File I/O
    # -------------------------------------------------------------------------

    def read_mseed(self, file_path):
        """
        Read a MiniSEED file.

        :param file_path: Path to the MiniSEED file.
        :return: Dictionary containing the status and the Stream object.
        """
        try:
            stream = mseed_core.read(file_path)
            return {"status": "success", "stream": stream}
        except Exception as e:
            return {"status": "error", "message": f"Failed to read MiniSEED file: {e}"}

    def write_stationxml(self, inventory, file_path):
        """
        Write an inventory to a StationXML file.

        :param inventory: Inventory object to write.
        :param file_path: Path to save the StationXML file.
        :return: Dictionary containing the status.
        """
        try:
            StationXML.write(inventory, file_path)
            return {"status": "success", "message": "StationXML file written successfully."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to write StationXML file: {e}"}

    # -------------------------------------------------------------------------
    # CLI Commands
    # -------------------------------------------------------------------------

    def run_tests(self):
        """
        Run the ObsPy test suite.

        :return: Dictionary containing the status and test results.
        """
        try:
            results = runtests()
            return {"status": "success", "results": results}
        except Exception as e:
            return {"status": "error", "message": f"Failed to run tests: {e}"}

    def generate_sds_html_report(self, directory):
        """
        Generate an HTML report for SDS directories.

        :param directory: Path to the SDS directory.
        :return: Dictionary containing the status and the report path.
        """
        try:
            report_path = sds_html_report(directory)
            return {"status": "success", "report_path": report_path}
        except Exception as e:
            return {"status": "error", "message": f"Failed to generate SDS HTML report: {e}"}

    def convert_to_flinnengdahl(self, latitude, longitude):
        """
        Convert latitude and longitude to Flinn-Engdahl region codes.

        :param latitude: Latitude value.
        :param longitude: Longitude value.
        :return: Dictionary containing the status and the region code.
        """
        try:
            region_code = flinnengdahl(latitude, longitude)
            return {"status": "success", "region_code": region_code}
        except Exception as e:
            return {"status": "error", "message": f"Failed to convert to Flinn-Engdahl region code: {e}"}