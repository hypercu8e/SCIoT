"""Run the shared v2 server with the frozen no-PAD prefix explicitly allowed."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from server.multiclient.run import main
if __name__=='__main__':main()
