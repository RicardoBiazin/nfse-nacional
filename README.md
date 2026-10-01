# NFS-e Nacional

Aplicativo desktop (Windows) para **emitir** e **consultar** a NFS-e do Padrão Nacional,
direto nas APIs do governo, sem provedor intermediário:

- **Sefin Nacional**: emissão síncrona (DPS → NFS-e), consulta por chave e por Id da DPS,
  cancelamento (evento 101101), parâmetros municipais.
- **ADN (Ambiente de Dados Nacional)**: distribuição por NSU das notas **emitidas e recebidas**,
  eventos e DANFSe em PDF.

Leiaute **DPS 1.01** (XSD de 09/02/2026, com o grupo IBS/CBS opcional). Começa em
**Produção Restrita**; produção só por escolha explícita no cadastro da empresa.

## Instalação (desenvolvimento)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python main.py            # interface
.\.venv\Scripts\python -m pytest -q       # testes (sem rede)
```

Executável: `.\.venv\Scripts\pyinstaller --noconfirm nfse_nacional.spec` gera
`dist\NFSE_Nacional\NFSE_Nacional.exe`.

## Uso

1. **Nova empresa → Importar certificado A1 (.pfx)**. O CNPJ vem do certificado (OID ICP-Brasil
   2.16.76.1.3.3). O .pfx é copiado para `%LOCALAPPDATA%\NFSE_Nacional\certificados` com ACL só do
   usuário e a senha vai para o Cofre de Credenciais do Windows (keyring), nunca para o banco.
2. Preencha município (IBGE), regime (Simples/MEI/não optante), código de tributação nacional
   padrão, série e, se já emitia por outro sistema, o próximo número da DPS.
3. **Emitir NFS-e**: o app valida as regras do Anexo I que dá para checar localmente, valida no
   XSD oficial, assina (XMLDSig RSA-SHA1, C14N) e envia. "Validar e salvar XML" faz tudo menos enviar.
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

- Teste ponta a ponta em Produção Restrita com um A1 real (os testes automáticos usam
  certificado autoassinado e API simulada; o servidor recusa certificado fora da ICP-Brasil).
- Substituição de NFS-e pela interface (o modelo `DPS.ch_substituida` já existe).
- (feito na 0.1.2) Campos JSON do ADN confirmados com o servidor real.

## Referências

- Documentação técnica: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
- Swagger (Produção Restrita, exige certificado): https://adn.producaorestrita.nfse.gov.br/contribuintes/docs/index.html
