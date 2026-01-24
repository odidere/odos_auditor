import os

import yaml

# Define the absolute path to config.yaml
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "../../config.yaml")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"❌ Critical Error: Config file not found at {CONFIG_PATH}")

    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# Global Config Object
CONFIG = load_config()
