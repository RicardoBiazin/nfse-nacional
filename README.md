# NFS-e Nacional

Aplicativo desktop (Windows) para **emitir** e **consultar** a NFS-e do Padrão Nacional,
direto nas APIs do governo, sem provedor intermediário:

- **Sefin Nacional**: emissão síncrona (DPS → NFS-e), consulta por chave e por Id da DPS,
  cancelamento (evento 101101), parâmetros municipais.
- **ADN (Ambiente de Dados Nacional)**: distribuição por NSU das notas **emitidas e recebidas**
  e eventos.
- **DANFSe** gerado no próprio app, conforme a NT 008/2026 (a API do governo foi suspensa).

Leiaute **DPS 1.01** (XSD de 09/02/2026, com o grupo IBS/CBS opcional). Começa em
**Produção Restrita**; produção só por escolha explícita no cadastro da empresa.

| | |
|---|---|
| **Download (Windows)** | [Releases](https://github.com/RicardoBiazin/nfse-nacional/releases/latest): `NFSE_Nacional.exe` (desktop), `NFSE_Servidor.exe` + `.bat` (versão para a rede) |
| **No navegador** | <https://nfse.biazin.com.br> — DANFSe a partir do XML e consulta de códigos, sem enviar arquivo a ninguém |
| **Licença** | [AGPL-3.0](LICENSE) |

> **Certificado digital:** nunca fica no repositório nem no executável. O `.gitignore` bloqueia
> `*.pfx`, `*.p12`, `*.pem`, `*.key` e o banco local. No desktop o `.pfx` fica em
> `%LOCALAPPDATA%\NFSE_Nacional` com a senha no Cofre de Credenciais do Windows; no servidor, em
> `C:\ProgramData\NFSE_Nacional` com a senha cifrada por DPAPI. Os testes usam certificado
> autoassinado gerado na hora e dados fictícios.

## Versão para navegador (`web/`)

Site estático (Vite + jsPDF) publicado no Netlify, com **portão anti-robô** próprio (prova de
trabalho + cookie assinado numa Edge Function, sem serviço de terceiros; o mesmo do EditPDFree):

- **DANFSe do XML:** solte XMLs de NFS-e (ou um .zip); inclua o XML do evento de cancelamento
  para sair com a marca "CANCELADA"/"SUBSTITUÍDA". Mesmo layout do app (porte de `danfse.py`).
- **Consultar códigos:** lista de serviços nacional, NBS 2.0 e municípios IBGE.
- **Nada sai do navegador:** sem banco, sem upload; CSP `connect-src 'self'` (mais o Cloudflare Web Analytics, sem cookie).

Emitir nota exige o certificado A1 e mTLS com a Sefin, por isso só existe no programa instalado.

Só a página de apresentação <https://nfse.biazin.com.br/sobre/> (`web/public/sobre/`) e o
`sitemap.xml` ficam abertos a robôs e indexáveis; o resto passa pelo portão e leva `noindex`.
Arquivo novo em `public/sobre/` precisa entrar na lista `PUBLICAS` de `portao.ts`.

```powershell
cd web
npm install
npm test                      # DANFSe (JS) + portão
npm run build                 # gera public/dados a partir de ../recursos e o dist/
npm run portao:local          # serve dist/ atrás do portão, em http://localhost:4181
netlify deploy --build --prod # publica (variável PORTAO_SEGREDO já definida no site)
```

Depois que o CNAME `nfse` → `nfse-nacional.netlify.app` existir no DNS, definir
`REDIRECIONAR_DOMINIO=1` no Netlify para o endereço antigo redirecionar ao oficial.

## Instalação (desenvolvimento)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python main.py            # interface
.\.venv\Scripts\python -m pytest -q       # testes (sem rede)
```

Executáveis:

- **Arquivo único (para distribuir / rodar de Google Drive ou rede):**
  `.\.venv\Scripts\pyinstaller --noconfirm --distpath dist_unico nfse_nacional_unico.spec`
  gera `dist_unico\NFSE_Nacional.exe` (~64 MB). Ele extrai o Python para a pasta temporária
  local antes de abrir; por isso funciona de `G:\Drives compartilhados\...`.
- **Pasta (desenvolvimento, abre mais rápido):** `.\.venv\Scripts\pyinstaller --noconfirm nfse_nacional.spec`
  gera `dist\NFSE_Nacional\`. **Não copie essa pasta para o Google Drive**: o Windows não consegue
  carregar as DLLs do drive virtual e dá "Failed to load Python DLL ... python313.dll".

Cada PC tem o próprio banco (`%LOCALAPPDATA%\NFSE_Nacional`) e o próprio cofre de senhas:
em outro computador é preciso importar o certificado de novo e sincronizar o ADN.

## Uso

1. **Nova empresa → aba Certificados → Adicionar certificado (.pfx)**. Pode haver vários (renovação, filial com o mesmo CNPJ raiz); o principal é usado e, se vencer, o app passa para o válido. O CNPJ vem do certificado (OID ICP-Brasil
   2.16.76.1.3.3). O .pfx é copiado para `%LOCALAPPDATA%\NFSE_Nacional\certificados` com ACL só do
   usuário e a senha vai para o Cofre de Credenciais do Windows (keyring), nunca para o banco.
2. Preencha município (IBGE), regime (Simples/MEI/não optante), código de tributação nacional
   padrão, série e, se já emitia por outro sistema, o próximo número da DPS.
3. **Emitir NFS-e**: o app valida as regras do Anexo I que dá para checar localmente, valida no
   XSD oficial, assina (XMLDSig RSA-SHA1, C14N) e envia. "Validar e salvar XML" faz tudo menos enviar.
   No tomador, digite o **CNPJ** (dados da Receita) ou o **CEP** (endereço) e o app preenche o
   resto. **Enviar por e-mail ao tomador** manda DANFSe e XML depois de autorizada (configure o
   SMTP em *Configurar empresa > E-mail*; Gmail e Yahoo exigem senha de app).
4. **Notas → Sincronizar ADN** baixa tudo a partir do último NSU (emitidas pelo portal também e as
   recebidas de fornecedores). Daí saem DANFSe, cancelamento, planilha .xlsx e XMLs.

### Linha de comando

```powershell
python -m nfse_nacional empresa-importar --pfx C:\cert\empresa.pfx --senha ****
python -m nfse_nacional empresa-config 11222333000181 c_mun=4115200 op_simp_nac=3 reg_ap_trib_sn=1 c_trib_nac=010701 p_tot_sn=6
python -m nfse_nacional simular 11222333000181 nota.json --saida dps.xml   # não envia
python -m nfse_nacional emitir 11222333000181 nota.json
python -m nfse_nacional sincronizar 11222333000181
python -m nfse_nacional notas 11222333000181 --inicio 2026-10-01
python -m nfse_nacional cancelar 11222333000181 12 --motivo 1 --justificativa "Valor digitado errado"
python -m nfse_nacional danfse 11222333000181 12
python -m nfse_nacional exportar 11222333000181 --inicio 2026-10-01 --fim 2026-10-31 --xlsx out.xlsx --xml-pasta xmls
```

O formato do `nota.json` está no topo de [nfse_nacional/cli.py](nfse_nacional/cli.py).

## Emissão idempotente

A nota é gravada como `pendente` (com a DPS assinada) **antes** do envio. Se a conexão cair ou a
Sefin responder 5xx, o app consulta `GET /dps/{id}`; achando a NFS-e, baixa e marca `autorizada`,
senão marca `indefinida`. **Reconsultar** resolve depois e só reenvia a mesma DPS (mesmo número)
se a Sefin confirmar que ela não existe. Número de DPS reservado nunca é reutilizado.

## Detalhes técnicos que custaram descobrir

- **C14N do lxml em subelemento está quebrada** quando há namespace padrão redeclarado
  (`<Signature xmlns=ds>` dentro de `<DPS xmlns=nfse>`): sai `xmlns=""` espúrio e a assinatura
  não bate com a da Sefin. O assinador reserializa o elemento antes da C14N; os testes conferem
  com o libxmlsec1 (`xmlsec`), que tem C14N própria.
- **XSD oficial usa `^...$` em `xs:pattern`** (ex.: `TSSerieDPS`). No libxml2 esses são
  caracteres literais e nada valida; o carregador remove as âncoras ao montar o schema.
- `pAliq`: as RNs E0600–E0640 dependem do regime, da retenção e do **convênio do município**.
  `regras.aliquota_exigida()` decide; marque o convênio no cadastro (ou "Consultar").
- `totTrib`: não optante usa `pTotTrib`, MEI `indTotTrib=0`, ME/EPP `pTotTribSN` (E0710–E0713).
- Com `tpEmit=1` o nome do prestador **não** pode ir na DPS (E0121).

## Pendências

- Emissão em produção real ainda não feita pelo app (Produção Restrita testada com A1 real).
- Substituição de NFS-e pela interface (o modelo `DPS.ch_substituida` já existe).
- (feito na 0.1.2) Campos JSON do ADN confirmados com o servidor real.

## Referências

- Documentação técnica: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
- Swagger (Produção Restrita, exige certificado): https://adn.producaorestrita.nfse.gov.br/contribuintes/docs/index.html

## Versão web (uso interno na rede)

Um PC/servidor da rede roda `NFSE_Servidor.exe`; os demais acessam pelo navegador.

**Atalho:** `NFSE_Servidor.bat` (ao lado do `.exe`) tem um menu com todas as operações abaixo —
iniciar, abrir no navegador, instalar/remover o serviço (pede administrador sozinho), situação,
importar dados do desktop, criar administrador e ver o log.

1. Copie `dist_unico\NFSE_Servidor.exe` para o servidor (ex.: `C:\NFSE\`).
2. Opcional — trazer os dados do desktop **deste mesmo usuário/PC**:
   `NFSE_Servidor.exe importar-dados-desktop` (banco, certificados e senhas → cofre do servidor).
3. Em um terminal **como administrador**: `NFSE_Servidor.exe instalar-servico` (inicia com o
   Windows, libera a porta 8443 no firewall).
4. Faça cada PC confiar no HTTPS do servidor (uma vez): no servidor, `NFSE_Servidor.bat` opção 9;
   nos outros PCs, `Confiar_no_servidor_NFSe.bat NOME-DO-SERVIDOR` (sem administrador). Sem isso o
   Chrome/Edge mostram "Sua conexão não é particular".
   Abra `https://NOME-DO-SERVIDOR:8443`; na primeira vez cria-se o administrador.
5. Em **Empresa** envie o certificado A1 (se não importou do desktop); em **Usuários** crie as contas.

Papéis: *consulta* (ver e baixar), *emissor* (emitir/duplicar/importar), *admin* (cancelar, empresa,
certificados, usuários, auditoria). Variáveis: `NFSE_SYNC_HORAS` (sincronização automática,
padrão 4), `NFSE_BACKUP_DESTINO` (pasta extra de backup, ex. no Google Drive),
`NFSE_NACIONAL_DADOS` (pasta de dados). Remover: `NFSE_Servidor.exe remover-servico`.
Senha de administrador esquecida: `NFSE_Servidor.exe criar-admin LOGIN` (no servidor, como admin).
