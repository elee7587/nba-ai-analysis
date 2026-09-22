import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.storage.db import init_db
init_db()