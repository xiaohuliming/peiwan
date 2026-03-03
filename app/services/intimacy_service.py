from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models.intimacy import Intimacy
from app.services.log_service import log_operation


def update_intimacy(boss_id, player_id, amount):
    """
    增加/减少亲密度 (基于消费金额, 1嗯呢币 = 1亲密度)
    """
    amount = Decimal(str(amount))
    record = Intimacy.query.filter_by(boss_id=boss_id, player_id=player_id).first()
    if record:
        record.value += amount
        if record.value < 0:
            record.value = Decimal('0')
    else:
        if amount > 0:
            record = Intimacy(boss_id=boss_id, player_id=player_id, value=amount)
            db.session.add(record)
    return record


def clear_intimacy(before_date, operator_id=None):
    """
    清空指定日期之前的亲密度数据 (管理员操作)
    """
    count = Intimacy.query.filter(Intimacy.updated_at < before_date).delete()
    if operator_id:
        log_operation(
            operator_id=operator_id,
            action_type='intimacy_clear',
            target_type='intimacy',
            target_id=0,
            detail=f'清空 {before_date.strftime("%Y-%m-%d")} 之前的亲密度, 共 {count} 条'
        )
    return count
