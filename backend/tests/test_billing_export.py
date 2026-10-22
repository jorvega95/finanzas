"""FAC-15 (CFDI reading) and FAC-16 (yearly export)."""

import csv
import io
import zipfile

import pytest
from freezegun import freeze_time

from app.core.config import settings
from app.services.cfdi import read_cfdi
from tests.test_billing import PDF, payments, upload, usd_income
from tests.test_tax_filings import setup
from tests.test_wallets import post_txn

UUID = "6F1E2C3A-1B2C-4D5E-8F90-A1B2C3D4E5F6"


def cfdi_xml(total="325.00", fecha="2026-10-02T11:20:00", rate="18.0692", iva="0.000000") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Fecha="{fecha}" SubTotal="{total}" Moneda="USD" TipoCambio="{rate}"
  Total="{total}" TipoDeComprobante="I" Exportacion="01" LugarExpedicion="00000">
  <cfdi:Emisor Rfc="AAAA000101AAA" Nombre="PERSONA" RegimenFiscal="626"/>
  <cfdi:Receptor Rfc="XEXX010101000" Nombre="GREENLIGHT TEST INC." UsoCFDI="S01"/>
  <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="81112000" Importe="{total}">
    <cfdi:Impuestos><cfdi:Traslados>
      <cfdi:Traslado Base="{total}" Impuesto="002" TipoFactor="Tasa"
        TasaOCuota="{iva}" Importe="0.00"/>
    </cfdi:Traslados></cfdi:Impuestos>
  </cfdi:Concepto></cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{UUID.lower()}"/>
  </cfdi:Complemento>
</cfdi:Comprobante>""".encode()


def zipped(**files: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "files_dir", str(tmp_path / "files"))


# --- FAC-15: reading --------------------------------------------------------------------------


def test_fac15_reads_cfdi_from_zip_and_xml():
    data = read_cfdi(zipped(**{"factura.pdf": PDF, "factura.xml": cfdi_xml()}))
    assert data is not None
    assert data.uuid == UUID
    assert str(data.total) == "325.00" and data.currency == "USD"
    assert str(data.fx_rate) == "18.0692"
    assert data.issue_date.isoformat() == "2026-10-02"
    assert data.receiver_rfc == "XEXX010101000"
    assert [str(r) for r in data.iva_rates] == ["0.000000"]
    assert read_cfdi(cfdi_xml()) is not None


def test_fac15_refuses_hostile_or_foreign_input():
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE c [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Total="&x;"/>'
    )
    assert read_cfdi(xxe) is None
    assert read_cfdi(cfdi_xml().decode().encode("utf-16")) is None  # blind spot closed
    assert read_cfdi(b"<?xml version='1.0'?><otro/>") is None
    assert read_cfdi(b"PK\x03\x04 not a zip") is None
    too_many = zipped(**{f"f{i}.xml": b"<a/>" for i in range(60)} | {"z.xml": cfdi_xml()})
    assert read_cfdi(too_many) is None


@freeze_time("2026-10-21 12:00:00")
async def test_fac15_check_against_payment(client):
    ctx, _ = await setup(client)
    await post_txn(client, ctx, **usd_income(ctx, day="2026-10-02"))
    [payment] = await payments(client, ctx)
    await client.patch(
        f"/api/v1/billing/payments/{payment['id']}",
        headers=ctx["headers"],
        json={"fiscal_fx_rate": "18.0692"},
    )
    url = f"/api/v1/billing/payments/{payment['id']}/cfdi"

    good = await upload(client, ctx, zipped(**{"f.xml": cfdi_xml(), "f.pdf": PDF}))
    res = await client.get(url, headers=ctx["headers"], params={"file_id": good["id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["uuid"] == UUID and body["total"] == "325.00"
    assert body["warnings"] == []

    bad = await upload(
        client,
        ctx,
        cfdi_xml(total="300.00", fecha="2026-11-03T10:00:00", rate="18.5000", iva="0.160000"),
        "f.xml",
    )
    res = await client.get(url, headers=ctx["headers"], params={"file_id": bad["id"]})
    assert res.json()["warnings"] == ["total", "fx_rate", "issue_month", "iva"]

    pdf = await upload(client, ctx, PDF, "acuse.pdf")
    res = await client.get(url, headers=ctx["headers"], params={"file_id": pdf["id"]})
    assert res.status_code == 422


# --- FAC-16: export ---------------------------------------------------------------------------


@freeze_time("2026-11-05 12:00:00")
async def test_fac16_yearly_export(client):
    ctx, greenlight = await setup(client)
    await post_txn(client, ctx, **usd_income(ctx, day="2026-10-02"))
    [payment] = await payments(client, ctx)
    invoice_file = await upload(client, ctx, zipped(**{"f.xml": cfdi_xml()}))
    await client.put(
        f"/api/v1/billing/payments/{payment['id']}/invoice",
        headers=ctx["headers"],
        json={
            "issue_date": "2026-10-02",
            "total": "325.00",
            "cfdi_uuid": UUID,
            "file_id": invoice_file["id"],
        },
    )
    ack = await upload(client, ctx, PDF, "acuse.pdf")
    await client.post(
        "/api/v1/billing/filings",
        headers=ctx["headers"],
        json={
            "period": "2026-10-01",
            "filed_date": "2026-11-05",
            "amount_due": "59.00",
            "ack_file_id": ack["id"],
        },
    )
    res = await client.get("/api/v1/billing/export?year=2026", headers=ctx["headers"])
    assert res.status_code == 200
    assert res.headers["content-disposition"] == 'attachment; filename="facturacion-2026.zip"'
    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        names = set(archive.namelist())
        assert {
            "cobros.csv",
            "declaraciones.csv",
            "2026-10/factura-2026-10-02.zip",
            "2026-10/acuse-normal-2026-10.pdf",
        } <= names
        assert archive.read("2026-10/acuse-normal-2026-10.pdf") == PDF
        rows = list(csv.DictReader(io.StringIO(archive.read("cobros.csv").decode("utf-8-sig"))))
        assert rows[0]["folio_fiscal"] == UUID
        assert rows[0]["estatus"] == "declared"
        assert rows[0]["cliente"] == "Greenlight"
    # Another year is empty but valid; another space sees nothing.
    res = await client.get("/api/v1/billing/export?year=2025", headers=ctx["headers"])
    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        assert sorted(archive.namelist()) == ["cobros.csv", "declaraciones.csv"]
