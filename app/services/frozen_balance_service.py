from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from app.extensions import db
from app.models.finance import WithdrawRequest
from app.models.gift import GiftOrder
from app.models.order import Order
from app.models.user import User


ZERO_MONEY = Decimal('0.00')


def quantize_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _normalize_user_id(user_or_id):
    if hasattr(user_or_id, 'id'):
        return int(user_or_id.id)
    return int(user_or_id)


def _empty_breakdown(legacy_total=ZERO_MONEY):
    legacy_cache = quantize_money(legacy_total)
    return {
        'total': ZERO_MONEY,
        'pending_withdraw': ZERO_MONEY,
        'order': ZERO_MONEY,
        'gift': ZERO_MONEY,
        'earning_frozen': ZERO_MONEY,
        'legacy_cache': legacy_cache,
        'legacy_diff': quantize_money(legacy_cache),
        'has_legacy_diff': legacy_cache != ZERO_MONEY,
    }


def get_frozen_balance_map(user_ids, legacy_totals=None):
    ids = []
    seen = set()
    for item in user_ids or []:
        try:
            user_id = _normalize_user_id(item)
        except Exception:
            continue
        if user_id in seen:
            continue
        ids.append(user_id)
        seen.add(user_id)

    if not ids:
        return {}

    legacy_map = {}
    for key, value in (legacy_totals or {}).items():
        try:
            legacy_map[int(key)] = quantize_money(value)
        except Exception:
            continue

    pending_rows = dict(
        db.session.query(
            WithdrawRequest.user_id,
            func.coalesce(func.sum(WithdrawRequest.amount), 0),
        )
        .filter(
            WithdrawRequest.user_id.in_(ids),
            WithdrawRequest.status == 'pending',
        )
        .group_by(WithdrawRequest.user_id)
        .all()
    )

    order_rows = dict(
        db.session.query(
            Order.player_id,
            func.coalesce(func.sum(Order.player_earning), 0),
        )
        .filter(
            Order.player_id.in_(ids),
            Order.status == 'paid',
            Order.freeze_status == 'frozen',
        )
        .group_by(Order.player_id)
        .all()
    )

    gift_rows = dict(
        db.session.query(
            GiftOrder.player_id,
            func.coalesce(func.sum(GiftOrder.player_earning), 0),
        )
        .filter(
            GiftOrder.player_id.in_(ids),
            GiftOrder.status == 'paid',
            GiftOrder.freeze_status == 'frozen',
        )
        .group_by(GiftOrder.player_id)
        .all()
    )

    result = {}
    for user_id in ids:
        pending_withdraw = quantize_money(pending_rows.get(user_id, 0))
        order_frozen = quantize_money(order_rows.get(user_id, 0))
        gift_frozen = quantize_money(gift_rows.get(user_id, 0))
        earning_frozen = quantize_money(order_frozen + gift_frozen)
        realtime_total = quantize_money(pending_withdraw + earning_frozen)
        legacy_cache = quantize_money(legacy_map.get(user_id, 0))
        legacy_diff = quantize_money(legacy_cache - realtime_total)
        result[user_id] = {
            'total': realtime_total,
            'pending_withdraw': pending_withdraw,
            'order': order_frozen,
            'gift': gift_frozen,
            'earning_frozen': earning_frozen,
            'legacy_cache': legacy_cache,
            'legacy_diff': legacy_diff,
            'has_legacy_diff': legacy_diff != ZERO_MONEY,
        }

    return result


def get_user_frozen_breakdown(user_or_id, legacy_total=None):
    user_id = _normalize_user_id(user_or_id)
    if legacy_total is None and hasattr(user_or_id, 'm_bean_frozen'):
        legacy_total = getattr(user_or_id, 'm_bean_frozen', 0)
    frozen_map = get_frozen_balance_map([user_id], legacy_totals={user_id: legacy_total or 0})
    return frozen_map.get(user_id, _empty_breakdown(legacy_total or 0))


def get_users_frozen_breakdown(users):
    legacy_totals = {}
    user_ids = []
    for user in users or []:
        try:
            user_id = _normalize_user_id(user)
        except Exception:
            continue
        user_ids.append(user_id)
        if hasattr(user, 'm_bean_frozen'):
            legacy_totals[user_id] = getattr(user, 'm_bean_frozen', 0)
    return get_frozen_balance_map(user_ids, legacy_totals=legacy_totals)


def get_realtime_total_frozen(user_or_id):
    return get_user_frozen_breakdown(user_or_id)['total']


def adjust_legacy_frozen_cache(user, delta):
    if not user or not hasattr(user, 'm_bean_frozen'):
        return ZERO_MONEY
    current = quantize_money(getattr(user, 'm_bean_frozen', 0))
    updated = quantize_money(current + quantize_money(delta))
    if updated < ZERO_MONEY:
        updated = ZERO_MONEY
    user.m_bean_frozen = updated
    return updated


def _user_display_name(user):
    for candidate in (
        getattr(user, 'player_nickname', None),
        getattr(user, 'nickname', None),
        getattr(user, 'kook_username', None),
        getattr(user, 'username', None),
    ):
        if candidate:
            return str(candidate)
    return f'User#{getattr(user, "id", "-")}'


def build_frozen_reconciliation_rows(user_id=None, only_diff=True, limit=None):
    query = User.query.order_by(User.id.asc())
    if user_id:
        query = query.filter(User.id == int(user_id))
    if limit:
        query = query.limit(max(1, int(limit)))

    users = query.all()
    frozen_map = get_users_frozen_breakdown(users)
    rows = []
    for user in users:
        breakdown = frozen_map.get(user.id, _empty_breakdown(getattr(user, 'm_bean_frozen', 0)))
        changed = breakdown['legacy_cache'] != breakdown['total']
        if only_diff and not changed:
            continue
        rows.append({
            'user_id': user.id,
            'username': user.username,
            'display_name': _user_display_name(user),
            'role': user.role,
            'user_code': getattr(user, 'user_code', '') or '',
            'legacy_cache': breakdown['legacy_cache'],
            'realtime_total': breakdown['total'],
            'legacy_diff': breakdown['legacy_diff'],
            'pending_withdraw': breakdown['pending_withdraw'],
            'order': breakdown['order'],
            'gift': breakdown['gift'],
            'changed': changed,
        })
    return rows


def reconcile_frozen_balance_cache(rows, operator_id=None, log_fn=None):
    updated_rows = []
    for row in rows or []:
        if not row.get('changed'):
            continue
        user = db.session.get(User, int(row['user_id']))
        if not user:
            continue

        before = quantize_money(getattr(user, 'm_bean_frozen', 0))
        after = quantize_money(row['realtime_total'])
        if before == after:
            continue

        user.m_bean_frozen = after
        row_copy = dict(row)
        row_copy['before'] = before
        row_copy['after'] = after
        updated_rows.append(row_copy)

        if log_fn:
            log_fn(
                operator_id,
                'frozen_balance_reconcile',
                'user',
                user.id,
                (
                    f'冻结缓存对账: legacy={before}, realtime={after}, '
                    f'diff={row_copy["legacy_diff"]}, '
                    f'提现={row_copy["pending_withdraw"]}, 订单={row_copy["order"]}, 礼物={row_copy["gift"]}'
                ),
            )

    return updated_rows
