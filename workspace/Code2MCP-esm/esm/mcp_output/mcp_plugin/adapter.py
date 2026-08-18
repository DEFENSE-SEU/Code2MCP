import os
import sys

# Set path
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
sys.path.insert(0, source_path)

# Minimal, stable imports only; avoid examples/scripts at import time
try:
    from esm.pretrained import load_model_and_alphabet, load_model_and_alphabet_local
    from esm import pretrained, inverse_folding
    from esm.data import Alphabet, BatchConverter
    from esm.model import ESM1, ESM2, MSATransformer
except ImportError as e:
    print(f"Module import failed: {e}, some functions will be unavailable.")

class Adapter:
    """
    MCP Import mode adapter class for encapsulating core functionality of facebookresearch/esm repository.
    """

    def __init__(self):
        """
        Initialize adapter class.
        """
        self.mode = "import"
        self.models = {}

    # ------------------------- Model Loading Module -------------------------

    def load_pretrained_model(self, model_name, local_path=None):
        """
        Load pre-trained model.

        Parameters:
        - model_name: str, model name.
        - local_path: str, optional, local model path.

        Returns:
        - dict: Information containing status and model instance.
        """
        try:
            if local_path:
                model, alphabet = load_model_and_alphabet_local(local_path)
            else:
                model, alphabet = load_model_and_alphabet(model_name)
            self.models[model_name] = model
            return {"success": True, "result": {"model": model, "alphabet": alphabet}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to load model: {e}"}

    def load_inverse_folding_model(self, model_name="esm_if1_gvp4_t16_142M_UR50"):
        """
        Load inverse folding model.

        Parameters:
        - model_name: str, model name.

        Returns:
        - dict: Information containing status and model instance.
        """
        try:
            # Use pretrained helper consistent with service
            model, _alphabet = getattr(pretrained, model_name)() if hasattr(pretrained, model_name) else pretrained.esm_if1_gvp4_t16_142M_UR50()
            self.models[model_name] = model
            return {"success": True, "result": {"model_name": model_name}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to load inverse folding model: {e}"}

    # ------------------------- Data Processing Module -------------------------

    def create_alphabet(self):
        """
        Create alphabet for protein sequences.

        Returns:
        - dict: Information containing status and Alphabet instance.
        """
        try:
            alphabet = Alphabet()
            return {"success": True, "result": {"alphabet": alphabet}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to create alphabet: {e}"}

    def create_batch_converter(self, alphabet):
        """
        Create batch converter.

        Parameters:
        - alphabet: Alphabet instance.

        Returns:
        - dict: Information containing status and BatchConverter instance.
        """
        try:
            batch_converter = BatchConverter(alphabet)
            return {"success": True, "result": {"batch_converter": batch_converter}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to create batch converter: {e}"}

    # ------------------------- Model Instantiation Module -------------------------

    def create_esm1_model(self, num_layers=12, embed_dim=768, attention_heads=12, alphabet_size=33):
        """
        Instantiate ESM1 model.

        Parameters:
        - num_layers: int, number of transformer layers (default: 12)
        - embed_dim: int, embedding dimension (default: 768)
        - attention_heads: int, number of attention heads (default: 12)
        - alphabet_size: int, size of the alphabet (default: 33)

        Returns:
        - dict: Information containing status and ESM1 instance.
        """
        try:
            model = ESM1(
                num_layers=num_layers,
                embed_dim=embed_dim,
                attention_heads=attention_heads,
                alphabet_size=alphabet_size
            )
            return {"success": True, "result": {"model": model}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to instantiate ESM1 model: {e}"}

    def create_esm2_model(self, num_layers=33, embed_dim=1280, attention_heads=20, alphabet_size=33):
        """
        Instantiate ESM2 model.

        Parameters:
        - num_layers: int, number of transformer layers (default: 33)
        - embed_dim: int, embedding dimension (default: 1280)
        - attention_heads: int, number of attention heads (default: 20)
        - alphabet_size: int, size of the alphabet (default: 33)

        Returns:
        - dict: Information containing status and ESM2 instance.
        """
        try:
            model = ESM2(
                num_layers=num_layers,
                embed_dim=embed_dim,
                attention_heads=attention_heads,
                alphabet_size=alphabet_size
            )
            return {"success": True, "result": {"model": model}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to instantiate ESM2 model: {e}"}

    def create_msa_transformer(self, num_layers=12, embed_dim=768, attention_heads=12, max_tokens_per_msa=2**14):
        """
        Instantiate MSA Transformer model.

        Parameters:
        - num_layers: int, number of transformer layers (default: 12)
        - embed_dim: int, embedding dimension (default: 768)
        - attention_heads: int, number of attention heads (default: 12)
        - max_tokens_per_msa: int, maximum tokens per MSA (default: 2**14)

        Returns:
        - dict: Information containing status and MSATransformer instance.
        """
        try:
            model = MSATransformer(
                num_layers=num_layers,
                embed_dim=embed_dim,
                attention_heads=attention_heads,
                max_tokens_per_msa=max_tokens_per_msa
            )
            return {"success": True, "result": {"model": model}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to instantiate MSA Transformer model: {e}"}

      # ------------------------- Function Call Module -------------------------

    def generate_fixed_backbone(self, pdbfile, chain_id=None, temperature=1.0, num_samples=1, multichain_backbone=False, nogpu=False):
        """
        Call fixed backbone generation function.

        Parameters:
        - pdbfile: str, path to PDB/CIF file
        - chain_id: str or None, chain identifier (ignored when multichain)
        - temperature: float, sampling temperature (default: 1.0)
        - num_samples: int, number of samples to generate (default: 1)
        - multichain_backbone: bool, condition on complex if True
        - nogpu: bool, force CPU

        Returns:
        - dict: Information containing status and generation result.
        """
        try:
            import torch
            model_obj, _alphabet = pretrained.esm_if1_gvp4_t16_142M_UR50()
            model_obj = model_obj.eval()

            sampled, recoveries = [], []

            if not torch.cuda.is_available() or nogpu:
                device = torch.device("cpu")
            else:
                model_obj = model_obj.cuda()
                device = torch.device("cuda")

            if multichain_backbone:
                structure = inverse_folding.util.load_structure(pdbfile)
                coords, native_seqs = inverse_folding.multichain_util.extract_coords_from_complex(structure)
                target_chain_id = chain_id if (chain_id in native_seqs if chain_id is not None else False) else next(iter(native_seqs.keys()))
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
                coords, native_seq = inverse_folding.util.load_coords(pdbfile, chain_id)
                for _ in range(num_samples):
                    sampled_seq = model_obj.sample(coords, temperature=temperature, device=device)
                    sampled.append(sampled_seq)
                    try:
                        recoveries.append(sum(a == b for a, b in zip(native_seq, sampled_seq)) / max(1, len(native_seq)))
                    except Exception:
                        recoveries.append(None)

            return {"success": True, "result": {"sampled_sequences": sampled, "recovery": recoveries}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to generate fixed backbone: {e}"}

    def generate_free_backbone(self, *args, **kwargs):
        """
        Call free backbone generation function.

        Parameters:
        - model: ESM model instance
        - alphabet: Alphabet instance
        - length: int, desired sequence length
        - temperature: float, sampling temperature (default: 1.0)
        - num_samples: int, number of samples to generate (default: 1)
        - device: str, device to use for computation (default: "cpu")

        Returns:
        - dict: Information containing status and generation result.
        """
        try:
            return {"success": False, "result": None, "error": "free_backbone generation is not exposed in MCP"}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to handle free backbone: {e}"}

    def predict_variant_effect(self, sequence, mutation, model_location=None, scoring_strategy="wt-marginals", offset_idx=0, nogpu=False):
        """
        Call variant effect prediction function.

        Parameters:
        - sequence: str, wild-type protein sequence
        - mutation: str, single mutation like "A42G" (WT, 1-based pos, MUT)
        - model_location: optional model name/path (default ESM-1v)
        - scoring_strategy: currently only "wt-marginals"
        - offset_idx: int, position offset
        - nogpu: bool

        Returns:
        - dict: Information containing status and prediction result.
        """
        try:
            import re
            import torch

            sequence = sequence.strip()
            m = re.match(r"^([ACDEFGHIKLMNPQRSTVWY])(\d+)([ACDEFGHIKLMNPQRSTVWY])$", mutation.strip().upper())
            if not m:
                return {"success": False, "result": None, "error": "Invalid mutation format. Use like 'A42G'"}
            wt, pos_str, mt = m.group(1), m.group(2), m.group(3)
            pos = int(pos_str) - offset_idx
            if pos < 0 or pos >= len(sequence):
                return {"success": False, "result": None, "error": "Mutation position out of range after offset"}
            if sequence[pos].upper() != wt:
                return {"success": False, "result": None, "error": "Wildtype residue does not match sequence at position"}

            model_name = model_location or "esm1v_t33_650M_UR90S_1"
            model_obj, alphabet = load_model_and_alphabet(model_name)
            model_obj = model_obj.eval()
            if torch.cuda.is_available() and not nogpu:
                model_obj = model_obj.cuda()

            batch_converter = alphabet.get_batch_converter()
            data = [("protein1", sequence)]
            _labels, _strs, batch_tokens = batch_converter(data)
            with torch.no_grad():
                if torch.cuda.is_available() and not nogpu:
                    batch_tokens = batch_tokens.cuda()
                logits = model_obj(batch_tokens)["logits"]
                token_log_probs = torch.log_softmax(logits, dim=-1)

            wt_idx = alphabet.get_idx(wt)
            mt_idx = alphabet.get_idx(mt)
            score = (token_log_probs[0, 1 + pos, mt_idx] - token_log_probs[0, 1 + pos, wt_idx]).item()

            return {"success": True, "result": {"score": score, "model": model_name, "strategy": scoring_strategy, "position_0_based": pos}, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to predict variant effect: {e}"}

    def extract_features(self, *args, **kwargs):
        """
        Call feature extraction function.

        Parameters:
        - model: ESM model instance
        - alphabet: Alphabet instance
        - sequences: list, list of protein sequences
        - repr_layers: list, layers to extract representations from (default: [-1])
        - include_contacts: bool, whether to include contact predictions (default: False)
        - device: str, device to use for computation (default: "cpu")

        Returns:
        - dict: Information containing status and extraction result.
        """
        try:
            return {"success": False, "result": None, "error": "extract_features not exposed via Adapter"}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to handle extract_features: {e}"}

    def predict_structure_local(self, *args, **kwargs):
        """
        Call local structure prediction function.

        Parameters:
        - model: ESM model instance
        - alphabet: Alphabet instance
        - sequence: str, protein sequence
        - device: str, device to use for computation (default: "cpu")

        Returns:
        - dict: Information containing status and prediction result.
        """
        try:
            return {"success": False, "result": None, "error": "local structure prediction is not exposed via Adapter"}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to handle predict_structure_local: {e}"}

    def predict_structure(self, sequence):
        """
        Predict protein structure using ESMFold API.

        Parameters:
        - sequence: str, protein amino acid sequence.

        Returns:
        - dict: Information containing status and prediction result.
        """
        try:
            import requests
            from Bio.PDB import PDBParser
            import io
            
            response = requests.post(
                "https://api.esmatlas.com/foldSequence/v1/pdb/", 
                data=sequence, 
                timeout=300
            )
            
            if response.status_code == 200 and response.text.strip():
                parser = PDBParser(QUIET=True)
                pdb_io = io.StringIO(response.text)
                structure = parser.get_structure("esmfold_prediction", pdb_io)
                
                structure_info = {
                    "num_models": len(structure),
                    "num_chains": len(list(structure.get_chains())),
                    "num_residues": len(list(structure.get_residues())),
                    "num_atoms": len(list(structure.get_atoms())),
                    "pdb_content": response.text
                }
                return {"success": True, "result": structure_info, "error": None}
            else:
                return {"success": False, "result": None, "error": f"API returned error: {response.status_code}"}
                
        except requests.exceptions.Timeout:
            return {"success": False, "result": None, "error": "ESMFold API request timed out"}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Error predicting structure: {e}"}

    def analyze_protein_sequence(self, sequence):
        """
        Analyze basic features of a protein sequence.

        Parameters:
        - sequence: str, protein sequence.

        Returns:
        - dict: Information containing status and analysis result.
        """
        try:
            length = len(sequence)
            amino_acids = set(sequence)
            
            composition = {}
            for aa in amino_acids:
                composition[aa] = sequence.count(aa)
            
            result = {
                "length": length,
                "unique_amino_acids": len(amino_acids),
                "composition": composition,
                "sequence": sequence
            }
            return {"success": True, "result": result, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to analyze sequence: {e}"}

    def validate_protein_sequence(self, sequence):
        """
        Validate protein sequence format.

        Parameters:
        - sequence: str, protein sequence.

        Returns:
        - dict: Information containing status and validation result.
        """
        try:
            valid_amino_acids = set("ACDEFGHIKLMNPQRSTVWY")
            sequence_upper = sequence.upper()
            
            invalid_chars = set(sequence_upper) - valid_amino_acids
            
            is_valid = len(invalid_chars) == 0
            
            result = {
                "is_valid": is_valid,
                "invalid_characters": list(invalid_chars) if invalid_chars else [],
                "length": len(sequence),
                "uppercase_sequence": sequence_upper
            }
            return {"success": True, "result": result, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": f"Failed to validate sequence: {e}"}

    # ------------------------- Fallback Mode Handling -------------------------

    def fallback_mode(self):
        """
        Enable fallback mode, prompting the user that some functions are unavailable.
        """
        return {"success": False, "result": None, "error": "Some functions are unavailable, please check module import status."}