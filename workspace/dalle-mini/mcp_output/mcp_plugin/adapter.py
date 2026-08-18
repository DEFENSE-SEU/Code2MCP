import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Import statements
from src.dalle_mini.model.configuration import Configuration
from src.dalle_mini.model.modeling import Modeling
from src.dalle_mini.model.processor import Processor
from src.dalle_mini.model.tokenizer import Tokenizer
from src.dalle_mini.model.utils import Utils
from tools.train.train import Train
from tools.inference.inference_pipeline import InferencePipeline

class Adapter:
    """
    Adapter class for MCP plugin integration with DALL-E Mini repository.
    Provides methods to interact with various modules and functionalities.
    """

    def __init__(self):
        """
        Initializes the Adapter class with default mode and handles import failures gracefully.
        """
        self.mode = "import"
        self.status = {"status": "success", "message": "Adapter initialized successfully."}

    # ----------------------------- Configuration Module -----------------------------

    def create_configuration_instance(self, config_path):
        """
        Creates an instance of the Configuration class.

        Parameters:
            config_path (str): Path to the configuration file.

        Returns:
            dict: Status and instance of Configuration class.
        """
        try:
            instance = Configuration(config_path)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Configuration instance: {str(e)}"}

    # ---------------------------- Modeling Module -----------------------------

    def create_modeling_instance(self, model_path):
        """
        Creates an instance of the Modeling class.

        Parameters:
            model_path (str): Path to the model file.

        Returns:
            dict: Status and instance of Modeling class.
        """
        try:
            instance = Modeling(model_path)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Modeling instance: {str(e)}"}

    # ----------------------------- Processor Module -----------------------------

    def create_processor_instance(self, processor_config):
        """
        Creates an instance of the Processor class.

        Parameters:
            processor_config (dict): Configuration for the processor.

        Returns:
            dict: Status and instance of Processor class.
        """
        try:
            instance = Processor(processor_config)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Processor instance: {str(e)}"}

    # ----------------------------- Tokenizer Module -----------------------------

    def create_tokenizer_instance(self, tokenizer_config):
        """
        Creates an instance of the Tokenizer class.

        Parameters:
            tokenizer_config (dict): Configuration for the tokenizer.

        Returns:
            dict: Status and instance of Tokenizer class.
        """
        try:
            instance = Tokenizer(tokenizer_config)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Tokenizer instance: {str(e)}"}

    # ----------------------------- Utils Module -----------------------------

    def call_utils_function(self, function_name, *args, **kwargs):
        """
        Calls a utility function from the Utils module.

        Parameters:
            function_name (str): Name of the utility function to call.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            dict: Status and result of the function call.
        """
        try:
            function = getattr(Utils, function_name)
            result = function(*args, **kwargs)
            return {"status": "success", "result": result}
        except AttributeError:
            return {"status": "error", "message": f"Utility function '{function_name}' not found."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call utility function '{function_name}': {str(e)}"}

    # ----------------------------- Training Module -----------------------------

    def call_train_function(self, config_path):
        """
        Calls the training function from the Train module.

        Parameters:
            config_path (str): Path to the training configuration file.

        Returns:
            dict: Status and result of the training process.
        """
        try:
            result = Train(config_path)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to execute training function: {str(e)}"}

    # ----------------------------- Inference Module -----------------------------

    def call_inference_function(self, input_data):
        """
        Calls the inference function from the InferencePipeline module.

        Parameters:
            input_data (dict): Input data for inference.

        Returns:
            dict: Status and result of the inference process.
        """
        try:
            result = InferencePipeline(input_data)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to execute inference function: {str(e)}"}

    # ----------------------------- Error Handling -----------------------------

    def handle_import_failure(self, module_name):
        """
        Handles import failure cases gracefully.

        Parameters:
            module_name (str): Name of the module that failed to import.

        Returns:
            dict: Status and fallback message.
        """
        return {"status": "error", "message": f"Failed to import module '{module_name}'. Please ensure the module is available and correctly configured."}