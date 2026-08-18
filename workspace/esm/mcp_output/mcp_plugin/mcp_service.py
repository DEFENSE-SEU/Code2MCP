import os
import sys

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from esm import pretrained, data, inverse_folding, model
# from examples.lm_design.lm_design import lm_design
# from examples.variant_prediction.predict import predict
# from scripts import extract, fold

mcp = FastMCP("esm_service")

@mcp.tool(name="load_pretrained_model", description="Load a pretrained ESM model")
def load_pretrained_model(model_name: str):
    """
    Load a pretrained ESM model.

    Parameters:
        model_name (str): Model name, e.g., 'esm1b_t33_650M_UR50S'.

    Returns:
        dict: Contains success/result/error fields.
    """
    try:
        model, alphabet = pretrained.load_model_and_alphabet(model_name)
        return {"success": True, "result": {"model": model, "alphabet": alphabet}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="process_sequence_data", description="Process protein sequence data")
def process_sequence_data(sequences: list):
    """
    Process protein sequence data using Alphabet and BatchConverter.

    Parameters:
        sequences (list): List of (label, description, sequence) tuples.

    Returns:
        dict: Contains success/result/error fields.
    """
    try:
        alphabet = data.Alphabet()
        batch_converter = data.BatchConverter(alphabet)
        batch = batch_converter(sequences)
        return {"success": True, "result": batch, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="inverse_folding_model", description="Load inverse folding model")
def inverse_folding_model():
    """
    Load the core model for inverse folding tasks.

    Returns:
        dict: Contains success/result/error fields.
    """
    try:
        model = inverse_folding.load_inverse_folding_model()
        return {"success": True, "result": model, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="generate_fixed_backbone", description="Generate protein sequence with fixed backbone")
def generate_fixed_backbone(input_data: dict):
    """
    Generate protein sequences using a fixed backbone.

    Parameters:
        input_data (dict): Input data payload.

    Returns:
        dict: Contains success/result/error fields.
    """
    try:
        result = lm_design.generate_fixed_backbone(input_data)
        return {"success": False, "result": None, "error": "This feature is currently unavailable"}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="predict_variant_effect", description="Predict protein variant effects")
def predict_variant_effect(sequence: str, mutation: str):
    """
    Predict the effect of a mutation in a protein sequence.

    Parameters:
        sequence (str): Protein sequence.
        mutation (str): Mutation description.

    Returns:
        dict: Contains success/result/error fields.
    """
    try:
        # result = predict.predict_variant_effect(sequence, mutation)
        return {"success": False, "result": None, "error": "This feature is currently unavailable"}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="extract_features", description="Extract features from model")
def extract_features(sequence: str):
    """
    Extract features of a protein sequence from a pretrained model.

    Parameters:
        sequence (str): Protein sequence.

    Returns:
        dict: Contains success/result/error fields.
    """
    try:
        features = extract.extract_features(sequence)  # type: ignore[name-defined]
        return {"success": True, "result": features, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="predict_structure", description="Predict protein structure using ESMFold API")
def predict_structure(sequence: str):
    """
    Predict protein structure using the ESMFold API.

    Parameters:
        sequence (str): Protein amino acid sequence.

    Returns:
        dict: Dictionary containing the prediction result.
    """
    try:
        import requests
        from Bio.PDB import PDBParser
        import io
        import datetime

        # Call ESMFold API
        response = requests.post(
            "https://api.esmatlas.com/foldSequence/v1/pdb/",
            data=sequence,
            timeout=300
        )

        if response.status_code == 200 and response.text.strip():
            parser = PDBParser(QUIET=True)
            pdb_io = io.StringIO(response.text)
            structure = parser.get_structure("esmfold_prediction", pdb_io)

            predictions_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "predictions")
            os.makedirs(predictions_dir, exist_ok=True)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            pdb_filename = f"prediction_{timestamp}.pdb"
            pdb_filepath = os.path.join(predictions_dir, pdb_filename)

            # Save PDB file
            with open(pdb_filepath, 'w') as f:
                f.write(response.text)

            # Extract structure info
            structure_info = {
                "num_models": len(structure),
                "num_chains": len(list(structure.get_chains())),
                "num_residues": len(list(structure.get_residues())),
                "num_atoms": len(list(structure.get_atoms())),
                "pdb_content": response.text,
                "pdb_file_path": pdb_filepath
            }

            return {
                "success": True,
                "result": structure_info,
                "error": None
            }
        else:
            return {
                "success": False,
                "result": None,
                "error": f"API returned error: {response.status_code}"
            }

    except requests.exceptions.Timeout:  # type: ignore[name-defined]
        return {
            "success": False,
            "result": None,
            "error": "ESMFold API request timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": f"Error predicting structure: {str(e)}"
        }

@mcp.tool(name="analyze_protein_sequence", description="Analyze protein sequence features")
def analyze_protein_sequence(sequence: str):
    """Analyze basic features of a protein sequence"""
    try:
        length = len(sequence)
        amino_acids = set(sequence)

        # Amino acid composition
        composition = {}
        for aa in amino_acids:
            composition[aa] = sequence.count(aa)

        return {
            "success": True,
            "result": {
                "length": length,
                "unique_amino_acids": len(amino_acids),
                "composition": composition,
                "sequence": sequence
            },
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": str(e)
        }

@mcp.tool(name="validate_protein_sequence", description="Validate protein sequence format")
def validate_protein_sequence(sequence: str):
    """Validate that a protein sequence contains valid amino acid codes"""
    try:
        valid_amino_acids = set("ACDEFGHIKLMNPQRSTVWY")
        sequence_upper = sequence.upper()

        invalid_chars = set(sequence_upper) - valid_amino_acids
        is_valid = len(invalid_chars) == 0

        return {
            "success": True,
            "result": {
                "is_valid": is_valid,
                "invalid_characters": list(invalid_chars) if invalid_chars else [],
                "length": len(sequence),
                "uppercase_sequence": sequence_upper
            },
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": str(e)
        }


def create_app():
    """
    Create and return a FastMCP instance.

    Returns:
        FastMCP: MCP service instance.
    """
    return mcp
