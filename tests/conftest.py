"""Pytest configuration and environment initialization."""

from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root before tests run
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
