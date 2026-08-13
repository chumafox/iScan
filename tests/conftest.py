import json
import pytest
from pathlib import Path

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'sample_device.json').read_text())

class FakeLockdown:
    def __init__(self):
        self._data = FIXTURE
    
    @property
    def all_values(self):
        return self._data['all_values']
    
    def get_value(self, domain=None, key=None):
        if domain == 'com.apple.mobile.battery':
            return self._data['battery']
        return {}

class FakeDiagnosticsService:
    def __init__(self, lockdown):
        self._data = FIXTURE['gestalt']
    
    def mobilegestalt(self, keys):
        return {k: self._data.get(k) for k in keys}

@pytest.fixture
def fake_lockdown():
    return FakeLockdown()

@pytest.fixture
def fake_diag(fake_lockdown):
    return FakeDiagnosticsService(fake_lockdown)
