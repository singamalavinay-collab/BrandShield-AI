import sys
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient

# Ensure backend root directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """Provide a synchronous TestClient for endpoint integration testing."""
    original_bootstrap = settings.BOOTSTRAP_ON_STARTUP
    settings.BOOTSTRAP_ON_STARTUP = False
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        settings.BOOTSTRAP_ON_STARTUP = original_bootstrap
