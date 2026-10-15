@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul <nul
title NFS-e Nacional - Servidor web

rem ---------------------------------------------------------------------------
rem  Menu do servidor web interno da NFS-e Nacional.
rem  Uso: NFSE_Servidor.bat            (menu)
rem       NFSE_Servidor.bat 1..8        (executa a opção direto)
rem  Funciona ao lado do NFSE_Servidor.exe ou na pasta do código (usa .venv).
rem  Porta: variável NFSE_PORTA (padrão 8443).
rem ---------------------------------------------------------------------------

set "AQUI=%~dp0"
if "%NFSE_PORTA%"=="" (set "PORTA=8443") else (set "PORTA=%NFSE_PORTA%")
set "TAREFA=NFSE_Nacional Servidor"
if "%NFSE_NACIONAL_DADOS%"=="" (set "DADOS=%ProgramData%\NFSE_Nacional") else (set "DADOS=%NFSE_NACIONAL_DADOS%")

if exist "%AQUI%NFSE_Servidor.exe" (
    set "SERVIDOR="%AQUI%NFSE_Servidor.exe""
) else if exist "%AQUI%dist_unico\NFSE_Servidor.exe" (
    set "SERVIDOR="%AQUI%dist_unico\NFSE_Servidor.exe""
) else if exist "%AQUI%.venv\Scripts\python.exe" (
    set "SERVIDOR="%AQUI%.venv\Scripts\python.exe" "%AQUI%servidor.py""
) else (
    echo Não encontrei o NFSE_Servidor.exe nesta pasta: %AQUI%
    pause <nul
    exit /b 1
)

set "OPCAO=%~1"
if not "%OPCAO%"=="" goto executar

:menu
cls
echo ============================================================
echo   NFS-e Nacional - Servidor web interno        porta %PORTA%
echo ============================================================
echo   1  Iniciar o servidor nesta janela (teste; fecha com a janela)
echo   2  Abrir no navegador
echo   3  Instalar como serviço (inicia com o Windows)   [admin]
echo   4  Remover o serviço                              [admin]
echo   5  Situação (serviço e servidor respondendo)
echo   6  Importar dados do app desktop deste usuário
echo   7  Criar ou redefinir administrador               [admin]
echo   8  Ver o final do log
echo   9  Confiar no certificado HTTPS neste PC (tira o aviso do navegador)
echo   0  Sair
echo ------------------------------------------------------------
set "OPCAO="
set /p "OPCAO=Escolha: "
if "%OPCAO%"=="" exit /b 0

:executar
if "%OPCAO%"=="1" goto iniciar
if "%OPCAO%"=="2" goto navegador
if "%OPCAO%"=="3" goto instalar
if "%OPCAO%"=="4" goto remover
if "%OPCAO%"=="5" goto situacao
if "%OPCAO%"=="6" goto importar
if "%OPCAO%"=="7" goto admin
if "%OPCAO%"=="8" goto log
if "%OPCAO%"=="9" goto confiar
if "%OPCAO%"=="0" exit /b 0
echo Opção inválida: %OPCAO%
goto fim

rem ------------------------------------------------------------------ 1
:iniciar
call :responde
if "!RESPONDE!"=="1" (
    echo O servidor já está respondendo na porta %PORTA% ^(provavelmente o serviço^).
    echo Use a opção 2 para abrir no navegador.
    goto fim
)
echo Iniciando em https://%COMPUTERNAME%:%PORTA%  ^(Ctrl+C para parar^)
echo O navegador abre sozinho em alguns segundos. Se aparecer "Sua conexão não é particular",
echo use a opção 9 neste PC (e o Confiar_no_servidor_NFSe.bat nos outros PCs).
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'https://%COMPUTERNAME%:%PORTA%/'"
%SERVIDOR% rodar --porta %PORTA%
goto fim

rem ------------------------------------------------------------------ 2
:navegador
start "" "https://%COMPUTERNAME%:%PORTA%/"
echo Abrindo https://%COMPUTERNAME%:%PORTA%/
echo Na primeira vez o navegador avisa que o certificado é autoassinado: aceite.
goto fim

rem ------------------------------------------------------------------ 3
:instalar
call :exige_admin 3 || goto fim
%SERVIDOR% instalar-servico --porta %PORTA%
goto fim

rem ------------------------------------------------------------------ 4
:remover
call :exige_admin 4 || goto fim
%SERVIDOR% remover-servico
goto fim

rem ------------------------------------------------------------------ 5
:situacao
schtasks /Query /TN "%TAREFA%" >nul 2>&1
if errorlevel 1 (
    echo Serviço: NÃO instalado.
) else (
    for /f "tokens=1,* delims=:" %%a in ('schtasks /Query /TN "%TAREFA%" /FO LIST ^| findstr /b /c:"Status"') do echo Serviço: instalado, status:%%b
)
call :responde
if "!RESPONDE!"=="1" (
    echo Servidor: respondendo em https://%COMPUTERNAME%:%PORTA%/
) else (
    echo Servidor: NÃO está respondendo na porta %PORTA%.
)
echo Dados: %DADOS%
if exist "%DADOS%\https\ca.crt" (
    echo Impressão digital da autoridade do HTTPS ^(compare ao instalar nos outros PCs^):
    certutil -hashfile "%DADOS%\https\ca.crt" SHA256 <nul | findstr /v /c:"CertUtil" /c:"SHA256"
)
goto fim

rem ------------------------------------------------------------------ 6
:importar
echo Copia o banco, os certificados e as senhas do app desktop deste usuário
echo para %DADOS%. Só funciona se o servidor ainda não tiver banco.
%SERVIDOR% importar-dados-desktop
goto fim

rem ------------------------------------------------------------------ 7
:admin
call :exige_admin 7 || goto fim
set "LOGIN="
set /p "LOGIN=Login do administrador: "
if "%LOGIN%"=="" goto fim
%SERVIDOR% criar-admin "%LOGIN%"
goto fim

rem ------------------------------------------------------------------ 8
:log
if not exist "%DADOS%\logs\servidor.log" (
    echo Ainda não há log em %DADOS%\logs\servidor.log
    goto fim
)
powershell -NoProfile -Command "Get-Content -LiteralPath '%DADOS%\logs\servidor.log' -Tail 30 -Encoding UTF8" <nul
goto fim

rem ------------------------------------------------------------------ 9
:confiar
echo Instala a autoridade certificadora do servidor em "Raiz Confiável" deste usuário.
echo O Windows vai pedir confirmação: clique em Sim.
%SERVIDOR% confiar-certificado
if errorlevel 1 (
    echo Não foi possível instalar. Rode a opção 1 ou 3 antes ^(gera o certificado^).
) else (
    echo Pronto. Feche e abra o navegador de novo. No Firefox: Configurações, Privacidade,
    echo Certificados, "Confiar em autoridades raiz do Windows" ^(ou importe o ca.crt^).
)
goto fim

rem ------------------------------------------------------------------ rotinas
:responde
rem RESPONDE=1 se https://127.0.0.1:PORTA/login responde (127.0.0.1: localhost tenta IPv6 antes)
set "RESPONDE=0"
for /f %%c in ('curl.exe -sk -o nul -m 4 -w "%%{http_code}" "https://127.0.0.1:%PORTA%/login" 2^>nul ^<nul') do (
    if not "%%c"=="000" set "RESPONDE=1"
)
exit /b 0

:exige_admin
net session >nul 2>&1
if not errorlevel 1 exit /b 0
echo Esta opção precisa de administrador. Abrindo uma janela elevada...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs" <nul
exit /b 1

:fim
echo.
pause
rem Opção passada por argumento (ou janela elevada): executa uma vez e encerra.
if "%~1"=="" goto menu
endlocal
exit /b 0
