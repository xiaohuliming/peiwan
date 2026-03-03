from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.models.finance import WithdrawRequest, CommissionLog
from app.extensions import db
from app.utils.permissions import admin_required
from datetime import datetime
from decimal import Decimal
import os
import uuid
from werkzeug.utils import secure_filename

finance_bp = Blueprint('finance', __name__)

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

@finance_bp.route('/')
@login_required
def index():
    if current_user.is_admin:
        return redirect(url_for('finance.withdraw_list'))
    if current_user.is_staff:
        flash('客服无权访问财务中心', 'error')
        return redirect(url_for('dashboard.index'))
    return redirect(url_for('finance.my_wallet'))

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
    query = WithdrawRequest.query
    
    if status != 'all':
        query = query.filter(WithdrawRequest.status == status)
        
    withdrawals = query.order_by(WithdrawRequest.created_at.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=20)
    
    return render_template('finance/withdraw_list.html', withdrawals=withdrawals, current_status=status)

@finance_bp.route('/withdraw/<int:request_id>/audit', methods=['POST'])
@login_required
@admin_required
def audit_withdraw(request_id):
    """提现审批 - 仅管理员+"""
        
    wr = WithdrawRequest.query.get_or_404(request_id)
    if wr.status != 'pending':
        flash('该申请已处理', 'error')
        return redirect(url_for('finance.withdraw_list'))
        
    action = request.form.get('action') # approve, reject
    remark = request.form.get('remark')
    
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
            flash('提现已通过并标记为已打款', 'success')
            
        elif action == 'reject':
            wr.status = 'rejected'
            
            # Refund balance
            wr.user.m_bean += wr.amount
            wr.user.m_bean_frozen -= wr.amount
            
            flash('提现申请已拒绝，余额已退回', 'success')
            
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {str(e)}', 'error')
        
    return redirect(url_for('finance.withdraw_list'))
