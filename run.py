#!/usr/bin/env python3
"""
Entrypoint to run the TrainerCentral backend and chat server.
Usage:
    python3 run.py
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_path = Path(__file__).parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

if __name__ == "__main__":
    import uvicorn
    import os
    from backend.app import app, SCHEDULER_INTERVAL_SECONDS, FRONTEND_DIR, BACKEND_DIR

    port = int(os.environ.get("PORT", 8000))
    print(f"\n=======================================================")
    print(f"🚀 TrainerCentral Server & Scheduler starting...")
    print(f"📡 Web & Chat UI:  http://localhost:{port}")
    print(f"🕒 Hourly Sync:    Running every {SCHEDULER_INTERVAL_SECONDS} seconds")
    print(f"📂 Frontend Dir:   {FRONTEND_DIR}")
    print(f"📂 Backend Dir:    {BACKEND_DIR}")
    print(f"=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
