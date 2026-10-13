@echo off
pip install -r requirements.txt
python assets\make_icon.py
python -m PyInstaller --onefile --windowed --name TableConverter --icon assets\icon.ico --add-data "assets\logo.png;assets" --collect-all pdfminer --collect-all pdfplumber --clean app.py
echo Exe: dist\TableConverter.exe
