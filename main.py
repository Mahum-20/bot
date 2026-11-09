import sys
import webbrowser
import uvicorn
import logging

if __name__ == "__main__":
    logging.info("Starting TopG HTF Structure & Level Python Visualizer...")
    url = "http://127.0.0.1:8000"
    print("\n" + "="*70)
    print(f"  Chart Dashboard is starting! Opening browser at: {url}")
    print("="*70 + "\n")
    
    # Open browser automatically after a short delay
    webbrowser.open(url)
    
    # Start FastAPI / Uvicorn server
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
