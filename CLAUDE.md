# NFSE_Nacional

App desktop (PySide6) + CLI para emitir e consultar NFS-e Padrão Nacional direto na Sefin
Nacional e no ADN. Python 3.13, venv em `.venv`.

## Comandos

- Testes: `.\.venv\Scripts\python -m pytest -q` (sem rede; a interface roda offscreen)
- Interface: `.\.venv\Scripts\python main.py`
- Executável: `.\.venv\Scripts\pyinstaller --noconfirm nfse_nacional.spec` e abrir
  `dist\NFSE_Nacional\NFSE_Nacional.exe` para conferir
- Arquivo único para distribuir (Google Drive/rede):
  `.\.venv\Scripts\pyinstaller --noconfirm --distpath dist_unico nfse_nacional_unico.spec`.
  A versão em pasta falha rodando do Google Drive ("Failed to load Python DLL"); gerar as duas a cada versão.

## Mapa

- `dps.py` monta o XML (ordem do XSD 1.01); `assinatura.py` XMLDSig próprio; `validacao.py` XSD
- `cliente_sefin.py` / `cliente_adn.py` HTTP; `cliente_http.py` mTLS e erros
- `servico.py` orquestra (emissão idempotente, cancelamento, sincronização NSU)
- `banco.py` SQLite em `%LOCALAPPDATA%\NFSE_Nacional` (env `NFSE_NACIONAL_DADOS` sobrepõe)
- `regras.py` RNs do Anexo I checadas antes do envio
- `schemas/` XSDs oficiais v1.01 (não editar à mão; as âncoras `^$` são tratadas no carregamento)

## Versão web (`web/`)

- `cd web; npm test; npm run build; netlify deploy --build --prod` (site Netlify `nfse-nacional`,
  domínio nfse.biazin.com.br). `src/danfse.js` é porte de `danfse.py`: mudou um, mude o outro.
- Portão anti-robô copiado do EditPDFree (`src/portao/`, `netlify/edge-functions/portao.ts`).

## Regras do projeto

- Repositório PÚBLICO (AGPL-3.0). Testes e exemplos só com dados fictícios; nada de CNPJ, valor
  ou nome real de cliente (o histórico foi reescrito em 21/10/2026 para tirar isso).
- Versão em `nfse_nacional/__init__.py` (`VERSAO`): incrementar a cada alteração publicada.
- Nunca versionar `.pfx/.p12/.pem`, `.db`, nem `docs_ref/` (material baixado do gov.br).
- Não trocar `_c14n()` de `assinatura.py` por `tostring(el, method="c14n")` direto: o lxml gera
  `xmlns=""` espúrio em subelemento e a Sefin recusa a assinatura. O teste com `xmlsec` pega isso.
- Padrão de ambiente é Produção Restrita; produção exige confirmação explícita na interface.
