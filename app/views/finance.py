from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.models.finance import WithdrawRequest, CommissionLog, BalanceLog
from app.models.user import User
from app.extensions import db
from app.utils.permissions import admin_required
from app.utils.time_utils import BJ_TZ
from app.services.log_service import log_operation
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import func, or_, and_
from collections import defaultdict, deque
import re
import os
import uuid
from werkzeug.utils import secure_filename

finance_bp = Blueprint('finance', __name__)


def _safe_redirect_path(raw_path: str, fallback: str):
    """仅允许站内路径，防止开放重定向。"""
    text = (raw_path or '').strip()
    if not text.startswith('/'):
        return fallback
    if text.startswith('//'):
        return fallback
    return text


def _append_query_param(url: str, key: str, value: str):
    if not key:
        return url
    joiner = '&' if '?' in url else '?'
    return f'{url}{joiner}{key}={value}'


def _bj_day_utc_range(day_obj):
    """将北京时间某天映射为 UTC 无时区时间区间 [start, end)。"""
    start_bj = datetime(day_obj.year, day_obj.month, day_obj.day, tzinfo=BJ_TZ)
    end_bj = start_bj + timedelta(days=1)
    start_utc = start_bj.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_bj.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


_RECHARGE_REF_RE = re.compile(r'\[recharge[_-]?ref:(\d+)\]', re.IGNORECASE)
_RECHARGE_CN_REF_RE = re.compile(r'充值(?:流水|记录|单号|ID)?\s*#?\s*(\d+)', re.IGNORECASE)
_REFUND_REASON_KEYWORDS = ('充值退款', '退款充值', '撤销充值', '回退充值', '回滚充值')


def _q_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


def _extract_recharge_ref_id(reason):
    text = str(reason or '')
    m = _RECHARGE_REF_RE.search(text)
    if m:
        return int(m.group(1))
    m = _RECHARGE_CN_REF_RE.search(text)
    if m:
        return int(m.group(1))
    return None


def _is_recharge_refund_reason(reason):
    text = str(reason or '')
    if _extract_recharge_ref_id(text):
        return True
    return any(key in text for key in _REFUND_REASON_KEYWORDS)


def _build_refunded_recharge_ids(all_recharge_rows, refund_rows):
    """返回已退款充值流水 ID 集合（用于统计排除与列表划线显示）。"""
    refunded_ids = set()
    recharge_map = {row.id: row for row in all_recharge_rows}

    buckets = defaultdict(deque)
    for row in sorted(all_recharge_rows, key=lambda r: (r.created_at, r.id)):
        key = (row.user_id, row.operator_id, _q_money(row.amount))
        buckets[key].append((row.id, row.created_at))

    for refund in sorted(refund_rows, key=lambda r: (r.created_at, r.id)):
        refund_amount = _q_money(abs(refund.amount))
        explicit_ref_id = _extract_recharge_ref_id(refund.reason)

        if explicit_ref_id and explicit_ref_id in recharge_map and explicit_ref_id not in refunded_ids:
            recharge_row = recharge_map[explicit_ref_id]
            if _q_money(recharge_row.amount) == refund_amount and refund.created_at >= recharge_row.created_at:
                refunded_ids.add(explicit_ref_id)
                continue

        if not _is_recharge_refund_reason(refund.reason):
            continue

        key = (refund.user_id, refund.operator_id, refund_amount)
        queue = buckets.get(key)
        if not queue:
            continue

        while queue:
            recharge_id, recharge_time = queue[0]
            if recharge_id in refunded_ids:
                queue.popleft()
                continue
            if refund.created_at < recharge_time:
                break
            refunded_ids.add(recharge_id)
            queue.popleft()
            break

    return refunded_ids


def _redirect_after_withdraw_audit(row_id=None):
    fallback = url_for('finance.withdraw_list')
    base_path = _safe_redirect_path(request.form.get('return_page', ''), fallback)

    scroll_raw = (request.form.get('scroll_y') or '').strip()
    try:
        scroll_y = max(0, int(float(scroll_raw)))
    except Exception:
        scroll_y = 0

    target = base_path
    if scroll_y > 0:
        target = _append_query_param(target, '_scroll_y', str(scroll_y))

    try:
        row_int = int(row_id or request.form.get('row_id') or 0)
    except Exception:
        row_int = 0
    if row_int > 0:
        target = f'{target}#wr-{row_int}'

    return redirect(target)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}


def _save_payment_image(file):
    """保存上传图片并返回相对路径。"""
    if not file or file.filename == '':
        return None, None
    if not allowed_file(file.filename):
        return None, '收款码图片格式仅支持 png/jpg/jpeg/gif'

    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'payment_codes')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    file.save(os.path.join(upload_folder, unique_filename))
    return f"uploads/payment_codes/{unique_filename}", None


def _parse_dual_payment_images(payment_method, payment_image):
    raw = str(payment_image or '').strip()
    if not raw:
        return '', ''
    if '|' in raw:
        left, right = raw.split('|', 1)
        return left.strip(), right.strip()
    method = str(payment_method or '').strip().lower()
    if method == 'alipay':
        return '', raw
    return raw, ''


def _parse_dual_payment_accounts(payment_account):
    raw = str(payment_account or '').strip()
    if not raw:
        return '', ''
    if raw.startswith('机器人提现'):
        return '', ''
    wechat_account = ''
    alipay_account = ''
    for part in [p.strip() for p in raw.split('|')]:
        if part.startswith('微信:'):
            wechat_account = part.split(':', 1)[1].strip()
        elif part.startswith('支付宝:'):
            alipay_account = part.split(':', 1)[1].strip()
    if wechat_account or alipay_account:
        return wechat_account, alipay_account
    return raw, ''


def _get_saved_withdraw_payment(user_id):
    """读取用户最近一次可复用的收款信息。"""
    records = (
        WithdrawRequest.query
        .filter(WithdrawRequest.user_id == user_id)
        .order_by(WithdrawRequest.created_at.desc())
        .limit(20)
        .all()
    )
    for wr in records:
        wx_img, ali_img = _parse_dual_payment_images(wr.payment_method, wr.payment_image)
        wx_acc, ali_acc = _parse_dual_payment_accounts(wr.payment_account)
        if wx_img or ali_img or wx_acc or ali_acc:
            return {
                'wechat_image': wx_img,
                'alipay_image': ali_img,
                'wechat_account': wx_acc,
                'alipay_account': ali_acc,
                'has_both_codes': bool(wx_img and ali_img),
            }
    return {
        'wechat_image': '',
        'alipay_image': '',
        'wechat_account': '',
        'alipay_account': '',
        'has_both_codes': False,
    }


def _get_recent_withdrawal_within_3_days(user_id):
    """获取3天内最近一笔提现（不计已拒绝/失败）"""
    window_start = datetime.utcnow() - timedelta(days=3)
    return (
        WithdrawRequest.query
        .filter(WithdrawRequest.user_id == user_id)
        .filter(WithdrawRequest.created_at >= window_start)
        .filter(~WithdrawRequest.status.in_(['rejected', 'failed']))
        .order_by(WithdrawRequest.created_at.desc())
        .first()
    )

@finance_bp.route('/')
@login_required
def index():
    if current_user.is_admin:
        return redirect(url_for('finance.withdraw_list'))
    if current_user.is_god or current_user.is_player:
        return redirect(url_for('finance.my_wallet'))
    flash('无权访问财务中心', 'error')
    return redirect(url_for('dashboard.index'))

@finance_bp.route('/wallet')
@login_required
def my_wallet():
    # Transaction history (Withdrawals + Commission Logs)
    withdrawals = WithdrawRequest.query.filter_by(user_id=current_user.id).order_by(WithdrawRequest.created_at.desc()).all()
    commission_logs = CommissionLog.query.filter_by(user_id=current_user.id).order_by(CommissionLog.created_at.desc()).limit(20).all()
    
    return render_template('finance/wallet.html', withdrawals=withdrawals, commission_logs=commission_logs)

@finance_bp.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    if not current_user.is_player:
        flash('只有陪玩可以提现', 'error')
        return redirect(url_for('finance.my_wallet'))

    def _render_page():
        saved_payment = _get_saved_withdraw_payment(current_user.id)
        return render_template('finance/withdraw.html', saved_payment=saved_payment)

    if request.method == 'POST':
        amount_str = request.form.get('amount', '0')
        try:
            amount = Decimal(amount_str)
        except Exception:
            flash('无效的金额格式', 'error')
            return _render_page()

        # Validation
        if amount <= 0:
            flash('提现金额必须大于0', 'error')
            return _render_page()

        if amount > current_user.m_bean:
            flash('余额不足', 'error')
            return _render_page()

        pending = WithdrawRequest.query.filter_by(user_id=current_user.id, status='pending').first()
        if pending:
            flash(f'你有一笔待审核提现（#{pending.id}），请等待处理', 'error')
            return _render_page()

        recent_wr = _get_recent_withdrawal_within_3_days(current_user.id)
        if recent_wr:
            next_time = (recent_wr.created_at + timedelta(days=3)).strftime('%Y-%m-%d %H:%M')
            flash(f'限制：3天内仅可提交1次提现申请。你可在 {next_time} 后再次申请。', 'error')
            return _render_page()

        saved_payment = _get_saved_withdraw_payment(current_user.id)
        wechat_account = (request.form.get('wechat_account', '').strip() or saved_payment.get('wechat_account', ''))
        alipay_account = (request.form.get('alipay_account', '').strip() or saved_payment.get('alipay_account', ''))

        wechat_image_upload, wechat_err = _save_payment_image(request.files.get('wechat_payment_image'))
        if wechat_err:
            flash(wechat_err, 'error')
            return _render_page()
        alipay_image_upload, alipay_err = _save_payment_image(request.files.get('alipay_payment_image'))
        if alipay_err:
            flash(alipay_err, 'error')
            return _render_page()

        wechat_image = wechat_image_upload or saved_payment.get('wechat_image', '')
        alipay_image = alipay_image_upload or saved_payment.get('alipay_image', '')

        if not wechat_image or not alipay_image:
            flash('请上传微信和支付宝收款码（首次必填；后续可不重复上传）', 'error')
            return _render_page()

        payment_account = f"微信:{wechat_account or '-'} | 支付宝:{alipay_account or '-'}"
        payment_image = f"{wechat_image}|{alipay_image}"

        # Create request
        wr = WithdrawRequest(
            user_id=current_user.id,
            amount=amount,
            payment_method='wechat+alipay',
            payment_account=payment_account,
            payment_image=payment_image
        )

        # Deduct balance immediately (freeze it)
        # Assuming model handles types correctly (Numeric -> Decimal)
        current_user.m_bean -= amount
        current_user.m_bean_frozen += amount
        
        db.session.add(wr)
        
        # Log withdrawal request (optional, or just rely on WithdrawRequest)
        
        try:
            db.session.commit()
            try:
                from app.services.kook_service import push_withdraw_submit_notice
                push_withdraw_submit_notice(wr)
            except Exception as e:
                current_app.logger.warning(f'提现提交私信通知失败: {e}')
            flash('提现申请已提交，等待审核', 'success')
            return redirect(url_for('finance.my_wallet'))
        except Exception as e:
            db.session.rollback()
            flash(f'提交失败: {str(e)}', 'error')
            return _render_page()

    return _render_page()

# Admin Routes
@finance_bp.route('/withdraws')
@login_required
@admin_required
def withdraw_list():
    status = request.args.get('status', 'all')
    keyword = request.args.get('q', '').strip()

    total_withdraw_amount = db.session.query(
        func.coalesce(func.sum(WithdrawRequest.amount), 0)
    ).scalar() or Decimal('0')
    pending_withdraw_amount = db.session.query(
        func.coalesce(func.sum(WithdrawRequest.amount), 0)
    ).filter(WithdrawRequest.status == 'pending').scalar() or Decimal('0')
    paid_withdraw_amount = db.session.query(
        func.coalesce(func.sum(WithdrawRequest.amount), 0)
    ).filter(WithdrawRequest.status == 'paid').scalar() or Decimal('0')

    pending_withdraw_count = WithdrawRequest.query.filter(WithdrawRequest.status == 'pending').count()
    paid_withdraw_count = WithdrawRequest.query.filter(WithdrawRequest.status == 'paid').count()

    query = WithdrawRequest.query
    
    if status != 'all':
        query = query.filter(WithdrawRequest.status == status)

    if keyword:
        keyword_filters = [
            User.player_nickname.ilike(f'%{keyword}%'),
            User.kook_username.ilike(f'%{keyword}%'),
            User.nickname.ilike(f'%{keyword}%'),
            User.username.ilike(f'%{keyword}%'),
            User.kook_id.ilike(f'%{keyword}%'),
            User.user_code.ilike(f'%{keyword}%'),
        ]
        if keyword.isdigit():
            keyword_filters.append(WithdrawRequest.id == int(keyword))
        query = query.join(WithdrawRequest.user).filter(or_(*keyword_filters))
        
    withdrawals = query.order_by(WithdrawRequest.created_at.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=20)
    
    stats = {
        'total_withdraw_amount': total_withdraw_amount,
        'pending_withdraw_amount': pending_withdraw_amount,
        'paid_withdraw_amount': paid_withdraw_amount,
        'pending_withdraw_count': pending_withdraw_count,
        'paid_withdraw_count': paid_withdraw_count,
    }

    return render_template(
        'finance/withdraw_list.html',
        withdrawals=withdrawals,
        current_status=status,
        current_query=keyword,
        stats=stats,
    )


@finance_bp.route('/recharges')
@login_required
@admin_required
def recharge_overview():
    """充值总览（手动充值嗯呢币账单）"""
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('q', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    recharge_cond = and_(
        BalanceLog.change_type == 'recharge',
        BalanceLog.amount > 0,
        ~func.coalesce(BalanceLog.reason, '').ilike('%赠金%'),
    )
    # 负值管理变账也纳入充值总览，便于人工对账
    negative_adjust_cond = and_(
        BalanceLog.change_type == 'admin_adjust',
        BalanceLog.amount < 0,
    )

    query = BalanceLog.query.filter(
        BalanceLog.operator_id.isnot(None),
        or_(recharge_cond, negative_adjust_cond),
    )

    from_date_obj = None
    to_date_obj = None
    if date_from:
        try:
            from_date_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            start_utc, _ = _bj_day_utc_range(from_date_obj)
            query = query.filter(BalanceLog.created_at >= start_utc)
        except ValueError:
            date_from = ''
    if date_to:
        try:
            to_date_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            _, end_utc = _bj_day_utc_range(to_date_obj)
            query = query.filter(BalanceLog.created_at < end_utc)
        except ValueError:
            date_to = ''

    if keyword:
        user_match_q = db.session.query(User.id).filter(or_(
            User.player_nickname.ilike(f'%{keyword}%'),
            User.kook_username.ilike(f'%{keyword}%'),
            User.nickname.ilike(f'%{keyword}%'),
            User.username.ilike(f'%{keyword}%'),
            User.kook_id.ilike(f'%{keyword}%'),
            User.user_code.ilike(f'%{keyword}%'),
        ))
        keyword_filters = [
            BalanceLog.user_id.in_(user_match_q),
            BalanceLog.operator_id.in_(user_match_q),
            BalanceLog.reason.ilike(f'%{keyword}%'),
        ]
        if keyword.isdigit():
            keyword_filters.append(BalanceLog.id == int(keyword))
        query = query.filter(or_(*keyword_filters))

    filtered_rows = query.with_entities(
        BalanceLog.id,
        BalanceLog.user_id,
        BalanceLog.operator_id,
        BalanceLog.change_type,
        BalanceLog.amount,
        BalanceLog.reason,
        BalanceLog.created_at,
    ).order_by(BalanceLog.created_at.asc(), BalanceLog.id.asc()).all()

    bj_today = datetime.now(BJ_TZ).date()
    today_start, tomorrow_start = _bj_day_utc_range(bj_today)
    today_rows = BalanceLog.query.filter(
        BalanceLog.operator_id.isnot(None),
        or_(recharge_cond, negative_adjust_cond),
        BalanceLog.created_at >= today_start,
        BalanceLog.created_at < tomorrow_start,
    ).with_entities(
        BalanceLog.id,
        BalanceLog.user_id,
        BalanceLog.operator_id,
        BalanceLog.change_type,
        BalanceLog.amount,
        BalanceLog.reason,
        BalanceLog.created_at,
    ).order_by(BalanceLog.created_at.asc(), BalanceLog.id.asc()).all()

    related_user_ids = {row.user_id for row in filtered_rows}
    related_user_ids.update(row.user_id for row in today_rows)

    refunded_ids = set()
    if related_user_ids:
        all_recharge_rows = BalanceLog.query.filter(
            BalanceLog.change_type == 'recharge',
            BalanceLog.amount > 0,
            BalanceLog.operator_id.isnot(None),
            ~func.coalesce(BalanceLog.reason, '').ilike('%赠金%'),
            BalanceLog.user_id.in_(list(related_user_ids)),
        ).with_entities(
            BalanceLog.id,
            BalanceLog.user_id,
            BalanceLog.operator_id,
            BalanceLog.amount,
            BalanceLog.created_at,
        ).all()

        refund_rows = BalanceLog.query.filter(
            BalanceLog.change_type == 'admin_adjust',
            BalanceLog.amount < 0,
            BalanceLog.operator_id.isnot(None),
            BalanceLog.user_id.in_(list(related_user_ids)),
        ).with_entities(
            BalanceLog.id,
            BalanceLog.user_id,
            BalanceLog.operator_id,
            BalanceLog.amount,
            BalanceLog.created_at,
            BalanceLog.reason,
        ).all()

        refunded_ids = _build_refunded_recharge_ids(all_recharge_rows, refund_rows)

    def _visible_recharge_row(row):
        if row.change_type == 'recharge' and row.id in refunded_ids:
            return False
        return True

    visible_filtered_rows = [r for r in filtered_rows if _visible_recharge_row(r)]
    visible_today_rows = [r for r in today_rows if _visible_recharge_row(r)]
    filtered_total = sum((_q_money(r.amount) for r in visible_filtered_rows), Decimal('0.00'))
    filtered_count = len(visible_filtered_rows)
    today_total = sum((_q_money(r.amount) for r in visible_today_rows), Decimal('0.00'))
    today_count = len(visible_today_rows)

    logs_query = query
    if refunded_ids:
        logs_query = logs_query.filter(or_(
            BalanceLog.change_type != 'recharge',
            ~BalanceLog.id.in_(list(refunded_ids)),
        ))
    logs = logs_query.order_by(BalanceLog.created_at.desc()).paginate(page=page, per_page=20, error_out=False)

    user_ids = set()
    for log in logs.items:
        if log.user_id:
            user_ids.add(log.user_id)
        if log.operator_id:
            user_ids.add(log.operator_id)
    users = User.query.filter(User.id.in_(list(user_ids))).all() if user_ids else []
    user_map = {u.id: u for u in users}

    pagination_args = request.args.to_dict(flat=True)
    pagination_args.pop('page', None)

    return render_template(
        'finance/recharge_overview.html',
        logs=logs,
        user_map=user_map,
        keyword=keyword,
        date_from=date_from,
        date_to=date_to,
        stats={
            'filtered_total': filtered_total,
            'filtered_count': filtered_count,
            'today_total': today_total,
            'today_count': today_count,
        },
        pagination_args=pagination_args,
    )

@finance_bp.route('/withdraw/<int:request_id>/audit', methods=['POST'])
@login_required
@admin_required
def audit_withdraw(request_id):
    """提现审批 - 仅管理员+"""
        
    wr = WithdrawRequest.query.get_or_404(request_id)
    if wr.status != 'pending':
        flash('该申请已处理', 'error')
        return _redirect_after_withdraw_audit(row_id=wr.id)
        
    action = request.form.get('action') # approve, reject
    remark = request.form.get('remark')
    if action not in ('approve', 'reject'):
        flash('未知审核操作', 'error')
        return _redirect_after_withdraw_audit(row_id=wr.id)

    wr.auditor_id = current_user.id
    wr.audit_at = datetime.utcnow()
    wr.audit_remark = remark
    
    try:
        if action == 'approve':
            wr.status = 'paid'
            wr.paid_at = datetime.utcnow()
            
            # Unfreeze (reduce frozen amount)
            # Money was already deducted from m_bean when requesting
            wr.user.m_bean_frozen -= wr.amount
            
            # Log commission change (actual payout)
            log = CommissionLog(
                user_id=wr.user_id,
                change_type='withdraw',
                amount=-wr.amount,
                balance_after=wr.user.m_bean,
                reason=f'提现成功 (单号: {wr.id})'
            )
            db.session.add(log)
            log_operation(
                current_user.id,
                'withdraw_approve',
                'withdraw',
                wr.id,
                f'审核通过提现 #{wr.id}，用户ID={wr.user_id}，金额={wr.amount}，备注={remark or "-"}',
            )
            flash('提现已通过并标记为已打款', 'success')
            
        elif action == 'reject':
            wr.status = 'rejected'
            
            # Refund balance
            wr.user.m_bean += wr.amount
            wr.user.m_bean_frozen -= wr.amount
            log_operation(
                current_user.id,
                'withdraw_reject',
                'withdraw',
                wr.id,
                f'审核拒绝提现 #{wr.id}，用户ID={wr.user_id}，金额={wr.amount}，备注={remark or "-"}',
            )
            
            flash('提现申请已拒绝，余额已退回', 'success')
            
        db.session.commit()
        try:
            from app.services.kook_service import (
                push_withdraw_approved_notice,
                push_withdraw_rejected_notice,
            )
            operator_name = current_user.staff_display_name
            if action == 'approve':
                push_withdraw_approved_notice(wr, operator=operator_name, remark=remark or '')
            elif action == 'reject':
                push_withdraw_rejected_notice(wr, operator=operator_name, remark=remark or '')
        except Exception as e:
            current_app.logger.warning(f'提现审核私信通知失败: {e}')
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {str(e)}', 'error')

    return _redirect_after_withdraw_audit(row_id=wr.id)


@finance_bp.route('/balance_logs')
@login_required
def balance_detail():
    """嗯呢币余额明细（老板可见）"""
    page = request.args.get('page', 1, type=int)
    change_type = request.args.get('type', '')

    query = BalanceLog.query.filter_by(user_id=current_user.id)
    if change_type:
        query = query.filter_by(change_type=change_type)

    logs = query.order_by(BalanceLog.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('finance/balance_detail.html', logs=logs, current_type=change_type)


@finance_bp.route('/commission_logs')
@login_required
def commission_detail():
    """小猪粮余额明细（陪玩/客服可见）"""
    page = request.args.get('page', 1, type=int)
    change_type = request.args.get('type', '')
    allowed_change_types = {
        'order_income',
        'gift_income',
        'withdraw_freeze',
        'withdraw',
        'refund_deduct',
        'admin_adjust',
        'exchange_in',
        'exchange_out',
    }
    if change_type not in allowed_change_types:
        change_type = ''

    query = CommissionLog.query.filter_by(user_id=current_user.id)
    query = query.filter(~CommissionLog.change_type.in_(['staff_commission', 'staff_refund_deduct']))
    if change_type:
        query = query.filter_by(change_type=change_type)

    logs = query.order_by(CommissionLog.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('finance/commission_detail.html', logs=logs, current_type=change_type)
