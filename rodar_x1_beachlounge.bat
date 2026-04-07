@echo off
set PYTHON_EXE=C:\Users\W10\AppData\Local\Programs\Python\Python311\python.exe
set APP_DIR=c:\meu_chatbot_flask - Copia\apps\x1_beachlounge
start "X1 Beach Lounge Server" cmd /k "cd /d "%APP_DIR%" && "%PYTHON_EXE%" app.py"
