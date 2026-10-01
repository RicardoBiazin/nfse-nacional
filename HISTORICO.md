# Histórico

## 0.1.0 — 01/10/2026

Primeira versão.

- DPS leiaute 1.01 (XSD 09/02/2026) com tomador, intermediário, serviço, ISSQN, tributos
  federais, totais aproximados por regime e grupo IBS/CBS opcional.
- Assinatura XMLDSig (RSA-SHA1 padrão, SHA-256 opcional) conferida com libxmlsec1 nos testes.
- Sefin Nacional: emitir, consultar NFS-e, chave por Id da DPS, cancelamento, parâmetros municipais.
- ADN: distribuição por NSU (emitidas e recebidas), eventos, DANFSe.
- Emissão idempotente (pendente → autorizada/rejeitada/indefinida + reconsulta).
- Certificado A1 com senha no Cofre do Windows; mTLS sem chave em claro no disco.
- Interface PySide6 (empresas, emissão, notas) e CLI; exportação .xlsx e XML.
- 43 testes automáticos (API simulada, certificado autoassinado).

Não testado ainda contra o servidor real: precisa de um certificado A1 ICP-Brasil.

## 0.1.1 — 01/10/2026

- Regra E0010: aplicativo próprio só pode usar série 1–49999. A série 70000 que aparece nas
  notas do portal é a do Emissor Web; o app usa a própria série (padrão 1) e numeração própria.
- Dica da faixa de série no cadastro da empresa.

## 0.1.2 — 01/10/2026

- Aba Notas: seletor de ambiente para consulta (padrão **Produção**, onde estão as notas reais),
  separado do ambiente de emissão da empresa. Antes a sincronização rodava na Produção Restrita
  (vazia) e o resultado sumia da barra de status: parecia que "nada acontecia".
- Sincronização mostra o resultado em caixa de mensagem e avisa quando o ambiente de testes está vazio.
- Botão Buscar; período padrão desde 1º de janeiro.
- Confirmação extra para cancelar nota de produção.
- Validado contra o ADN real: mTLS com A1 ICP-Brasil, campos JSON (`LoteDFe`, `NSU`,
  `ChaveAcesso`, `TipoDocumento`, `TipoEvento`, `ArquivoXml`) e leitura de 28 documentos
  (NFS-e emitidas, recebidas e eventos de cancelamento/substituição). O ADN não manda
  `UltimoNSU`/`MaiorNSU`; o fim é o 404 com E2220.

## 0.2.0 — 01/10/2026

- **DANFSe gerado localmente** (novo `danfse.py`, reportlab + segno) no layout da NT SE/CGNFS-e
  008/2026: página única A4, Arial/Microsoft Sans Serif, QR Code da Consulta Pública,
  blocos suprimidos conforme notas 2–4, faixa "NFS-e SEM VALIDADE JURÍDICA" em homologação,
  marca d'água CANCELADA/SUBSTITUÍDA. A API `/danfse` do ADN foi suspensa pela própria NT
  (responde 503 em todos os hosts) — era o erro do botão DANFSe (PDF).
- Tabela IBGE de municípios (Anexo A) e logo oficial da NFS-e em `recursos/`.
- Ícone próprio do aplicativo (janela, barra de tarefas e .exe) e "Sobre" com o ícone.

## 0.3.0 — 01/10/2026

- Emitir: campo **Buscar tomador** (qualquer parte do nome ou do CPF/CNPJ) que preenche o
  tomador inteiro, e botão **Repetir última nota deste tomador** (serviço, valor, códigos e
  tributação da última nota autorizada).
- Notas: botão **Duplicar nota** — copia uma nota emitida para a aba Emitir com competência de hoje.
- Tomadores das notas emitidas (inclusive pelo portal) entram no cadastro automaticamente,
  na sincronização e ao abrir a empresa.

## 0.4.0 — 01/10/2026

- **Vários certificados por empresa** (nova tabela `certificados`, aba "Certificados" no cadastro):
  adicionar, tornar principal, remover. Aceita o mesmo CNPJ ou o mesmo CNPJ raiz (filial).
  O principal é usado na emissão; se vencer, o app usa sozinho o válido com maior validade.
- Senha no keyring passa a ser por certificado (`CNPJ:serial`); o certificado único das versões
  anteriores é migrado automaticamente na primeira abertura.
- CLI: `empresa-importar` pode ser repetido (`--principal`, `--cnpj` para filial) e novo `certificados`.

## 0.5.0 — 01/10/2026

- Descritivo oficial abaixo dos campos de código (tributação nacional, NBS, local da prestação,
  município do tomador e do cadastro da empresa), inclusive do valor padrão da empresa;
  código inexistente aparece em laranja.
- Esses campos aceitam busca pela descrição ("consultoria", "Belo Horizonte"...) e gravam só o código.
- Tabelas do Anexo B (lista de serviços nacional e NBS 2.0) em `recursos/`; novo `tabelas.py`.

## 0.5.1 — 01/10/2026

- Executável em **arquivo único** (`nfse_nacional_unico.spec` → `dist_unico\NFSE_Nacional.exe`)
  para rodar de Google Drive/pasta de rede. A versão em pasta copiada para o Drive dava
  "Failed to load Python DLL ... python313.dll" (DLL carregada do drive virtual). Testado
  abrindo direto de `G:\Drives compartilhados\...`.

## 0.6.0 — 01/10/2026

- **Importar XML/PDF…** (aba Notas): vários arquivos ou uma pasta inteira (com subpastas), XML,
  PDF de DANFSe e .zip. Do PDF o app lê a chave de acesso e baixa o XML oficial da Sefin
  (testado em produção com a NFS-e nº 17), e busca os eventos no ADN. Notas repetidas são puladas.
- **Exportar XML/PDF…**: das notas selecionadas (Ctrl/Shift + clique, Ctrl+A) ou de todas as
  listadas, escolhendo XML (com eventos), PDF do DANFSe ou os dois. Arquivos `NFSe_<nº>_<chave>`.
- CLI: `importar CNPJ caminhos...` e `exportar --pdf-pasta`.
