import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Import statements
try:
    from src.alphagenome.dna_client import DnaClient
    from src.alphagenome.genome import Interval, Variant
    from src.alphagenome.track_data import TrackData
    from src.alphagenome.plot_components import plot
    from src.alphagenome.anndata import AnnData
except ImportError as e:
    print(f"Error importing modules: {e}. Ensure the source directory is correctly configured.")
    DnaClient = None
    Interval = None
    Variant = None
    TrackData = None
    plot = None
    AnnData = None


class Adapter:
    """
    Adapter class for interacting with the AlphaGenome client library.
    Provides methods for genomic analysis, visualization, and data handling.
    """

    def __init__(self):
        """
        Initialize the Adapter class.
        Sets the mode attribute to 'import' and checks for module availability.
        """
        self.mode = "import"
        self.status = {"status": "success", "message": "Adapter initialized successfully."}
        if not all([DnaClient, Interval, Variant, TrackData, plot, AnnData]):
            self.mode = "fallback"
            self.status = {"status": "error", "message": "Some modules failed to import. Fallback mode activated."}

    # -------------------------------------------------------------------------
    # Core Client Methods
    # -------------------------------------------------------------------------

    def create_dna_client(self, api_key):
        """
        Create an instance of DnaClient.

        Parameters:
            api_key (str): API key for authentication.

        Returns:
            dict: Status and DnaClient instance or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("DnaClient module not available.")
            client = DnaClient.create(api_key)
            return {"status": "success", "client": client}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create DnaClient: {e}"}

    def predict_sequence(self, client, sequence):
        """
        Predict properties for a raw DNA sequence.

        Parameters:
            client (DnaClient): Instance of DnaClient.
            sequence (str): Raw DNA sequence.

        Returns:
            dict: Status and prediction results or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("DnaClient module not available.")
            predictions = client.predict_sequence(sequence)
            return {"status": "success", "predictions": predictions}
        except Exception as e:
            return {"status": "error", "message": f"Failed to predict sequence: {e}"}

    def predict_interval(self, client, interval):
        """
        Predict properties for a genomic interval.

        Parameters:
            client (DnaClient): Instance of DnaClient.
            interval (Interval): Genomic interval object.

        Returns:
            dict: Status and prediction results or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("DnaClient module not available.")
            predictions = client.predict_interval(interval)
            return {"status": "success", "predictions": predictions}
        except Exception as e:
            return {"status": "error", "message": f"Failed to predict interval: {e}"}

    def predict_variant(self, client, interval, variant):
        """
        Predict properties for a genetic variant.

        Parameters:
            client (DnaClient): Instance of DnaClient.
            interval (Interval): Genomic interval object.
            variant (Variant): Genetic variant object.

        Returns:
            dict: Status and prediction results or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("DnaClient module not available.")
            predictions = client.predict_variant(interval, variant)
            return {"status": "success", "predictions": predictions}
        except Exception as e:
            return {"status": "error", "message": f"Failed to predict variant: {e}"}

    def score_variant(self, client, variant):
        """
        Calculate variant effect scores.

        Parameters:
            client (DnaClient): Instance of DnaClient.
            variant (Variant): Genetic variant object.

        Returns:
            dict: Status and score results or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("DnaClient module not available.")
            scores = client.score_variant(variant)
            return {"status": "success", "scores": scores}
        except Exception as e:
            return {"status": "error", "message": f"Failed to score variant: {e}"}

    def score_variants(self, client, variants):
        """
        Batch process multiple variants for effect scores.

        Parameters:
            client (DnaClient): Instance of DnaClient.
            variants (list): List of Variant objects.

        Returns:
            dict: Status and batch score results or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("DnaClient module not available.")
            scores = client.score_variants(variants)
            return {"status": "success", "scores": scores}
        except Exception as e:
            return {"status": "error", "message": f"Failed to score variants: {e}"}

    # -------------------------------------------------------------------------
    # Data Structure Methods
    # -------------------------------------------------------------------------

    def create_interval(self, chromosome, start, end):
        """
        Create a genomic interval object.

        Parameters:
            chromosome (str): Chromosome name.
            start (int): Start position.
            end (int): End position.

        Returns:
            dict: Status and Interval object or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("Interval module not available.")
            interval = Interval(chromosome, start, end)
            return {"status": "success", "interval": interval}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create interval: {e}"}

    def create_variant(self, chromosome, position, reference_bases, alternate_bases):
        """
        Create a genetic variant object.

        Parameters:
            chromosome (str): Chromosome name.
            position (int): Position on the chromosome.
            reference_bases (str): Reference bases.
            alternate_bases (str): Alternate bases.

        Returns:
            dict: Status and Variant object or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("Variant module not available.")
            variant = Variant(chromosome, position, reference_bases, alternate_bases)
            return {"status": "success", "variant": variant}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create variant: {e}"}

    # -------------------------------------------------------------------------
    # Visualization Methods
    # -------------------------------------------------------------------------

    def plot_predictions(self, tracks, annotations=None):
        """
        Visualize genomic predictions.

        Parameters:
            tracks (list): List of TrackData objects.
            annotations (list, optional): List of annotations for the plot.

        Returns:
            dict: Status and matplotlib figure or error message.
        """
        try:
            if self.mode == "fallback":
                raise ImportError("Plot module not available.")
            figure = plot(tracks, annotations)
            return {"status": "success", "figure": figure}
        except Exception as e:
            return {"status": "error", "message": f"Failed to plot predictions: {e}"}

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def check_status(self):
        """
        Check the current status of the adapter.

        Returns:
            dict: Current status of the adapter.
        """
        return self.status