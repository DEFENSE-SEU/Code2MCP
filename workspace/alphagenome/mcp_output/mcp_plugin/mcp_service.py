import os
import sys

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from src.alphagenome.dna_client import DnaClient
from src.alphagenome.genome import Interval, Variant
from src.alphagenome.track_data import TrackData
from src.alphagenome.visualization.plot_components import plot

mcp = FastMCP("alphagenome_service")


@mcp.tool(name="create_client", description="Create a DNA client instance using an API key.")
def create_client(api_key: str) -> dict:
    """
    Create a DNA client instance using the provided API key.

    Parameters:
        api_key (str): The API key for authentication.

    Returns:
        dict: A dictionary containing success, result (DnaClient instance), or error fields.
    """
    try:
        client = DnaClient.create(api_key)
        return {"success": True, "result": client, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="predict_sequence", description="Analyze raw DNA sequences using the DNA client.")
def predict_sequence(client: DnaClient, sequence: str) -> dict:
    """
    Analyze raw DNA sequences using the DNA client.

    Parameters:
        client (DnaClient): The DNA client instance.
        sequence (str): The raw DNA sequence to analyze.

    Returns:
        dict: A dictionary containing success, result (predictions), or error fields.
    """
    try:
        predictions = client.predict_sequence(sequence)
        return {"success": True, "result": predictions, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="predict_interval", description="Predict properties for genomic intervals.")
def predict_interval(client: DnaClient, interval: Interval) -> dict:
    """
    Predict properties for genomic intervals using the DNA client.

    Parameters:
        client (DnaClient): The DNA client instance.
        interval (Interval): The genomic interval to analyze.

    Returns:
        dict: A dictionary containing success, result (predictions), or error fields.
    """
    try:
        predictions = client.predict_interval(interval)
        return {"success": True, "result": predictions, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="predict_variant", description="Compare reference and alternate sequences for variants.")
def predict_variant(client: DnaClient, interval: Interval, variant: Variant) -> dict:
    """
    Compare reference and alternate sequences for variants using the DNA client.

    Parameters:
        client (DnaClient): The DNA client instance.
        interval (Interval): The genomic interval containing the variant.
        variant (Variant): The genetic variant to analyze.

    Returns:
        dict: A dictionary containing success, result (predictions), or error fields.
    """
    try:
        predictions = client.predict_variant(interval, variant)
        return {"success": True, "result": predictions, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="score_variant", description="Calculate variant effect scores.")
def score_variant(client: DnaClient, variant: Variant) -> dict:
    """
    Calculate variant effect scores using the DNA client.

    Parameters:
        client (DnaClient): The DNA client instance.
        variant (Variant): The genetic variant to score.

    Returns:
        dict: A dictionary containing success, result (scores), or error fields.
    """
    try:
        scores = client.score_variant(variant)
        return {"success": True, "result": scores, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="score_variants", description="Batch process multiple variants for effect scores.")
def score_variants(client: DnaClient, variants: list[Variant]) -> dict:
    """
    Batch process multiple variants for effect scores using the DNA client.

    Parameters:
        client (DnaClient): The DNA client instance.
        variants (list[Variant]): A list of genetic variants to score.

    Returns:
        dict: A dictionary containing success, result (scores), or error fields.
    """
    try:
        scores = client.score_variants(variants)
        return {"success": True, "result": scores, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


@mcp.tool(name="visualize_predictions", description="Visualize genomic predictions using plot components.")
def visualize_predictions(tracks: list[TrackData], annotations: list[str]) -> dict:
    """
    Visualize genomic predictions using plot components.

    Parameters:
        tracks (list[TrackData]): A list of prediction tracks to visualize.
        annotations (list[str]): A list of annotations for the visualization.

    Returns:
        dict: A dictionary containing success, result (plot figure), or error fields.
    """
    try:
        figure = plot(tracks, annotations)
        return {"success": True, "result": figure, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


def create_app() -> FastMCP:
    """
    Create and return the FastMCP application instance.

    Returns:
        FastMCP: The FastMCP application instance.
    """
    return mcp