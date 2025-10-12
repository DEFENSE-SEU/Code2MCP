# TextBlob MCP (Model Context Protocol) Service README

## Project Introduction

TextBlob is a Python library designed for processing textual data, offering a simple API for common natural language processing (NLP) tasks. It provides developers with tools for tokenization, part-of-speech tagging, noun phrase extraction, sentiment analysis, text classification, and more. Built on top of NLTK and Pattern libraries, TextBlob simplifies complex NLP operations, making them accessible without requiring deep expertise in computational linguistics.

## Installation Method

To install TextBlob, ensure you have Python 3.9 or higher. TextBlob requires the following dependencies:
- `nltk` (required)
- `pattern` (required)
- `numpy` (optional)

Install TextBlob using pip:
```
pip install textblob
```

Additionally, download the necessary corpora for `nltk`:
```
python -m textblob.download_corpora
```

## Quick Start

Here’s how to get started with TextBlob MCP (Model Context Protocol):

1. **Create a TextBlob instance**:
   ```
   from textblob import TextBlob
   blob = TextBlob("TextBlob makes NLP simple.")
   ```

2. **Perform NLP tasks**:
   - **Tokenization**: `blob.words` or `blob.sentences`
   - **Part-of-Speech Tagging**: `blob.tags`
   - **Noun Phrase Extraction**: `blob.noun_phrases`
   - **Sentiment Analysis**: `blob.sentiment`
   - **Word Inflection**: `blob.words[0].pluralize()`

3. **Text Classification**:
   ```
   from textblob.classifiers import NaiveBayesClassifier
   train = [("I love this library", "pos"), ("I hate bugs", "neg")]
   classifier = NaiveBayesClassifier(train)
   classifier.classify("This is amazing!")  # Output: 'pos'
   ```

## Available Tools and Endpoints List

TextBlob MCP provides the following services:

- **TextBlob Class**: Main interface for text processing tasks.
- **Word and Sentence Tokenizers**: Break text into words or sentences.
- **Part-of-Speech Taggers**: Assign grammatical tags to words.
- **Noun Phrase Extractors**: Identify noun phrases in text.
- **Sentiment Analyzers**: Calculate polarity and subjectivity of text.
- **Inflection Services**: Singularize, pluralize, and lemmatize words.
- **Classification Services**: Categorize text using Naive Bayes or custom classifiers.
- **WordNet Integration**: Access synonyms, antonyms, and definitions.

## Common Issues and Notes

- **Dependencies**: Ensure `nltk` and `pattern` are installed. Use `python -m textblob.download_corpora` to download required corpora.
- **Environment**: TextBlob supports Python 3.9 and above. Compatibility with older versions is not guaranteed.
- **Performance**: For large-scale text processing, consider optimizing corpora downloads and using efficient tokenizers.
- **Removed Features**: Translation functionality has been removed. Use external APIs like Google Translate for translation tasks.

## Reference Links or Documentation

- [TextBlob GitHub Repository](https://github.com/sloria/TextBlob)
- [Official Documentation](https://textblob.readthedocs.io/en/dev/)
- [NLTK Documentation](http://nltk.org/)
- [Pattern Library](https://github.com/clips/pattern)

For detailed usage examples and advanced features, refer to the official documentation.