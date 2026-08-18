import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Import statements
from src.dateutil.relativedelta import relativedelta
from src.dateutil.rrule import rrule, rruleset
from src.dateutil.easter import easter
from src.dateutil.zoneinfo import get_zonefile_instance, ZoneInfoFile

class Adapter:
    """
    Adapter class for MCP plugin to integrate and utilize the functionalities of the dateutil library.
    """

    def __init__(self):
        """
        Initialize the Adapter class with default mode set to 'import'.
        """
        self.mode = "import"

    # -------------------------------------------------------------------------
    # Instance Methods for Classes
    # -------------------------------------------------------------------------

    def create_relativedelta_instance(self, **kwargs):
        """
        Create an instance of the relativedelta class.

        Parameters:
            kwargs: Keyword arguments for relativedelta initialization.

        Returns:
            dict: A dictionary containing the status and the instance or error message.
        """
        try:
            instance = relativedelta(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create relativedelta instance: {str(e)}"}

    def create_rrule_instance(self, **kwargs):
        """
        Create an instance of the rrule class.

        Parameters:
            kwargs: Keyword arguments for rrule initialization.

        Returns:
            dict: A dictionary containing the status and the instance or error message.
        """
        try:
            instance = rrule(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create rrule instance: {str(e)}"}

    def create_rruleset_instance(self):
        """
        Create an instance of the rruleset class.

        Returns:
            dict: A dictionary containing the status and the instance or error message.
        """
        try:
            instance = rruleset()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create rruleset instance: {str(e)}"}

    def create_zoneinfofile_instance(self):
        """
        Create an instance of the ZoneInfoFile class.

        Returns:
            dict: A dictionary containing the status and the instance or error message.
        """
        try:
            instance = ZoneInfoFile()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create ZoneInfoFile instance: {str(e)}"}

    # -------------------------------------------------------------------------
    # Call Methods for Functions
    # -------------------------------------------------------------------------

    def call_easter(self, year):
        """
        Call the easter function to calculate the date of Easter Sunday for a given year.

        Parameters:
            year (int): The year for which to calculate Easter Sunday.

        Returns:
            dict: A dictionary containing the status and the result or error message.
        """
        try:
            result = easter(year)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to calculate Easter date: {str(e)}"}

    def call_get_zonefile_instance(self):
        """
        Call the get_zonefile_instance function to retrieve the timezone database instance.

        Returns:
            dict: A dictionary containing the status and the result or error message.
        """
        try:
            result = get_zonefile_instance()
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to retrieve timezone database instance: {str(e)}"}

    # -------------------------------------------------------------------------
    # Error Handling and Fallback
    # -------------------------------------------------------------------------

    def handle_import_failure(self):
        """
        Handle import failure gracefully by switching to fallback mode.

        Returns:
            dict: A dictionary containing the status and fallback message.
        """
        self.mode = "fallback"
        return {"status": "error", "message": "Import mode failed. Switching to fallback mode."}

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_mode(self):
        """
        Retrieve the current mode of the adapter.

        Returns:
            dict: A dictionary containing the status and the current mode.
        """
        return {"status": "success", "mode": self.mode}

    def reset_mode(self):
        """
        Reset the mode of the adapter to 'import'.

        Returns:
            dict: A dictionary containing the status and the updated mode.
        """
        self.mode = "import"
        return {"status": "success", "mode": self.mode}