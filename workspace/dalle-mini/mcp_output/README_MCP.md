# DALL-E Mini MCP Plugin

## Overview

DALL-E Mini is an open-source implementation of OpenAI's DALL-E, a model capable of generating images from textual descriptions. This repository provides tools for training, inference, and deployment of the DALL-E Mini model. It includes a modular architecture for customization and scalability, making it suitable for research and production use.

This plugin integrates DALL-E Mini into the MCP (Modular Computational Platform) ecosystem, enabling seamless interaction with the model for tasks such as image generation, dataset preparation, and model training.

- **Repository**: [borisdayma/dalle-mini](https://github.com/borisdayma/dalle-mini)
- **Commit**: `f0be4de610285a002052024a1e096126f9452cc4`

## Features

- **Image Generation**: Generate images from textual prompts using pre-trained DALL-E Mini models.
- **Training Tools**: Train or fine-tune the model with custom datasets.
- **Inference Pipelines**: Run inference pipelines for batch or interactive use cases.
- **Deployment**: Tools for deploying the model using Docker or web-based interfaces (Gradio and Streamlit).
- **Custom Configurations**: Easily modify model configurations for different scales (e.g., mini, micro, mega).

## Installation

### Prerequisites

Ensure the following dependencies are installed:

- Python 3.8 or higher
- `torch`, `transformers`, `numpy`
- Optional: `wandb`, `optuna` for advanced logging and hyperparameter optimization

### Installation Steps

1. Clone the repository:
   ```
   git clone https://github.com/borisdayma/dalle-mini.git
   cd dalle-mini
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. (Optional) Install additional tools for development:
   ```
   pip install wandb optuna
   ```

4. Build the Docker image (if using Docker):
   ```
   cd Docker
   ./build_docker.sh
   ```

## Usage

### CLI Commands

The repository provides several CLI commands for interacting with the DALL-E Mini model:

1. **Training**:
   ```
   python source/tools/train/train.py --config path/to/config.json
   ```
   - Description: Train the DALL-E Mini model using a specified configuration file.
   - Example: Use `tools/train/config/mini/config.json` for training the mini model.

2. **Inference**:
   ```
   python source/tools/inference/inference_pipeline.py --input path/to/input.txt --output path/to/output/
   ```
   - Description: Run inference to generate images from textual prompts.
   - Example: Provide a text file with prompts and specify an output directory for generated images.

### Web Interfaces

- **Gradio App**:
  ```
  python app/gradio/app.py
  ```
  - Launches a Gradio-based web interface for interactive image generation.

- **Streamlit App**:
  ```
  python app/streamlit/app.py
  ```
  - Launches a Streamlit-based web interface for interactive image generation.

### Docker Deployment

1. Build the Docker image:
   ```
   ./Docker/build_docker.sh
   ```

2. Run the Docker container:
   ```
   docker run -p 7860:7860 dalle-mini
   ```

3. Access the web interface at `http://localhost:7860`.

## Tool Endpoints

The following tools and scripts are available in the repository:

### Dataset Tools
- `tools/dataset/encode_dataset.ipynb`: Encode datasets for training or inference.

### Training Tools
- `tools/train/train.py`: Main script for training the model.
- `tools/train/config/`: Configuration files for different model scales (mini, micro, mega, etc.).
- `tools/train/scalable_shampoo/`: Advanced optimizers and utilities for scalable training.

### Inference Tools
- `tools/inference/inference_pipeline.ipynb`: Notebook for running inference pipelines.
- `tools/inference/run_infer_notebook.sh`: Script to execute inference notebooks.

### Deployment Tools
- `Docker/`: Scripts and Dockerfiles for containerized deployment.

## Notes and Troubleshooting

### Common Issues

1. **Dependency Conflicts**:
   - Ensure all required dependencies are installed with compatible versions.
   - Use a virtual environment to isolate the project.

2. **CUDA Errors**:
   - Verify that your system has a compatible GPU and CUDA drivers installed.
   - Check PyTorch installation with `torch.cuda.is_available()`.

3. **Out of Memory**:
   - Reduce batch size or use a smaller model configuration (e.g., `mini` instead of `mega`).

4. **Docker Issues**:
   - Ensure Docker is installed and running.
   - Check for sufficient disk space before building the Docker image.

### Additional Resources

- [DALL-E Mini Documentation](https://github.com/borisdayma/dalle-mini)
- [PyTorch Documentation](https://pytorch.org/docs/)
- [Transformers Documentation](https://huggingface.co/docs/transformers/)

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch for your feature or bug fix.
3. Submit a pull request with a detailed description of your changes.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

---

For further questions or support, please open an issue on the [GitHub repository](https://github.com/borisdayma/dalle-mini/issues).