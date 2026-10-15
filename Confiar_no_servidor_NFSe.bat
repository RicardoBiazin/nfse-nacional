@echo off
setlocal EnableExtensions
chcp 65001 >nul <nul
title NFS-e Nacional - Confiar no servidor

rem ---------------------------------------------------------------------------
rem  Rode em cada PC que vai acessar a versão web (não precisa de administrador).
rem  Baixa a autoridade certificadora PÚBLICA do servidor e a instala em
rem  "Autoridades de Certificação Raiz Confiáveis" do usuário: o navegador passa a
rem  abrir https://SERVIDOR:8443 com cadeado, sem "Sua conexão não é particular".
rem  Uso: Confiar_no_servidor_NFSe.bat [NOME-DO-SERVIDOR] [PORTA]
rem ---------------------------------------------------------------------------

set "SERVIDOR=%~1"
set "PORTA=%~2"
if "%PORTA%"=="" set "PORTA=8443"
if "%SERVIDOR%"=="" (
    set /p "SERVIDOR=Nome ou IP do servidor (ex.: DESKTOP-FS65BNN): "
)
if "%SERVIDOR%"=="" exit /b 1

set "ARQ=%TEMP%\NFSe_Nacional_AC.crt"
del "%ARQ%" >nul 2>&1
echo Baixando a autoridade certificadora de https://%SERVIDOR%:%PORTA%/ca.crt ...
curl.exe -sSk --ssl-no-revoke -m 15 -o "%ARQ%" "https://%SERVIDOR%:%PORTA%/ca.crt" <nul
if errorlevel 1 goto falhou
findstr /c:"BEGIN CERTIFICATE" "%ARQ%" >nul || goto falhou

echo.
echo Confira a impressão digital com a mostrada no servidor (NFSE_Servidor.bat, opção 5):
certutil -hashfile "%ARQ%" SHA256 <nul | findstr /v /c:"CertUtil" /c:"SHA256"
echo.
echo O Windows vai pedir confirmação para instalar o certificado: clique em Sim.
certutil -user -addstore Root "%ARQ%" <nul
if errorlevel 1 goto falhou
del "%ARQ%" >nul 2>&1
echo.
echo Pronto. Feche e abra o navegador e acesse https://%SERVIDOR%:%PORTA%/
echo (Firefox: Configurações, Privacidade, Certificados, "Confiar em autoridades raiz do Windows".)
pause
exit /b 0

:falhou
echo.
echo Não consegui baixar/instalar. Confira se o servidor está ligado, o nome/IP e a porta,
echo e se o firewall do servidor libera a porta %PORTA% (NFSE_Servidor.bat, opção 3).
pause
exit /b 1
