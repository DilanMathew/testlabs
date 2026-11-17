"""
Start Bethesda Labs from the source code (developer / Mac / Linux use).
The Windows installer runs the same thing as BethesdaLabs.exe.

    python run.py                 opens the app window, icon in the system tray
    python run.py --lan           also reachable from other PCs on the same network
    python run.py --port 8080     use a different port
    python run.py --no-tray       keep running in this terminal (Ctrl+C to stop)
"""
from bethesda.launcher import main

if __name__ == "__main__":
    main()
