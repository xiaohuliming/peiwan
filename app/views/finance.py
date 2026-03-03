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
        
    if request.method == 'POST':
        amount_str = request.form.get('amount', '0')
        try:
            amount = Decimal(amount_str)
        except:
            flash('无效的金额格式', 'error')
            return render_template('finance/withdraw.html')
            
        payment_method = request.form.get('payment_method')
        payment_account = request.form.get('payment_account')
        
        # Validation
        if amount <= 0:
            flash('提现金额必须大于0', 'error')
            return render_template('finance/withdraw.html')
            
        if amount > current_user.m_bean:
            flash('余额不足', 'error')
            return render_template('finance/withdraw.html')
            
        if not payment_account:
            flash('请填写收款账号', 'error')
            return render_template('finance/withdraw.html')
            
        # Handle Image Upload
        payment_image_path = None
        if 'payment_image' in request.files:
            file = request.files['payment_image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'payment_codes')
                
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                    
                file.save(os.path.join(upload_folder, unique_filename))
                payment_image_path = f"uploads/payment_codes/{unique_filename}"
            
        # Create request
        wr = WithdrawRequest(
            user_id=current_user.id,
            amount=amount,
            payment_method=payment_method,
            payment_account=payment_account,
            payment_image=payment_image_path
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
            
    return render_template('finance/withdraw.html')

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
