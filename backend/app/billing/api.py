from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.auth.dependencies import account, require
from app.auth.roles import Role
from app.billing.contracts import SettlementRequest
from app.billing.models import Settlement
from app.billing.service import describe, get_settlement, post_settlement
from app.database import Session
from app.delivery.report import export_table


router = APIRouter(tags=['Settlements'])
reviewer = require(Role.reviewer)


@router.post('/settlements', status_code=201)
def post(payload: SettlementRequest, response: Response, user=Depends(reviewer)):
    settlement, created = post_settlement(payload.base_run_id, payload.revision_run_id, user.email)
    response.status_code = 201 if created else 200
    return describe(settlement)


@router.get('/settlements')
def history(user=Depends(account),
            base_run_id: Annotated[int | None, Query(ge=1)] = None):
    with Session() as db:
        query = select(Settlement).order_by(Settlement.id.desc())
        if base_run_id is not None:
            query = query.where(Settlement.base_run_id == base_run_id)
        return [describe(settlement) for settlement in db.scalars(query)]


@router.get('/settlements/{settlement_id}')
def detail(settlement_id: int, user=Depends(account)):
    with Session() as db:
        return describe(get_settlement(db, settlement_id))


@router.get('/settlements/{settlement_id}/csv')
def settlement_csv(settlement_id: int,
                   table: Annotated[str, Query(min_length=1, max_length=120)], user=Depends(account)):
    with Session() as db:
        report = get_settlement(db, settlement_id).report
    content = export_table({'result': report['result']}, table)
    return Response(content, media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="settlement-{settlement_id}.csv"'})
