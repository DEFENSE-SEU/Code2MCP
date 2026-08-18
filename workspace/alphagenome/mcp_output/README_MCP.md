# AlphaGenome MCP Plugin

## Overview

AlphaGenome is Google DeepMind's deep learning model designed to decode the regulatory code within DNA sequences. This repository contains the AlphaGenome MCP Plugin, a Python client library that enables researchers to interact with the AlphaGenome API for genomic sequence analysis. The plugin provides tools for submitting genomic sequences, retrieving predictions, scoring variants, and visualizing results.

### Key Features

- **Multimodal Predictions**: Analyze DNA sequences for gene expression, splicing patterns, chromatin features, and contact maps.
- **High Resolution**: Predictions at single base-pair resolution for most outputs.
- **Batch Processing**: Efficiently score and analyze thousands of variants.
- **Visualization Tools**: Generate plots for genomic predictions and annotations.
- **Tissue-Specific Analysis**: Use ontology terms for biological context mapping.

The AlphaGenome API is free for non-commercial use and is optimized for small to medium-scale analyses.

---

## Installation

### Prerequisites

Ensure the following dependencies are installed:

- Python 3.8 or higher
- Required Python packages:
  - `numpy`
  - `pandas`
  - `matplotlib`
  - `tensorflow`
  - `protobuf`
- Optional packages for enhanced functionality:
  - `jupyter`
  - `seaborn`

### Steps

1. Clone the repository:
   ```
   git clone https://github.com/google-deepmind/alphagenome.git
   cd alphagenome
   ```

2. Install the package using `pip`:
   ```
   pip install .
   ```

3. Verify installation:
   ```
   python -c "import alphagenome; print('AlphaGenome installed successfully')"
   ```

---

## Usage

### Authentication

To use the AlphaGenome API, you need an API key. Create a client instance using the following code:

```python
from alphagenome.dna_client import create

client = create(api_key="YOUR_API_KEY")
```

### Common Workflows

#### Single Variant Analysis

Analyze individual variants by comparing reference and alternate sequences:

```python
from alphagenome.genome import Variant

variant = Variant(chromosome="chr1", position=12345, reference_bases="A", alternate_bases="T")
result = client.predict_variant(variant)
print(result)
```

#### Batch Variant Scoring

Process multiple variants efficiently:

```python
from alphagenome.genome import Variant

variants = [
    Variant(chromosome="chr1", position=12345, reference_bases="A", alternate_bases="T"),
    Variant(chromosome="chr2", position=67890, reference_bases="G", alternate_bases="C")
]
scores = client.score_variants(variants)
print(scores)
```

#### Visualization

Generate plots for genomic predictions:

```python
from alphagenome.visualization.plot_components import plot

plot(tracks=result.tracks, annotations=result.annotations)
```

---

## Tool Endpoints

### Core Client (`dna_client`)

- `create(api_key)`: Initialize the client.
- `predict_sequence(sequence)`: Analyze raw DNA sequences.
- `predict_interval(interval)`: Predict properties for genomic intervals.
- `predict_variant(variant)`: Compare reference and alternate sequences for variants.
- `score_variant(variant)`: Calculate variant effect scores.
- `score_variants(variants)`: Batch process multiple variants.

### Data Structures

- `genome.Interval`: Represents genomic coordinates (chromosome, start, end).
- `genome.Variant`: Represents genetic variants (chromosome, position, reference bases, alternate bases).
- `track_data.TrackData`: Contains model prediction outputs.
- `anndata.AnnData`: Stores variant scores and metadata.

### Visualization Tools

- `plot_components.plot(tracks, annotations)`: Main plotting function.
- `plot_components.OverlaidTracks`: Overlay multiple prediction tracks.
- `plot_components.VariantAnnotation`: Annotate variant positions on plots.

---

## Notes and Troubleshooting

### Notes

- The AlphaGenome API supports sequences up to 1 million base pairs in length.
- Predictions can be tissue-specific using ontology terms (e.g., `UBERON:0001157`).

### Troubleshooting

#### Common Issues

1. **Authentication Error**: Ensure your API key is valid and correctly set.
2. **Dependency Errors**: Verify all required Python packages are installed.
3. **Visualization Issues**: Ensure `matplotlib` and `seaborn` are installed for plotting.

#### Debugging

Enable verbose logging for detailed error messages:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Contributing

We welcome contributions to the AlphaGenome MCP Plugin. Please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) file for guidelines on how to contribute.

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

---

## Support

For questions or issues, please open a GitHub issue in the [repository](https://github.com/google-deepmind/alphagenome/issues).