from fastmcp import FastMCP
from textblob import TextBlob
from textblob.classifiers import NaiveBayesClassifier
from textblob.exceptions import NotTranslated
from textblob.sentiments import PatternAnalyzer

mcp = FastMCP("textblob_service")

@mcp.tool(name="analyze_sentiment", description="Analyze the sentiment of a given text.")
def analyze_sentiment(text: str) -> dict:
    """
    Analyze the sentiment of the provided text.

    Parameters:
        text (str): The text to analyze.

    Returns:
        dict: A dictionary containing the polarity and subjectivity of the text.
    """
    try:
        blob = TextBlob(text)
        sentiment = blob.sentiment
        return {"success": True, "result": {"polarity": sentiment.polarity, "subjectivity": sentiment.subjectivity}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="classify_text", description="Classify text using a Naive Bayes Classifier.")
def classify_text(text: str, training_data: list) -> dict:
    """
    Classify the given text based on training data.

    Parameters:
        text (str): The text to classify.
        training_data (list): A list of tuples containing training data in the format (text, label).

    Returns:
        dict: A dictionary containing the classification label.
    """
    try:
        classifier = NaiveBayesClassifier(training_data)
        label = classifier.classify(text)
        return {"success": True, "result": {"label": label}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="tokenize_text", description="Tokenize the given text into words.")
def tokenize_text(text: str) -> dict:
    """
    Tokenize the provided text into words.

    Parameters:
        text (str): The text to tokenize.

    Returns:
        dict: A dictionary containing the list of tokens.
    """
    try:
        blob = TextBlob(text)
        tokens = blob.words
        return {"success": True, "result": {"tokens": list(tokens)}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="extract_noun_phrases", description="Extract noun phrases from the given text.")
def extract_noun_phrases(text: str) -> dict:
    """
    Extract noun phrases from the provided text.

    Parameters:
        text (str): The text to process.

    Returns:
        dict: A dictionary containing the list of noun phrases.
    """
    try:
        blob = TextBlob(text)
        noun_phrases = blob.noun_phrases
        return {"success": True, "result": {"noun_phrases": list(noun_phrases)}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="translate_text", description="Translate text to a specified language.")
def translate_text(text: str, to_language: str) -> dict:
    """
    Translate the given text to the specified language.

    Parameters:
        text (str): The text to translate.
        to_language (str): The target language code (e.g., 'es' for Spanish).

    Returns:
        dict: A dictionary containing the translated text.
    """
    try:
        blob = TextBlob(text)
        translated = blob.translate(to=to_language)
        return {"success": True, "result": {"translated_text": str(translated)}, "error": None}
    except NotTranslated:
        return {"success": False, "result": None, "error": "Translation not performed."}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="correct_spelling", description="Correct the spelling of the given text.")
def correct_spelling(text: str) -> dict:
    """
    Correct the spelling of the provided text.

    Parameters:
        text (str): The text to correct.

    Returns:
        dict: A dictionary containing the corrected text.
    """
    try:
        blob = TextBlob(text)
        corrected = blob.correct()
        return {"success": True, "result": {"corrected_text": str(corrected)}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="detect_language", description="Detect the language of the given text.")
def detect_language(text: str) -> dict:
    """
    Detect the language of the provided text.

    Parameters:
        text (str): The text to analyze.

    Returns:
        dict: A dictionary containing the detected language code.
    """
    try:
        blob = TextBlob(text)
        language = blob.detect_language()
        return {"success": True, "result": {"language": language}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

def create_app() -> FastMCP:
    """
    Create and return the FastMCP application instance.

    Returns:
        FastMCP: The FastMCP application instance.
    """
    return mcp