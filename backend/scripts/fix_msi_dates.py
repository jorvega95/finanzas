"""One-shot: recalcula estimated_charge_date de cuotas pending con la
lógica nueva (MSI-04: max(purchase_date, period_start)).

Solo toca planes donde TODAS las cuotas están pending (seguro re-ejecutar).
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.cards import Card
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus
from app.models.transactions import Transaction
from app.services.cards import spec_for
from app.services.msi import installment_charge_dates


async def main() -> None:
    async with SessionLocal() as session:
        plans = (
            (
                await session.execute(
                    select(InstallmentPlan).options(
                        selectinload(InstallmentPlan.installments)
                    )
                )
            )
            .scalars()
            .unique()
            .all()
        )

        fixed = 0
        for plan in plans:
            installments: list[Installment] = sorted(
                plan.installments, key=lambda i: i.number
            )
            if not installments:
                continue
            if any(i.status != InstallmentStatus.pending for i in installments):
                print(f"Plan {plan.id}: tiene cuotas no-pending, omitiendo.")
                continue

            txn = await session.get(Transaction, plan.transaction_id)
            card = await session.get(Card, plan.credit_card_id)
            if txn is None or card is None:
                print(f"Plan {plan.id}: transacción o tarjeta no encontrada, omitiendo.")
                continue

            new_dates = installment_charge_dates(txn.date, spec_for(card), plan.months)

            print(f"\nPlan {plan.id} - {txn.description} ({txn.date}, {plan.months}m):")
            for inst, new_date in zip(installments, new_dates, strict=True):
                old = inst.estimated_charge_date
                inst.estimated_charge_date = new_date
                print(f"  Cuota {inst.number}: {old} -> {new_date}")

            fixed += 1

        if fixed:
            await session.commit()
            print(f"\nOK: {fixed} plan(es) actualizados.")
        else:
            print("\nNo hay planes que actualizar.")


asyncio.run(main())
