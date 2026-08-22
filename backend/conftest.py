"""Make `config`, `engine`, etc. importable as top-level modules when running
pytest from anywhere.  DealBench uses flat absolute imports (e.g.
`from config import SETTINGS`) with the backend dir as the import root."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
