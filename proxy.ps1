# Прокси для запросов к OpenAI/Cohere через VPN.
# Запуск в текущем окне:  . .\proxy.ps1
$env:ALL_PROXY   = "socks5://127.0.0.1:10808"
$env:HTTPS_PROXY = "socks5://127.0.0.1:10808"
$env:HTTP_PROXY  = "socks5://127.0.0.1:10808"
$env:NO_PROXY    = "localhost,127.0.0.1,qdrant"
Write-Host "Прокси включён: socks5://127.0.0.1:10808"

# каждый раз в новом окне надо запускать команду
# . .\proxy.ps1