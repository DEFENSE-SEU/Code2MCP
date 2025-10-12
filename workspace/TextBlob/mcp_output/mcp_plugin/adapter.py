import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Importing necessary modules and classes
try:
    from src.textblob.blob import TextBlob
    from src.textblob.wordnet import Word
    from src.textblob.classifiers import NaiveBayesClassifier
    from src.textblob.tokenizers import WordTokenizer, SentenceTokenizer
    from src.textblob.sentiments import PatternAnalyzer, NaiveBayesAnalyzer
    from src.textblob.parsers import PatternParser
    from src.textblob.np_extractors import FastNPExtractor
    from src.textblob.decorators import cached_property
    from src.textblob.utils import strip_punc
    from src.textblob.exceptions import TextBlobException
    from src.textblob.download_corpora import download_all
    mode = "import"
except ImportError as e:
    mode = "fallback"
    print(f"Warning: Failed to import TextBlob modules. Fallback mode activated. Error: {e}")

# Adapter class
class Adapter:
    """
    Adapter class for the MCP plugin, providing an interface to the TextBlob library.
    This class handles NLP tasks such as tokenization, sentiment analysis, classification, and more.
    """

    def __init__(self):
        """
        Initialize the Adapter class.
        Sets the mode attribute to indicate the import strategy.
        """
        self.mode = mode

    # -------------------------------------------------------------------------
    # TextBlob Class Methods
    # -------------------------------------------------------------------------

    def create_textblob_instance(self, text):
        """
        Create an instance of the TextBlob class.

        Parameters:
            text (str): The text to process.

        Returns:
            dict: A dictionary containing the status and the TextBlob instance or error message.
        """
        try:
            blob = TextBlob(text)
            return {"status": "success", "data": blob}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create TextBlob instance: {e}"}

    # -------------------------------------------------------------------------
    # Tokenization Methods
    # -------------------------------------------------------------------------

    def tokenize_words(self, text):
        """
        Tokenize the given text into words.

        Parameters:
            text (str): The text to tokenize.

        Returns:
            dict: A dictionary containing the status and the list of words or error message.
        """
        try:
            tokenizer = WordTokenizer()
            tokens = tokenizer.tokenize(text)
            return {"status": "success", "data": tokens}
        except Exception as e:
            return {"status": "error", "message": f"Failed to tokenize words: {e}"}

    def tokenize_sentences(self, text):
        """
        Tokenize the given text into sentences.

        Parameters:
            text (str): The text to tokenize.

        Returns:
            dict: A dictionary containing the status and the list of sentences or error message.
        """
        try:
            tokenizer = SentenceTokenizer()
            tokens = tokenizer.tokenize(text)
            return {"status": "success", "data": tokens}
        except Exception as e:
            return {"status": "error", "message": f"Failed to tokenize sentences: {e}"}

    # -------------------------------------------------------------------------
    # Sentiment Analysis Methods
    # -------------------------------------------------------------------------

    def analyze_sentiment(self, text, analyzer_type="pattern"):
        """
        Analyze the sentiment of the given text.

        Parameters:
            text (str): The text to analyze.
            analyzer_type (str): The type of analyzer to use ("pattern" or "naive_bayes").

        Returns:
            dict: A dictionary containing the status and the sentiment analysis result or error message.
        """
        try:
            if analyzer_type == "pattern":
                analyzer = PatternAnalyzer()
            elif analyzer_type == "naive_bayes":
                analyzer = NaiveBayesAnalyzer()
            else:
                return {"status": "error", "message": "Invalid analyzer type specified."}

            sentiment = analyzer.analyze(text)
            return {"status": "success", "data": sentiment}
        except Exception as e:
            return {"status": "error", "message": f"Failed to analyze sentiment: {e}"}

    # -------------------------------------------------------------------------
    # Classification Methods
    # -------------------------------------------------------------------------

    def train_classifier(self, training_data):
        """
        Train a Naive Bayes classifier with the given training data.

        Parameters:
            training_data (list): A list of tuples containing text and labels.

        Returns:
            dict: A dictionary containing the status and the trained classifier or error message.
        """
        try:
            classifier = NaiveBayesClassifier(training_data)
            return {"status": "success", "data": classifier}
        except Exception as e:
            return {"status": "error", "message": f"Failed to train classifier: {e}"}

    def classify_text(self, classifier, text):
        """
        Classify the given text using the provided classifier.

        Parameters:
            classifier (NaiveBayesClassifier): The trained classifier.
            text (str): The text to classify.

        Returns:
            dict: A dictionary containing the status and the classification result or error message.
        """
        try:
            label = classifier.classify(text)
            return {"status": "success", "data": label}
        except Exception as e:
            return {"status": "error", "message": f"Failed to classify text: {e}"}

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def strip_punctuation(self, text):
        """
        Remove punctuation from the given text.

        Parameters:
            text (str): The text to process.

        Returns:
            dict: A dictionary containing the status and the processed text or error message.
        """
        try:
            stripped_text = strip_punc(text)
            return {"status": "success", "data": stripped_text}
        except Exception as e:
            return {"status": "error", "message": f"Failed to strip punctuation: {e}"}

    def download_corpora(self):
        """
        Download all necessary corpora for TextBlob.

        Returns:
            dict: A dictionary containing the status and a success message or error message.
        """
        try:
            download_all()
            return {"status": "success", "message": "Corpora downloaded successfully."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to download corpora: {e}"}

    # -------------------------------------------------------------------------
    # Error Handling and Fallback
    # -------------------------------------------------------------------------

    def fallback_mode_message(self):
        """
        Provide a message indicating fallback mode is active.

        Returns:
            dict: A dictionary containing the status and a fallback message.
        """
        if self.mode == "fallback":
            return {"status": "warning", "message": "Fallback mode is active. Some features may be unavailable."}
        return {"status": "success", "message": "Import mode is active."}