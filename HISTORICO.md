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
