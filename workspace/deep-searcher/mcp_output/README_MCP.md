# Deep Searcher MCP Plugin

## Overview

Deep Searcher is a modular and extensible framework designed for advanced search and retrieval tasks. It integrates multiple components, including embeddings, large language models (LLMs), vector databases, and data loaders, to provide a comprehensive solution for deep search applications. The framework supports both offline and online query processing, making it suitable for a wide range of use cases.

This repository contains the MCP (Modular Component Plugin) for Deep Searcher, enabling seamless integration with various tools and services. The plugin is designed to be flexible, scalable, and easy to use, with a focus on simplifying complex search workflows.

## Features

- **Embeddings**: Support for multiple embedding methods, including OpenAI, Sentence Transformers, Milvus, and more.
- **LLMs**: Integration with popular LLMs such as OpenAI, Bedrock, and Anthropic.
- **Vector Databases**: Compatibility with Milvus, Qdrant, Azure Search, and Oracle DB.
- **Data Loaders**: File loaders for PDFs, JSON, text files, and web crawlers for online data.
- **Command-Line Interface (CLI)**: A user-friendly CLI for managing and interacting with the framework.
- **Extensibility**: Modular design for easy customization and integration with new tools.

## Installation

### Prerequisites

Ensure you have the following installed on your system:

- Python 3.8 or higher
- `pip` (Python package manager)
- Docker (optional, for containerized deployment)

### Steps

1. Clone the repository:
   ```
   git clone https://github.com/zilliztech/deep-searcher.git
   cd deep-searcher
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

   Alternatively, if using `pyproject.toml`:
   ```
   pip install .
   ```

3. Configure the environment:
   - Copy the example environment file:
     ```
     cp env.example .env
     ```
   - Update `.env` with your configuration details.

4. Run the application:
   ```
   python main.py
   ```

## Usage

### Command-Line Interface (CLI)

Deep Searcher provides a CLI for managing and interacting with the framework. Below are some common commands:

- **Start the CLI**:
  ```
  deepsearcher-cli
  ```

- **Load local files**:
  ```
  deepsearcher-cli load --file path/to/file.txt
  ```

- **Query a vector database**:
  ```
  deepsearcher-cli query --db milvus --query "search term"
  ```

- **Run a web crawler**:
  ```
  deepsearcher-cli crawl --url https://example.com
  ```

### Examples

Refer to the `examples/` directory for detailed usage examples:

- Basic example: `examples/basic_example.py`
- Using Azure Search: `examples/basic_example_azuresearch.py`
- Loading local files: `examples/load_local_file_using_unstructured.py`
- Crawling websites: `examples/load_website_using_firecrawl.py`

### Configuration

Configuration files are located in the `deepsearcher/config.yaml` directory. Update these files to customize embeddings, LLMs, vector databases, and other components.

## Available Endpoints

### Embedding Methods

- OpenAI Embedding
- Sentence Transformer Embedding
- Milvus Embedding
- Bedrock Embedding
- FastEmbed Embedding
- Novita Embedding
- Volcengine Embedding
- WatsonX Embedding

### LLM Integrations

- OpenAI
- Bedrock
- Anthropic
- Azure OpenAI
- Together AI
- Ollama
- Novita
- SiliconFlow

### Vector Databases

- Milvus
- Qdrant
- Azure Search
- Oracle DB

### Data Loaders

#### File Loaders

- PDF Loader
- JSON Loader
- Text Loader
- Unstructured Loader

#### Web Crawlers

- Firecrawl Crawler
- Docling Crawler
- Jina Crawler
- Crawl4AI Crawler

## Notes and Troubleshooting

### Common Issues

1. **Dependency Errors**:
   - Ensure all required dependencies are installed. Run `pip install -r requirements.txt` to resolve missing packages.

2. **Configuration Issues**:
   - Verify that the `.env` file and `config.yaml` are correctly set up.

3. **Database Connection Errors**:
   - Check the connection details for vector databases in the configuration file.

4. **Web Crawler Failures**:
   - Ensure the target website is accessible and not blocking crawlers.

### Debugging

Enable debug mode by setting the `DEBUG` flag in the `.env` file:
```
DEBUG=true
```

Logs are stored in the `logs/` directory for further analysis.

## Contributing

We welcome contributions to Deep Searcher! Please refer to the `CONTRIBUTING.md` file for guidelines on how to get started.

## License

This project is licensed under the [MIT License](LICENSE).

## Support

For questions or support, please open an issue in the [GitHub repository](https://github.com/zilliztech/deep-searcher/issues).

---

Thank you for using Deep Searcher MCP Plugin!