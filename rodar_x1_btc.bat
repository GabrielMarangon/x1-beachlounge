@echo off
set PYTHON_EXE=C:\Users\W10\AppData\Local\Programs\Python\Python311\python.exe
set APP_DIR=c:\meu_chatbot_flask - Copia\templates\x1_btc
start "X1_BTC Server" cmd /k "cd /d "%APP_DIR%" && "%PYTHON_EXE%" app.py"
