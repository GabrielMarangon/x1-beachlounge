$python = "C:\Users\W10\AppData\Local\Programs\Python\Python311\python.exe"
$workdir = "c:\meu_chatbot_flask - Copia\templates\x1_btc"
$logOut = Join-Path $workdir "server_stdout.log"
$logErr = Join-Path $workdir "server_stderr.log"

# Se já estiver ativo, não reinicia.
$listenPid = (
  netstat -ano |
  Select-String ':5004' |
  Select-String 'LISTENING' |
  ForEach-Object { ($_ -split '\s+')[-1] } |
  Select-Object -First 1
)
if ($listenPid) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5004/health -TimeoutSec 3
    if ($r.StatusCode -eq 200) {
      Write-Output "X1_BTC já estava ativo em http://127.0.0.1:5004 | health=$($r.StatusCode)"
      exit 0
    }
  } catch {
    Stop-Process -Id $listenPid -Force
    Start-Sleep -Milliseconds 500
  }
}

# Inicia em segundo plano e grava logs para diagnóstico.
$env:PYTHONUTF8 = "1"
Start-Process -FilePath $python -ArgumentList "app.py" -WorkingDirectory $workdir -RedirectStandardOutput $logOut -RedirectStandardError $logErr

# Aguarda subida por até 12s
for ($i = 0; $i -lt 12; $i++) {
  Start-Sleep -Seconds 1
  try {
    $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5004/health -TimeoutSec 2
    if ($r.StatusCode -eq 200) {
      Write-Output "X1_BTC ativo em http://127.0.0.1:5004 | health=$($r.StatusCode)"
      exit 0
    }
  } catch {
    # continua tentando
  }
}

Write-Output "Falha ao iniciar X1_BTC. Verifique logs em:"
Write-Output $logOut
Write-Output $logErr
exit 1
