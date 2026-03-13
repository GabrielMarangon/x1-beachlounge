@echo off
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5004 ^| findstr LISTENING') do taskkill /PID %%a /F
echo Servidor na porta 5004 finalizado.
