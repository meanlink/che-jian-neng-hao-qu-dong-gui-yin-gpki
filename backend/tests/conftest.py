import os
import tempfile

# Must be set before any src import: config builds the engine at import time.
_TMP = tempfile.mkdtemp(prefix='energy-ridge-tests-')
os.environ['DATABASE_URL'] = f'sqlite:///{_TMP}/test.db'
os.environ['ARTIFACT_DIR'] = f'{_TMP}/artifacts'
os.environ['JWT_SECRET'] = 'test-secret'
os.environ['SEED_DEMO'] = 'false'
