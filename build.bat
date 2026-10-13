@echo off
pip install -r requirements.txt
python -m PyInstaller --onefile --windowed --name TableConverter --collect-all pdfminer --collect-all pdfplumber --clean app.py
echo Exe: dist\TableConverter.exe
