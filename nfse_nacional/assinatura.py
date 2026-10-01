"""Assinatura XMLDSig enveloped (padrão das notas fiscais brasileiras).

<Signature> entra como irmã do elemento assinado (infDPS / infPedReg), com
C14N inclusivo, transforms enveloped + C14N e RSA. SHA-1 é o padrão do
ecossistema NFS-e; SHA-256 fica disponível por parâmetro.

Implementação própria com lxml + cryptography: o signxml recusa SHA-1.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from .certificado import Certificado
from .config import NS_DS

C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
ALGORITMOS = {
    "sha1": ("http://www.w3.org/2000/09/xmldsig#rsa-sha1",
             "http://www.w3.org/2000/09/xmldsig#sha1", hashes.SHA1),
    "sha256": ("http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
               "http://www.w3.org/2001/04/xmlenc#sha256", hashes.SHA256),
}
_POR_URI_ASSIN = {v[0]: k for k, v in ALGORITMOS.items()}


def _c14n(el: etree._Element) -> bytes:
    """C14N inclusiva do subelemento como documento próprio.

    Não usar tostring(el, method="c14n") direto num subelemento: o libxml2
    (lxml 6 / libxml2 2.11) emite xmlns="" espúrio em netos quando há um
    namespace padrão redeclarado acima (caso de <Signature> dentro de <DPS>),
    e o digest/assinatura deixam de bater com o calculado pela Sefin.
    Reserializar leva junto as declarações de namespace em escopo.
    """
    isolado = etree.fromstring(etree.tostring(el))
    return etree.tostring(isolado, method="c14n", exclusive=False, with_comments=False)


def _ds(pai, nome, **attrs):
    el = etree.SubElement(pai, f"{{{NS_DS}}}{nome}")
    for k, v in attrs.items():
        el.set(k, v)
    return el


def assinar(raiz: etree._Element, tag_assinada: str, cert: Certificado,
            algoritmo: str = "sha1") -> etree._Element:
    """Assina o primeiro elemento `tag_assinada` (nome local) com atributo Id.

    Modifica e devolve `raiz`.
    """
    uri_assin, uri_digest, hash_cls = ALGORITMOS[algoritmo]
    alvo = next((e for e in raiz.iter() if etree.QName(e).localname == tag_assinada), None)
    if alvo is None:
        raise ValueError(f"Elemento {tag_assinada} não encontrado.")
    id_ = alvo.get("Id")
    if not id_:
        raise ValueError(f"{tag_assinada} sem atributo Id.")

    digest = base64.b64encode(
        hashlib.new(algoritmo, _c14n(alvo)).digest()).decode()

    sig = etree.Element(f"{{{NS_DS}}}Signature", nsmap={None: NS_DS})
    si = _ds(sig, "SignedInfo")
    _ds(si, "CanonicalizationMethod", Algorithm=C14N)
    _ds(si, "SignatureMethod", Algorithm=uri_assin)
    ref = _ds(si, "Reference", URI=f"#{id_}")
    tr = _ds(ref, "Transforms")
    _ds(tr, "Transform", Algorithm=ENVELOPED)
    _ds(tr, "Transform", Algorithm=C14N)
    _ds(ref, "DigestMethod", Algorithm=uri_digest)
    _ds(ref, "DigestValue").text = digest

    # A Signature precisa estar na árvore antes da C14N do SignedInfo, para que
    # os namespaces herdados sejam os mesmos que o verificador verá.
    alvo.addnext(sig)
    valor = cert.chave.sign(_c14n(si), padding.PKCS1v15(), hash_cls())
    _ds(sig, "SignatureValue").text = base64.b64encode(valor).decode()
    ki = _ds(sig, "KeyInfo")
    xd = _ds(ki, "X509Data")
    _ds(xd, "X509Certificate").text = cert.cert_base64()
    return raiz


class AssinaturaInvalida(ValueError):
    pass


def verificar(raiz: etree._Element) -> x509.Certificate:
    """Confere digest e assinatura da primeira <Signature>; devolve o certificado.

    Serve para testes e para checar XMLs recebidos (NFS-e, eventos).
    """
    sig = raiz.find(f".//{{{NS_DS}}}Signature")
    if sig is None:
        raise AssinaturaInvalida("XML sem assinatura.")
    si = sig.find(f"{{{NS_DS}}}SignedInfo")
    ref = si.find(f"{{{NS_DS}}}Reference")
    id_ = ref.get("URI", "").lstrip("#")
    alvo = next((e for e in raiz.iter() if e.get("Id") == id_), None)
    if alvo is None:
        raise AssinaturaInvalida(f"Elemento referenciado #{id_} não encontrado.")
    metodo = si.find(f"{{{NS_DS}}}SignatureMethod").get("Algorithm")
    algoritmo = _POR_URI_ASSIN.get(metodo)
    if not algoritmo:
        raise AssinaturaInvalida(f"Algoritmo não suportado: {metodo}")

    # Transform enveloped: se a assinatura estiver dentro do alvo, remove-a de uma cópia.
    copia = alvo
    if any(s is sig for s in alvo.iter(f"{{{NS_DS}}}Signature")):
        copia = etree.fromstring(etree.tostring(alvo))
        for s in copia.iter(f"{{{NS_DS}}}Signature"):
            s.getparent().remove(s)
    digest = base64.b64encode(hashlib.new(algoritmo, _c14n(copia)).digest()).decode()
    if digest != ref.findtext(f"{{{NS_DS}}}DigestValue"):
        raise AssinaturaInvalida("DigestValue não confere: o conteúdo foi alterado.")

    cert = x509.load_der_x509_certificate(base64.b64decode(
        sig.findtext(f".//{{{NS_DS}}}X509Certificate")))
    valor = base64.b64decode(sig.findtext(f"{{{NS_DS}}}SignatureValue"))
    try:
        cert.public_key().verify(valor, _c14n(si), padding.PKCS1v15(),
                                 ALGORITMOS[algoritmo][2]())
    except Exception as erro:
        raise AssinaturaInvalida(f"SignatureValue inválido: {erro}") from None
    return cert
