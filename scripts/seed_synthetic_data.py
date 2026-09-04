import os
import sys

backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, backend_dir)

from scripts.seed_synthetic_data import main

if __name__ == "__main__":
    main()
