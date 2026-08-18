import os
import sys

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from esm import pretrained, data, model  # type: ignore

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
def inverse_folding_model(model_name: str = "esm_if1_gvp4_t16_142M_UR50"):
    """
    Ensure the inverse folding model weights are available and loadable.

    Parameters:
        model_name (str): Pretrained inverse folding model identifier.

    Returns:
        dict: success/result/error. result contains { model_name }
    """
    try:
        # Load to ensure environment and weights are OK; don't return the torch object
        model_obj, _alphabet = pretrained.__dict__[model_name]() if hasattr(pretrained, model_name) else pretrained.esm_if1_gvp4_t16_142M_UR50()
        # Put into eval mode and immediately free GPU if any
        model_obj = model_obj.eval()
        try:
            # move back to CPU to avoid holding GPU memory
            import torch  # local import to avoid hard dep on torch at import time
            model_obj.cpu()
        except Exception:
            pass
        return {"success": True, "result": {"model_name": model_name}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="generate_fixed_backbone", description="Generate protein sequence with fixed backbone")
def generate_fixed_backbone(
    pdbfile: str,
    chain: str | None = None,
    temperature: float = 1.0,
    num_samples: int = 1,
    multichain_backbone: bool = False,
    nogpu: bool = False,
):
    """
    Sample protein sequences conditioned on a fixed backbone structure.

    Parameters:
        pdbfile (str): Path to input PDB/CIF file.
        chain (str|None): Chain ID for single-chain conditioning. Ignored when multichain_backbone=True.
        temperature (float): Sampling temperature (>1 for diversity).
        num_samples (int): Number of sequences to sample.
        multichain_backbone (bool): If True, condition on all chains in the complex.
        nogpu (bool): If True, do not use GPU even if available.

    Returns:
        dict: success/result/error. result contains { sampled_sequences, recovery (if native available) }
    """
    try:
        # Lazy import to avoid requiring torch_geometric unless needed
        from esm import inverse_folding  # type: ignore
        import torch
        model_obj, _alphabet = pretrained.esm_if1_gvp4_t16_142M_UR50()
        model_obj = model_obj.eval()

        sampled = []
        recoveries = []

        if not torch.cuda.is_available() or nogpu:
            device = torch.device("cpu")
        else:
            model_obj = model_obj.cuda()
            device = torch.device("cuda")

        if multichain_backbone:
            structure = inverse_folding.util.load_structure(pdbfile)
            coords, native_seqs = inverse_folding.multichain_util.extract_coords_from_complex(structure)
            # choose target chain: if chain provided and exists, use it; else pick first
            target_chain_id = chain if (chain in native_seqs if chain is not None else False) else next(iter(native_seqs.keys()))
            native_seq = native_seqs[target_chain_id]
            for _ in range(num_samples):
                sampled_seq = inverse_folding.multichain_util.sample_sequence_in_complex(
                    model_obj, coords, target_chain_id, temperature=temperature
                )
                sampled.append(sampled_seq)
                try:
                    recoveries.append(sum(a == b for a, b in zip(native_seq, sampled_seq)) / max(1, len(native_seq)))
                except Exception:
                    recoveries.append(None)
        else:
            coords, native_seq = inverse_folding.util.load_coords(pdbfile, chain)
            for _ in range(num_samples):
                sampled_seq = model_obj.sample(coords, temperature=temperature, device=device)
                sampled.append(sampled_seq)
                try:
                    recoveries.append(sum(a == b for a, b in zip(native_seq, sampled_seq)) / max(1, len(native_seq)))
                except Exception:
                    recoveries.append(None)

        return {
            "success": True,
            "result": {
                "sampled_sequences": sampled,
                "recovery": recoveries,
            },
            "error": None,
        }
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="predict_variant_effect", description="Predict protein variant effects")
def predict_variant_effect(
    sequence: str,
    mutation: str,
    model_location: str | None = None,
    scoring_strategy: str = "wt-marginals",
    offset_idx: int = 0,
    nogpu: bool = False,
):
    """
    Score a single point mutation using a pretrained LM.

    Parameters:
        sequence (str): Wildtype protein sequence.
        mutation (str): In the form 'A42G' (WT + 1-based position + MUT). offset_idx can shift position.
        model_location (str|None): Pretrained model name or path. Defaults to an ESM-1v model.
        scoring_strategy (str): 'wt-marginals' (default). Others not implemented in this minimal API.
        offset_idx (int): Position offset (e.g., 1 if your mutation indices are 1-based).
        nogpu (bool): Do not use GPU even if available.

    Returns:
        dict: success/result/error. result contains { score, model, strategy }
    """
    try:
        import re
        import torch

        sequence = sequence.strip()
        m = re.match(r"^([ACDEFGHIKLMNPQRSTVWY])(\d+)([ACDEFGHIKLMNPQRSTVWY])$", mutation.strip().upper())
        if not m:
            return {"success": False, "result": None, "error": "Invalid mutation format. Use like 'A42G'"}
        wt, pos_str, mt = m.group(1), m.group(2), m.group(3)
        pos = int(pos_str) - offset_idx  # convert to 0-based index
        if pos < 0 or pos >= len(sequence):
            return {"success": False, "result": None, "error": "Mutation position out of range after offset"}
        if sequence[pos].upper() != wt:
            return {"success": False, "result": None, "error": "Wildtype residue does not match sequence at position"}

        model_name = model_location or "esm1v_t33_650M_UR90S_1"
        model_obj, alphabet = pretrained.load_model_and_alphabet(model_name)
        model_obj = model_obj.eval()

        if torch.cuda.is_available() and not nogpu:
            model_obj = model_obj.cuda()

        batch_converter = alphabet.get_batch_converter()
        data = [("protein1", sequence)]
        batch_labels, batch_strs, batch_tokens = batch_converter(data)

        with torch.no_grad():
            if torch.cuda.is_available() and not nogpu:
                batch_tokens = batch_tokens.cuda()
            logits = model_obj(batch_tokens)["logits"]
            token_log_probs = torch.log_softmax(logits, dim=-1)

        wt_idx = alphabet.get_idx(wt)
        mt_idx = alphabet.get_idx(mt)
        # +1 for BOS token alignment
        score = (token_log_probs[0, 1 + pos, mt_idx] - token_log_probs[0, 1 + pos, wt_idx]).item()

        return {
            "success": True,
            "result": {
                "score": score,
                "model": model_name,
                "strategy": scoring_strategy,
                "position_0_based": pos,
            },
            "error": None,
        }
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

@mcp.tool(name="get_prediction_pdb", description="Fetch saved PDB by filename or latest from predictions directory")
def get_prediction_pdb(filename: str):
    """Return PDB content saved under predictions directory.

    Parameters:
        filename (str): Filename in predictions directory. Use "latest" to fetch the most recent file.

    Returns:
        dict: success/result/error. result contains { filename, pdb_content, path }
    """
    try:
        import glob
        predictions_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "predictions")
        if not os.path.isdir(predictions_dir):
            return {"success": False, "result": None, "error": f"Predictions dir not found: {predictions_dir}"}

        target_path: str
        if filename.strip().lower() == "latest":
            files = sorted(
                glob.glob(os.path.join(predictions_dir, "*.pdb")),
                key=lambda p: os.path.getmtime(p),
                reverse=True,
            )
            if not files:
                return {"success": False, "result": None, "error": "No PDB files found"}
            target_path = files[0]
            filename = os.path.basename(target_path)
        else:
            # prevent path traversal
            safe_name = os.path.basename(filename)
            target_path = os.path.join(predictions_dir, safe_name)
            if not os.path.isfile(target_path):
                return {"success": False, "result": None, "error": f"File not found: {safe_name}"}

        with open(target_path, "r") as f:
            content = f.read()

        return {
            "success": True,
            "result": {"filename": filename, "pdb_content": content, "path": target_path},
            "error": None,
        }
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

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
