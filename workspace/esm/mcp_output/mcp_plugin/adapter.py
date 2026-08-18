import os
import sys

# Set path
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
sys.path.insert(0, source_path)

# Import modules
try:
    from esm.pretrained import load_model_and_alphabet, load_model_and_alphabet_local
    from esm.data import Alphabet, BatchConverter
    from esm.inverse_folding import load_inverse_folding_model
    from esm.model import ESM1, ESM2, MSATransformer
    from examples.lm_design.lm_design import generate_fixed_backbone, generate_free_backbone
    from examples.variant_prediction.predict import predict_variant_effect
    from scripts.extract import extract_features
    from scripts.fold import predict_structure
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
            return {"status": "success", "model": model, "alphabet": alphabet}
        except Exception as e:
            return {"status": "error", "message": f"Failed to load model: {e}"}

    def load_inverse_folding_model(self, model_name):
        """
        Load inverse folding model.

        Parameters:
        - model_name: str, model name.

        Returns:
        - dict: Information containing status and model instance.
        """
        try:
            model = load_inverse_folding_model(model_name)
            self.models[model_name] = model
            return {"status": "success", "model": model}
        except Exception as e:
            return {"status": "error", "message": f"Failed to load inverse folding model: {e}"}

    # ------------------------- Data Processing Module -------------------------

    def create_alphabet(self):
        """
        Create alphabet for protein sequences.

        Returns:
        - dict: Information containing status and Alphabet instance.
        """
        try:
            alphabet = Alphabet()
            return {"status": "success", "alphabet": alphabet}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create alphabet: {e}"}

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
            return {"status": "success", "batch_converter": batch_converter}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create batch converter: {e}"}

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
            return {"status": "success", "model": model}
        except Exception as e:
            return {"status": "error", "message": f"Failed to instantiate ESM1 model: {e}"}

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
            return {"status": "success", "model": model}
        except Exception as e:
            return {"status": "error", "message": f"Failed to instantiate ESM2 model: {e}"}

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
            return {"status": "success", "model": model}
        except Exception as e:
            return {"status": "error", "message": f"Failed to instantiate MSA Transformer model: {e}"}

      # ------------------------- Function Call Module -------------------------

    def generate_fixed_backbone(self, model, alphabet, pdb_file, chain_id, temperature=1.0, num_samples=1):
        """
        Call fixed backbone generation function.

        Parameters:
        - model: ESM model instance
        - alphabet: Alphabet instance
        - pdb_file: str, path to PDB file
        - chain_id: str, chain identifier
        - temperature: float, sampling temperature (default: 1.0)
        - num_samples: int, number of samples to generate (default: 1)

        Returns:
        - dict: Information containing status and generation result.
        """
        try:
            result = generate_fixed_backbone(
                model=model,
                alphabet=alphabet,
                pdb_file=pdb_file,
                chain_id=chain_id,
                temperature=temperature,
                num_samples=num_samples
            )
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to generate fixed backbone: {e}"}

    def generate_free_backbone(self, model, alphabet, length, temperature=1.0, num_samples=1, device="cpu"):
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
            result = generate_free_backbone(
                model=model,
                alphabet=alphabet,
                length=length,
                temperature=temperature,
                num_samples=num_samples,
                device=device
            )
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to generate free backbone: {e}"}

    def predict_variant_effect(self, model, alphabet, sequence, mutations, batch_size=1, device="cpu"):
        """
        Call variant effect prediction function.

        Parameters:
        - model: ESM model instance
        - alphabet: Alphabet instance
        - sequence: str, wild-type protein sequence
        - mutations: list, list of mutations in format ["A123V", "G456D"]
        - batch_size: int, batch size for processing (default: 1)
        - device: str, device to use for computation (default: "cpu")

        Returns:
        - dict: Information containing status and prediction result.
        """
        try:
            result = predict_variant_effect(
                model=model,
                alphabet=alphabet,
                sequence=sequence,
                mutations=mutations,
                batch_size=batch_size,
                device=device
            )
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to predict variant effect: {e}"}

    def extract_features(self, model, alphabet, sequences, repr_layers=[-1], include_contacts=False, device="cpu"):
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
            result = extract_features(
                model=model,
                alphabet=alphabet,
                sequences=sequences,
                repr_layers=repr_layers,
                include_contacts=include_contacts,
                device=device
            )
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to extract features: {e}"}

    def predict_structure_local(self, model, alphabet, sequence, device="cpu"):
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
            result = predict_structure(
                model=model,
                alphabet=alphabet,
                sequence=sequence,
                device=device
            )
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to predict structure: {e}"}

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
                
                return {"status": "success", "result": structure_info}
            else:
                return {"status": "error", "message": f"API returned error: {response.status_code}"}
                
        except requests.exceptions.Timeout:
            return {"status": "error", "message": "ESMFold API request timed out"}
        except Exception as e:
            return {"status": "error", "message": f"Error predicting structure: {e}"}

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
            
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to analyze sequence: {e}"}

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
            
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to validate sequence: {e}"}

    # ------------------------- Fallback Mode Handling -------------------------

    def fallback_mode(self):
        """
        Enable fallback mode, prompting the user that some functions are unavailable.
        """
        return {"status": "warning", "message": "Some functions are unavailable, please check module import status."}