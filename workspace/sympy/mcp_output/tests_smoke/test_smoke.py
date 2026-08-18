import importlib
import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.getcwd())

source_dir = os.path.join(os.getcwd(), "source")
if os.path.exists(source_dir):
    sys.path.insert(0, source_dir)

try:
    importlib.import_module("sympy")
    print("OK - Successfully imported sympy")
except ImportError as e:
    print(f"Failed to import sympy: {e}")
    fallback_packages = ['sympy']

    for pkg in fallback_packages:
        try:
            importlib.import_module(pkg)
            print(f"OK - Successfully imported {pkg}")
            break
        except ImportError:
            continue
    else:
        print("All import attempts failed")
