#!/bin/bash
# Start the AI Trading Tournament backend
# Dashboard will be at: http://localhost:8000

cd "$(dirname "$0")/backend"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
