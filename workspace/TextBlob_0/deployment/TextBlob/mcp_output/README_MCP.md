# TextBlob MCP (Model Context Protocol) Service README

## Project Introduction

TextBlob is a Python library designed for processing textual data. It provides a simple and intuitive API for performing common natural language processing (NLP) tasks such as tokenization, sentiment analysis, classification, and parsing. Built on top of robust libraries like NLTK and Pattern, TextBlob simplifies complex NLP operations, making them accessible to developers without requiring deep expertise in computational linguistics.

## Installation Method

To install TextBlob, ensure you have Python 3.9 or higher. The library depends on `nltk`, `numpy`, `requests`, and `six`. Optionally, you can use `pattern` for enhanced functionality.

Install TextBlob using pip:

```
pip install textblob
```

To download NLTK corpora required for certain operations, run:

```
python -m textblob.download_corpora
```

## Quick Start

Here is a quick example of how to use TextBlob for basic NLP tasks:

1. **Create a TextBlob instance**:
   ```
   from textblob import TextBlob
   blob = TextBlob("TextBlob makes NLP simple and intuitive.")
   ```

2. **Perform tokenization**:
   ```
   words = blob.words
   sentences = blob.sentences
   ```

3. **Analyze sentiment**:
   ```
   sentiment = blob.sentiment
   print(f"Polarity: {sentiment.polarity}, Subjectivity: {sentiment.subjectivity}")
   ```

4. **Classify text** (requires training a classifier):
   ```
   from textblob.classifiers import NaiveBayesClassifier
   train_data = [("I love this library!", "pos"), ("I hate bugs.", "neg")]
   classifier = NaiveBayesClassifier(train_data)
   print(classifier.classify("This is amazing!"))
   ```

## Available Tools and Endpoints List

TextBlob MCP provides the following services:

1. **TextBlob Class**: Core class for text processing, offering methods for tokenization, sentiment analysis, noun phrase extraction, and more.
2. **Blobber Service**: Factory for creating TextBlob instances with consistent configurations.
3. **Tokenizers**:
   - `WordTokenizer`: Splits text into words.
   - `SentenceTokenizer`: Splits text into sentences.
4. **Sentiment Analysis Services**:
   - `PatternAnalyzer`: Uses Pattern library for sentiment analysis.
   - `NaiveBayesAnalyzer`: Performs sentiment analysis using a Naive Bayes model.
5. **Classification Services**:
   - `NaiveBayesClassifier`: Text classification using Naive Bayes.
   - `DecisionTreeClassifier`: Text classification using Decision Tree algorithms.
6. **Parsing Service**:
   - `PatternParser`: Creates syntax trees for sentences.
7. **Utility Services**:
   - `lowerstrip`: Strips and converts text to lowercase.
   - `strip_punctuation`: Removes punctuation from text.

## Common Issues and Notes

1. **Dependencies**: Ensure `nltk` and `numpy` are installed. For additional functionality, install the `pattern` library.
2. **Environment**: TextBlob supports Python versions 3.9 to 3.13.
3. **Performance**: While TextBlob is optimized for general use cases, performance may vary depending on the size of the text and the complexity of operations.
4. **Translation**: Translation functionality has been removed. Use the official Google Translate API for translation tasks.
5. **Customization**: TextBlob allows users to inject custom services for tokenization, sentiment analysis, classification, and more.

## Reference Links or Documentation

- [TextBlob GitHub Repository](https://github.com/sloria/TextBlob)
- [Official Documentation](https://textblob.readthedocs.io/)
- [NLTK Documentation](http://nltk.org/)
- [Pattern Library](https://github.com/clips/pattern)

For further details, refer to the [DeepWiki TextBlob Documentation](https://deepwiki.com/sloria/TextBlob).