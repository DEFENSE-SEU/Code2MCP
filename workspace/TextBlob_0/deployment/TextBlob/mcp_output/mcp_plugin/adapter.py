import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Importing required modules and classes
from src.textblob.blob import TextBlob
from src.textblob.wordnet import Word
from src.textblob.tokenizers import WordTokenizer, SentenceTokenizer
from src.textblob.parsers import PatternParser
from src.textblob.sentiments import PatternAnalyzer, NaiveBayesAnalyzer
from src.textblob.np_extractors import FastNPExtractor, ConllExtractor
from src.textblob.classifiers import NaiveBayesClassifier
from src.textblob.decorators import requires_nltk_corpus
from src.textblob.download_corpora import download_corpora
from src.textblob.utils import lowerstrip

class Adapter:
    """
    Adapter class for the MCP plugin to integrate with the TextBlob library.
    This class provides methods to interact with the core functionalities of TextBlob.
    """

    def __init__(self):
        """
        Initialize the Adapter class with default settings.
        """
        self.mode = "import"

    # -------------------------------------------------------------------------
    # TextBlob Class Methods
    # -------------------------------------------------------------------------

    def create_textblob_instance(self, text):
        """
        Create an instance of the TextBlob class.

        Args:
            text (str): The text to initialize the TextBlob instance with.

        Returns:
            dict: A dictionary containing the status and the TextBlob instance or error message.
        """
        try:
            blob = TextBlob(text)
            return {"status": "success", "data": blob}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create TextBlob instance: {str(e)}"}

    def analyze_sentiment(self, text):
        """
        Analyze the sentiment of the given text using TextBlob.

        Args:
            text (str): The text to analyze.

        Returns:
            dict: A dictionary containing the status and sentiment analysis result or error message.
        """
        try:
            blob = TextBlob(text)
            sentiment = blob.sentiment
            return {"status": "success", "data": {"polarity": sentiment.polarity, "subjectivity": sentiment.subjectivity}}
        except Exception as e:
            return {"status": "error", "message": f"Failed to analyze sentiment: {str(e)}"}

    def tokenize_text(self, text):
        """
        Tokenize the given text into words and sentences.

        Args:
            text (str): The text to tokenize.

        Returns:
            dict: A dictionary containing the status and tokenized words and sentences or error message.
        """
        try:
            blob = TextBlob(text)
            words = blob.words
            sentences = blob.sentences
            return {"status": "success", "data": {"words": list(words), "sentences": [str(s) for s in sentences]}}
        except Exception as e:
            return {"status": "error", "message": f"Failed to tokenize text: {str(e)}"}

    # -------------------------------------------------------------------------
    # Word Class Methods
    # -------------------------------------------------------------------------

    def create_word_instance(self, word):
        """
        Create an instance of the Word class.

        Args:
            word (str): The word to initialize the Word instance with.

        Returns:
            dict: A dictionary containing the status and the Word instance or error message.
        """
        try:
            word_instance = Word(word)
            return {"status": "success", "data": word_instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Word instance: {str(e)}"}

    def get_word_synonyms(self, word):
        """
        Get synonyms for the given word using WordNet.

        Args:
            word (str): The word to find synonyms for.

        Returns:
            dict: A dictionary containing the status and synonyms or error message.
        """
        try:
            word_instance = Word(word)
            synonyms = word_instance.synsets
            return {"status": "success", "data": [synonym.name() for synonym in synonyms]}
        except Exception as e:
            return {"status": "error", "message": f"Failed to retrieve synonyms: {str(e)}"}

    # -------------------------------------------------------------------------
    # Tokenizer Methods
    # -------------------------------------------------------------------------

    def word_tokenize(self, text):
        """
        Tokenize the given text into words using WordTokenizer.

        Args:
            text (str): The text to tokenize.

        Returns:
            dict: A dictionary containing the status and tokenized words or error message.
        """
        try:
            tokenizer = WordTokenizer()
            tokens = tokenizer.tokenize(text)
            return {"status": "success", "data": tokens}
        except Exception as e:
            return {"status": "error", "message": f"Failed to tokenize words: {str(e)}"}

    def sentence_tokenize(self, text):
        """
        Tokenize the given text into sentences using SentenceTokenizer.

        Args:
            text (str): The text to tokenize.

        Returns:
            dict: A dictionary containing the status and tokenized sentences or error message.
        """
        try:
            tokenizer = SentenceTokenizer()
            sentences = tokenizer.tokenize(text)
            return {"status": "success", "data": sentences}
        except Exception as e:
            return {"status": "error", "message": f"Failed to tokenize sentences: {str(e)}"}

    # -------------------------------------------------------------------------
    # Sentiment Analysis Methods
    # -------------------------------------------------------------------------

    def analyze_sentiment_pattern(self, text):
        """
        Analyze sentiment using the PatternAnalyzer.

        Args:
            text (str): The text to analyze.

        Returns:
            dict: A dictionary containing the status and sentiment analysis result or error message.
        """
        try:
            analyzer = PatternAnalyzer()
            sentiment = analyzer.analyze(text)
            return {"status": "success", "data": {"polarity": sentiment.polarity, "subjectivity": sentiment.subjectivity}}
        except Exception as e:
            return {"status": "error", "message": f"Failed to analyze sentiment using PatternAnalyzer: {str(e)}"}

    def analyze_sentiment_naive_bayes(self, text):
        """
        Analyze sentiment using the NaiveBayesAnalyzer.

        Args:
            text (str): The text to analyze.

        Returns:
            dict: A dictionary containing the status and sentiment analysis result or error message.
        """
        try:
            analyzer = NaiveBayesAnalyzer()
            blob = TextBlob(text, analyzer=analyzer)
            sentiment = blob.sentiment
            return {"status": "success", "data": {"classification": sentiment.classification, "p_pos": sentiment.p_pos, "p_neg": sentiment.p_neg}}
        except Exception as e:
            return {"status": "error", "message": f"Failed to analyze sentiment using NaiveBayesAnalyzer: {str(e)}"}

    # -------------------------------------------------------------------------
    # Noun Phrase Extraction Methods
    # -------------------------------------------------------------------------

    def extract_noun_phrases_fast(self, text):
        """
        Extract noun phrases using FastNPExtractor.

        Args:
            text (str): The text to extract noun phrases from.

        Returns:
            dict: A dictionary containing the status and extracted noun phrases or error message.
        """
        try:
            extractor = FastNPExtractor()
            noun_phrases = extractor.extract(text)
            return {"status": "success", "data": noun_phrases}
        except Exception as e:
            return {"status": "error", "message": f"Failed to extract noun phrases using FastNPExtractor: {str(e)}"}

    def extract_noun_phrases_conll(self, text):
        """
        Extract noun phrases using ConllExtractor.

        Args:
            text (str): The text to extract noun phrases from.

        Returns:
            dict: A dictionary containing the status and extracted noun phrases or error message.
        """
        try:
            extractor = ConllExtractor()
            noun_phrases = extractor.extract(text)
            return {"status": "success", "data": noun_phrases}
        except Exception as e:
            return {"status": "error", "message": f"Failed to extract noun phrases using ConllExtractor: {str(e)}"}

    # -------------------------------------------------------------------------
    # Corpus Download Method
    # -------------------------------------------------------------------------

    def download_corpora(self):
        """
        Download required corpora for TextBlob.

        Returns:
            dict: A dictionary containing the status or error message.
        """
        try:
            download_corpora()
            return {"status": "success", "message": "Corpora downloaded successfully."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to download corpora: {str(e)}"}

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def lower_and_strip(self, text):
        """
        Convert text to lowercase and strip whitespace.

        Args:
            text (str): The text to process.

        Returns:
            dict: A dictionary containing the status and processed text or error message.
        """
        try:
            processed_text = lowerstrip(text)
            return {"status": "success", "data": processed_text}
        except Exception as e:
            return {"status": "error", "message": f"Failed to process text: {str(e)}"}