"""Start the local-only Streamlit demo using this Python environment."""
from pathlib import Path
import subprocess, sys

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    raise SystemExit(subprocess.call([sys.executable,'-m','streamlit','run',str(root/'src/floodroute/ui/app.py'),
        '--server.address=127.0.0.1','--browser.gatherUsageStats=false',*sys.argv[1:]],cwd=root))
