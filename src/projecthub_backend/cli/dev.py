import sys
from fastapi_cli.cli import main

def run_dev():
    sys.argv = ["fastapi", "dev", "src/projecthub_backend/main.py"]
    main()
