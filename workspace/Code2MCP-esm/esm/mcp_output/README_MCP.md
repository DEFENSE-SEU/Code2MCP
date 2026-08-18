# ESM: Evolutionary Scale Modeling for Protein Sequences

## Overview

`facebookresearch/esm` is an open-source project developed by Facebook AI Research (FAIR) for deep learning-based protein sequence modeling. It provides state-of-the-art tools for analyzing and predicting protein structures, functions, and variant effects using advanced language models and deep learning techniques.

### Key Features

- **Protein Language Models**: Pretrained models like ESM-1 and ESM-2 capture semantic information in protein sequences.
- **Multiple Sequence Alignment (MSA) Modeling**: Tools for protein modeling based on MSA, including MSA Transformer.
- **Inverse Folding**: Predict how protein sequences fold into 3D structures.
- **Variant Effect Prediction**: Assess the impact of mutations on protein functionality.
- **Contact Prediction**: Predict residue-residue contacts in protein sequences.
- **Metagenomic Analysis**: Analyze environmental protein sequences using the ESM Metagenomic Atlas.
- **Feature Extraction**: Tools like `esm-extract` for extracting features from pretrained models.

This repository is designed for researchers and developers in computational biology, bioinformatics, and related fields.

---

## Installation

### Prerequisites

- Python 3.8 or later
- PyTorch 1.8 or later
- GPU support (optional but recommended for large-scale computations)

### Installation Steps

1. Clone the repository:
   ```
   git clone https://github.com/facebookresearch/esm.git
   cd esm
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. (Optional) Set up a virtual environment:
   ```
   python -m venv esm_env
   source esm_env/bin/activate
   ```

4. Install the package:
   ```
   pip install .
   ```

5. (Optional) Install additional dependencies for specific features:
   ```
   pip install fairscale pandas
   ```

---

## Usage

### Loading Pretrained Models

The repository provides pretrained models for various tasks. You can load a model using the following example:

```
from esm.pretrained import load_model_and_alphabet
model, alphabet = load_model_and_alphabet("esm2_t33_650M_UR50D")
```

### Command-Line Tools

The repository includes several command-line tools for common tasks:

#### 1. `esm-extract`
Extract features from protein sequences using pretrained models.

**Usage:**
```
esm-extract --model esm2_t33_650M_UR50D --fasta input.fasta --output output.pt
```

#### 2. `esm-fold`
Predict the 3D structure of a protein sequence.

**Usage:**
```
esm-fold --model esm2_t33_650M_UR50D --fasta input.fasta --output output.pdb
```

---

## Available Tools and Endpoints

### Core Modules

- **`esm.pretrained`**: Load pretrained models.
  - Functions: `load_model_and_alphabet`, `load_model_and_alphabet_local`
- **`esm.data`**: Handle protein sequence data.
  - Functions: `Alphabet`, `BatchConverter`
- **`esm.inverse_folding`**: Tools for inverse folding tasks.
  - Functions: `load_inverse_folding_model`
  - Classes: `GVPTransformerEncoder`, `GVPTransformerDecoder`
- **`esm.model`**: Core model definitions.
  - Classes: `ESM1`, `ESM2`, `MSATransformer`

### CLI Commands

- **`esm-extract`**: Extract features from protein sequences.
- **`esm-fold`**: Predict protein 3D structures.

---

## Notes and Troubleshooting

### Notes

1. **Model Size**: Pretrained models like ESM-2 are large and may require significant memory. Use a GPU for optimal performance.
2. **Dependencies**: Ensure all required dependencies are installed. Optional dependencies like `fairscale` and `pandas` are needed for specific features.
3. **Input Formats**: Protein sequences should be provided in FASTA format for most tools.

### Troubleshooting

- **Out of Memory Errors**: If you encounter memory issues, try reducing batch size or using a smaller model.
- **Installation Issues**: Ensure you are using a compatible Python and PyTorch version.
- **Model Loading Errors**: Verify the model name and ensure the model weights are downloaded correctly.

---

## Contributing

We welcome contributions to improve the repository. Please follow the guidelines in the `CONTRIBUTING.md` file.

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

---

## Acknowledgments

This repository is developed and maintained by Facebook AI Research (FAIR). For more information, visit the [official repository](https://github.com/facebookresearch/esm).