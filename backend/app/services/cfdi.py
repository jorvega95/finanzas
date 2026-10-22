"""Read a CFDI (the XML of an invoice) out of an uploaded file. Implements FAC-15.

Accepts the .zip the SAT portal downloads (XML + PDF) or the bare XML. The
input is untrusted: DTDs/entities are refused before parsing (XXE, billion
laughs) and zips are bounded in entries and uncompressed size (zip bombs).
"""

import datetime as dt
import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

MAX_XML_BYTES = 2 * 1024 * 1024
MAX_ZIP_ENTRIES = 50
CFDI_NAMESPACES = ("http://www.sat.gob.mx/cfd/4", "http://www.sat.gob.mx/cfd/3")
TFD_NAMESPACE = "http://www.sat.gob.mx/TimbreFiscalDigital"


@dataclass
class CfdiData:
    uuid: str | None
    issue_date: dt.date | None
    total: Decimal | None
    currency: str | None
    fx_rate: Decimal | None
    issuer_rfc: str | None
    receiver_rfc: str | None
    receiver_name: str | None
    iva_rates: list[Decimal] = field(default_factory=list)  # TasaOCuota of IVA transfers


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _xml_candidates(content: bytes) -> list[bytes]:
    if not content.startswith(b"PK\x03\x04"):
        return [content]
    out: list[bytes] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                return []
            for info in infos:
                if not info.filename.lower().endswith(".xml") or info.file_size > MAX_XML_BYTES:
                    continue
                with archive.open(info) as fh:
                    data = fh.read(MAX_XML_BYTES + 1)  # never trust file_size alone
                if len(data) <= MAX_XML_BYTES:
                    out.append(data)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError):
        return []
    return out


def _parse_one(content: bytes) -> CfdiData | None:
    if len(content) > MAX_XML_BYTES:
        return None
    # No DTDs at all: without them there are no entities, so neither XXE nor
    # entity expansion can happen (stdlib expat, no defusedxml dependency).
    # NUL bytes mean UTF-16/32, where the byte search below would be blind.
    upper = content.upper()
    if b"\x00" in content or b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return None
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    ns = next((n for n in CFDI_NAMESPACES if root.tag == f"{{{n}}}Comprobante"), None)
    if ns is None:
        return None
    issuer = root.find(f"{{{ns}}}Emisor")
    receiver = root.find(f"{{{ns}}}Receptor")
    stamp = root.find(f".//{{{TFD_NAMESPACE}}}TimbreFiscalDigital")
    fecha = root.get("Fecha") or ""
    try:
        issue_date: dt.date | None = dt.date.fromisoformat(fecha[:10])
    except ValueError:
        issue_date = None
    iva_rates = [
        rate
        for t in root.iter(f"{{{ns}}}Traslado")
        if t.get("Impuesto") == "002" and (rate := _decimal(t.get("TasaOCuota"))) is not None
    ]
    uuid = stamp.get("UUID") if stamp is not None else None
    return CfdiData(
        uuid=uuid.upper() if uuid else None,
        issue_date=issue_date,
        total=_decimal(root.get("Total")),
        currency=root.get("Moneda"),
        fx_rate=_decimal(root.get("TipoCambio")),
        issuer_rfc=issuer.get("Rfc") if issuer is not None else None,
        receiver_rfc=receiver.get("Rfc") if receiver is not None else None,
        receiver_name=receiver.get("Nombre") if receiver is not None else None,
        iva_rates=iva_rates,
    )


def read_cfdi(content: bytes) -> CfdiData | None:
    """FAC-15: the first CFDI found in the file, or None."""
    for candidate in _xml_candidates(content):
        data = _parse_one(candidate)
        if data is not None:
            return data
    return None
