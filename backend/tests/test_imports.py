"""Fase 6 tests: IMP-01..IMP-07."""

import uuid

from freezegun import freeze_time

from tests.conftest import bootstrap_space

CSV_CONTENT = (
    "Fecha,Concepto,Cargo\n"
    "01/06/2026,OXXO CENTRO,-150.50\n"
    "02/06/2026,NOMINA QUINCENA,8000.00\n"
    "03/06/2026,UBER VIAJE,-89.90\n"
)

MAPPING = {
    "date_column": "Fecha",
    "amount_column": "Cargo",
    "description_column": "Concepto",
    "date_format": "%d/%m/%Y",
    "decimal_separator": ".",
    "negative_is_expense": True,
    "currency": "MXN",
}


async def preview(client, ctx, content=CSV_CONTENT, mapping=None, expected=200):
    res = await client.post(
        "/api/v1/imports/preview",
        headers=ctx["headers"],
        json={"content": content, "mapping": mapping or MAPPING},
    )
    assert res.status_code == expected, res.text
    return res.json() if expected == 200 else None


async def confirm(client, ctx, rows, expected=201, **overrides):
    res = await client.post(
        "/api/v1/imports/confirm",
        headers=ctx["headers"],
        json={
            "file_name": "estado.csv",
            "source": "bbva",
            "mapping": MAPPING,
            "rows": rows,
            "payment_method_id": ctx["methods"]["Débito"]["id"],
            **overrides,
        },
    )
    assert res.status_code == expected, res.text
    return res.json() if expected == 201 else None


@freeze_time("2026-06-20 18:00:00")
async def test_imp01_preview_inserts_nothing_then_confirm(client):
    """IMP-01: nada se inserta antes de confirmar; tipos por signo."""
    ctx = await bootstrap_space(client)
    body = await preview(client, ctx)
    assert body["total"] == 3
    assert body["invalid"] == 0
    types = [r["type"] for r in body["rows"]]
    assert types == ["expense", "income", "expense"]
    assert body["rows"][0]["amount"] == "150.50"  # valor absoluto
    assert body["rows"][0]["date"] == "2026-06-01"  # %d/%m/%Y parseado

    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    assert res.json()["total"] == 0  # preview no persistió

    await confirm(client, ctx, body["rows"])
    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    assert res.json()["total"] == 3
    # IMP-03: sin categoría inferible ⇒ bandeja de revisión.
    res = await client.get("/api/v1/transactions?needs_review=true", headers=ctx["headers"])
    assert res.json()["total"] == 3


@freeze_time("2026-06-20 18:00:00")
async def test_imp02_duplicates_marked_and_deselected(client):
    ctx = await bootstrap_space(client)
    body = await preview(client, ctx)
    await confirm(client, ctx, body["rows"])

    # Re-importar el mismo archivo: todas chocan contra existentes.
    body = await preview(client, ctx)
    assert body["duplicates"] == 3
    assert all(r["is_duplicate"] and not r["selected"] for r in body["rows"])

    # El usuario decide: fuerza una e importa solo esa (IMP-02).
    body["rows"][0]["selected"] = True
    await confirm(client, ctx, body["rows"])
    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    assert res.json()["total"] == 4


@freeze_time("2026-06-20 18:00:00")
async def test_imp03_uncategorized_is_hidden_from_forms(client, db_session):
    from sqlalchemy import select

    from app.models.catalogs import Category

    ctx = await bootstrap_space(client)
    body = await preview(client, ctx)
    await confirm(client, ctx, body["rows"])

    # La seed oculta existe pero no aparece en el catálogo de captura.
    cats_api = (await client.get("/api/v1/catalogs/categories", headers=ctx["headers"])).json()
    assert all(c["name"] != "Sin categoría" for c in cats_api)
    hidden = await db_session.scalar(
        select(Category).where(
            Category.space_id == uuid.UUID(ctx["space_id"]),
            Category.is_system.is_(True),
        )
    )
    assert hidden is not None and hidden.name == "Sin categoría"


@freeze_time("2026-06-20 18:00:00")
async def test_imp04_rollback_excludes_manual_edits(client):
    ctx = await bootstrap_space(client)
    body = await preview(client, ctx)
    batch = await confirm(client, ctx, body["rows"])

    # Editar una a mano: el rollback la conserva y lo informa (IMP-04).
    txns = (await client.get("/api/v1/transactions", headers=ctx["headers"])).json()["items"]
    edited = txns[0]
    res = await client.put(
        f"/api/v1/transactions/{edited['id']}",
        headers=ctx["headers"],
        json={
            "type": edited["type"],
            "date": edited["date"],
            "amount": edited["amount"],
            "currency": edited["currency"],
            "description": "Editada a mano",
            "category_id": ctx["categories"]["Comida"]["id"]
            if edited["type"] == "expense"
            else ctx["categories"]["Nómina"]["id"],
            "payment_method_id": ctx["methods"]["Débito"]["id"],
        },
    )
    assert res.status_code == 200

    res = await client.post(f"/api/v1/imports/{batch['id']}/rollback", headers=ctx["headers"])
    assert res.json() == {"removed": 2, "kept_edited": 1}
    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    assert res.json()["total"] == 1

    # Doble rollback ⇒ 409.
    res = await client.post(f"/api/v1/imports/{batch['id']}/rollback", headers=ctx["headers"])
    assert res.status_code == 409

    batches = (await client.get("/api/v1/imports", headers=ctx["headers"])).json()
    assert batches[0]["status"] == "partially_rolled_back"


@freeze_time("2026-06-20 18:00:00")
async def test_imp06_validations(client):
    ctx = await bootstrap_space(client)

    # Columna inexistente ⇒ 422.
    await preview(client, ctx, mapping={**MAPPING, "amount_column": "NoExiste"}, expected=422)
    # Separador decimal coma + filas inválidas reportadas por fila.
    content = 'Fecha,Concepto,Cargo\n01/06/2026,CAFE,"-1.234,56"\nbasura,X,9\n'
    body = await preview(
        client, ctx, content=content, mapping={**MAPPING, "decimal_separator": ","}
    )
    assert body["rows"][0]["amount"] == "1234.56"
    assert body["invalid"] == 1
    assert body["rows"][1]["error"] is not None

    # Más de 5,000 filas ⇒ 422 (IMP-06).
    big = "Fecha,Concepto,Cargo\n" + "\n".join(f"01/06/2026,FILA {i},-1.00" for i in range(5001))
    await preview(client, ctx, content=big, expected=422)


@freeze_time("2026-06-20 18:00:00")
async def test_imp07_export_csv_and_json(client):
    ctx = await bootstrap_space(client)
    body = await preview(client, ctx)
    await confirm(client, ctx, body["rows"])

    res = await client.get("/api/v1/exports/transactions.csv", headers=ctx["headers"])
    assert res.status_code == 200
    lines = res.text.strip().splitlines()
    assert lines[0].startswith("date,type,amount")
    assert len(lines) == 4  # header + 3
    assert "OXXO CENTRO" in res.text

    res = await client.get("/api/v1/exports/full.json", headers=ctx["headers"])
    assert res.status_code == 200
    data = res.json()
    assert len(data["transactions"]) == 3
    assert {"space", "categories", "payment_methods"} <= set(data.keys())

    # Viewer puede exportar (lectura), no importar.
    # (cobertura ESP-03 del wizard)
    from app.models.spaces import SpaceMember, SpaceRole  # noqa: F401


@freeze_time("2026-06-20 18:00:00")
async def test_imp05_card_charges_get_cycle_assigned(client):
    """IMP-05: cargos importados a un método TDC se asignan a su ciclo."""
    from tests.test_cards import create_card

    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    body = await preview(client, ctx)
    rows = [r for r in body["rows"] if r["type"] == "expense"]
    await confirm(client, ctx, rows, payment_method_id=card["payment_method_id"])

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    # 150.50 + 89.90 cargados al ciclo abierto (corte 15-jun ya pasó? hoy 20-jun:
    # compras del 1-3 jun van al corte 15-jun, aún sin cerrar ⇒ saldo al corte 0
    # hasta cerrar; el total de deuda refleja ambos cargos.
    assert detail["debt"]["total_debt"] == "240.40"
