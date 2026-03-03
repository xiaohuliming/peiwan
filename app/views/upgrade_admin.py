from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.extensions import db
from app.models.vip import UpgradeRecord
from app.utils.permissions import staff_required
from app.services.log_service import log_operation

upgrade_admin_bp = Blueprint('upgrade_admin', __name__, template_folder='../templates')


@upgrade_admin_bp.route('/')
@login_required
@staff_required
def index():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '')

    query = UpgradeRecord.query
    if status:
        query = query.filter_by(benefit_status=status)

    records = query.order_by(UpgradeRecord.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin/upgrades.html', records=records, status=status)


@upgrade_admin_bp.route('/<int:record_id>/grant', methods=['POST'])
@login_required
@staff_required
def grant(record_id):
    record = UpgradeRecord.query.get_or_404(record_id)
    if record.benefit_status == 'granted':
        flash('权益已发放', 'error')
        return redirect(url_for('upgrade_admin.index'))

    record.benefit_status = 'granted'
    record.granted_by = current_user.id
    record.granted_at = datetime.utcnow()
    db.session.commit()

    log_operation(current_user.id, 'upgrade_grant', 'upgrade_record', record.id,
                  f'确认发放升级权益: {record.user.nickname or record.user.username} {record.from_level} → {record.to_level}')
    db.session.commit()

    flash('权益已确认发放', 'success')
    return redirect(url_for('upgrade_admin.index'))
