@echo off
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5005 ^| findstr LISTENING') do taskkill /PID %%a /F
echo Servidor na porta 5005 finalizado.
