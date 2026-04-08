"""Entry point for Agent Debate System."""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.api import app
from src.database import init_db

if __name__ == "__main__":
    import uvicorn
    
    # Initialize database
    init_db()
    
    # Run server
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    
    print(f"Starting Agent Debate System on http://{host}:{port}")
    print(f"API docs available at http://{host}:{port}/docs")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
