from fastmcp import FastMCP
from textblob import TextBlob
from textblob.classifiers import NaiveBayesClassifier
from textblob.exceptions import NotTranslated
from textblob.wordnet import Synset

mcp = FastMCP("textblob_service")

@mcp.tool(name="analyze_sentiment", description="Analyze the sentiment of a given text.")
def analyze_sentiment(text: str) -> dict:
    """
    Analyze the sentiment of the provided text.

    Parameters:
        text (str): The input text to analyze.

    Returns:
        dict: A dictionary containing success status and sentiment analysis result or error message.
    """
    try:
        blob = TextBlob(text)
        sentiment = blob.sentiment
        return {"success": True, "result": {"polarity": sentiment.polarity, "subjectivity": sentiment.subjectivity}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="tokenize_text", description="Tokenize the given text into words.")
def tokenize_text(text: str) -> dict:
    """
    Tokenize the provided text into words.

    Parameters:
        text (str): The input text to tokenize.

    Returns:
        dict: A dictionary containing success status and tokenized words or error message.
    """
    try:
        blob = TextBlob(text)
        tokens = blob.words
        return {"success": True, "result": list(tokens), "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="detect_language", description="Detect the language of the given text.")
def detect_language(text: str) -> dict:
    """
    Detect the language of the provided text.

    Parameters:
        text (str): The input text to detect the language.

    Returns:
        dict: A dictionary containing success status and detected language or error message.
    """
    try:
        blob = TextBlob(text)
        language = blob.detect_language()
        return {"success": True, "result": {"language": language}, "error": None}
    except NotTranslated as e:
        return {"success": False, "result": None, "error": "Text could not be translated or detected."}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="translate_text", description="Translate the given text to a target language.")
def translate_text(text: str, target_language: str) -> dict:
    """
    Translate the provided text to the specified target language.

    Parameters:
        text (str): The input text to translate.
        target_language (str): The target language code (e.g., 'es' for Spanish).

    Returns:
        dict: A dictionary containing success status and translated text or error message.
    """
    try:
        blob = TextBlob(text)
        translated_text = str(blob.translate(to=target_language))
        return {"success": True, "result": {"translated_text": translated_text}, "error": None}
    except NotTranslated as e:
        return {"success": False, "result": None, "error": "Translation not available for the given text."}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="extract_noun_phrases", description="Extract noun phrases from the given text.")
def extract_noun_phrases(text: str) -> dict:
    """
    Extract noun phrases from the provided text.

    Parameters:
        text (str): The input text to extract noun phrases from.

    Returns:
        dict: A dictionary containing success status and extracted noun phrases or error message.
    """
    try:
        blob = TextBlob(text)
        noun_phrases = blob.noun_phrases
        return {"success": True, "result": list(noun_phrases), "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="classify_text", description="Classify the given text using a Naive Bayes Classifier.")
def classify_text(text: str, training_data: list) -> dict:
    """
    Classify the provided text using a Naive Bayes Classifier.

    Parameters:
        text (str): The input text to classify.
        training_data (list): A list of tuples containing training data in the format [(text, label), ...].

    Returns:
        dict: A dictionary containing success status and classification result or error message.
    """
    try:
        classifier = NaiveBayesClassifier(training_data)
        classification = classifier.classify(text)
        return {"success": True, "result": {"classification": classification}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="get_word_synonyms", description="Get synonyms for a given word.")
def get_word_synonyms(word: str) -> dict:
    """
    Get synonyms for the provided word using WordNet.

    Parameters:
        word (str): The input word to find synonyms for.

    Returns:
        dict: A dictionary containing success status and a list of synonyms or error message.
    """
    try:
        synonyms = []
        for synset in Synset(word).lemmas():
            synonyms.append(synset.name())
        return {"success": True, "result": {"synonyms": list(set(synonyms))}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

def create_app() -> FastMCP:
    """
    Create and return the FastMCP application instance.

    Returns:
        FastMCP: The initialized FastMCP application.
    """
    return mcp