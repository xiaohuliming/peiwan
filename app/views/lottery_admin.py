import json
from datetime import datetime

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.lottery import Lottery, LotteryParticipant, LotteryWinner
from app.models.user import User
from app.utils.permissions import staff_required
from app.services.log_service import log_operation
from app.services import lottery_service

lottery_admin_bp = Blueprint('lottery_admin', __name__, template_folder='../templates')


@lottery_admin_bp.route('/')
@login_required
@staff_required
def index():
    lotteries = Lottery.query.order_by(Lottery.created_at.desc()).all()
    participant_counts = dict(
        db.session.query(
            LotteryParticipant.lottery_id,
            func.count(LotteryParticipant.id),
        )
        .group_by(LotteryParticipant.lottery_id)
        .all()
    )
    return render_template(
        'admin/lottery.html',
        lotteries=lotteries,
        participant_counts=participant_counts,
    )


@lottery_admin_bp.route('/create', methods=['GET', 'POST'])
@login_required
@staff_required
def create():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        prize = request.form.get('prize', '').strip()
        winner_count = int(request.form.get('winner_count', 1) or 1)
        channel_id = request.form.get('channel_id', '').strip()
        emoji = request.form.get('emoji', '🎉').strip() or '🎉'
        description = request.form.get('description', '').strip()
        draw_time_str = request.form.get('draw_time', '').strip()

        # 参与资格
        eligible_roles = request.form.getlist('eligible_roles')
        min_vip_level = request.form.get('min_vip_level', '').strip()

        # 内定用户 (逗号分隔的用户 ID)
        rigged_str = request.form.get('rigged_user_ids', '').strip()
        rigged_ids = []
        if rigged_str:
            for s in rigged_str.replace('，', ',').split(','):
                s = s.strip()
                if s.isdigit():
                    rigged_ids.append(int(s))

        if not title or not prize or not channel_id or not draw_time_str:
            flash('请填写必填项', 'error')
            return redirect(url_for('lottery_admin.create'))

        try:
            draw_time = datetime.strptime(draw_time_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('开奖时间格式错误', 'error')
            return redirect(url_for('lottery_admin.create'))

        lottery = Lottery(
            title=title,
            description=description,
            prize=prize,
            winner_count=winner_count,
            channel_id=channel_id,
            emoji=emoji,
            eligible_roles=json.dumps(eligible_roles) if eligible_roles else None,
            min_vip_level=min_vip_level or None,
            draw_time=draw_time,
            created_by=current_user.id,
            rigged_user_ids=json.dumps(rigged_ids) if rigged_ids else None,
        )
        db.session.add(lottery)
        db.session.commit()

        log_operation(current_user.id, 'lottery_create', 'lottery', lottery.id,
                      f'创建抽奖: {title}')
        db.session.commit()

        flash('抽奖已创建', 'success')
        return redirect(url_for('lottery_admin.detail', lottery_id=lottery.id))

    from app.models.vip import VipLevel
    vip_levels = VipLevel.query.order_by(VipLevel.sort_order).all()
    return render_template('admin/lottery_form.html', vip_levels=vip_levels)


@lottery_admin_bp.route('/<int:lottery_id>')
@login_required
@staff_required
def detail(lottery_id):
    lottery = Lottery.query.get_or_404(lottery_id)
    winners = LotteryWinner.query.filter_by(lottery_id=lottery_id).all()
    participants = (
        LotteryParticipant.query
        .options(joinedload(LotteryParticipant.user))
        .filter_by(lottery_id=lottery_id)
        .order_by(LotteryParticipant.joined_at.asc())
        .all()
    )
    return render_template(
        'admin/lottery_detail.html',
        lottery=lottery,
        winners=winners,
        participants=participants,
    )


@lottery_admin_bp.route('/<int:lottery_id>/publish', methods=['POST'])
@login_required
@staff_required
def publish(lottery_id):
    lottery = Lottery.query.get_or_404(lottery_id)
    ok, msg = lottery_service.publish_lottery(lottery)
    if ok:
        log_operation(current_user.id, 'lottery_publish', 'lottery', lottery.id,
                      f'发布抽奖: {lottery.title}')
        db.session.commit()
        flash(msg, 'success')
    else:
        flash(msg, 'error')
    return redirect(url_for('lottery_admin.detail', lottery_id=lottery.id))


@lottery_admin_bp.route('/<int:lottery_id>/draw', methods=['POST'])
@login_required
@staff_required
def draw(lottery_id):
    lottery = Lottery.query.get_or_404(lottery_id)
    ok, msg = lottery_service.draw_lottery(lottery)
    if ok:
        log_operation(current_user.id, 'lottery_draw', 'lottery', lottery.id,
                      f'手动开奖: {lottery.title}')
        db.session.commit()
        flash(msg, 'success')
    else:
        flash(msg, 'error')
    return redirect(url_for('lottery_admin.detail', lottery_id=lottery.id))


@lottery_admin_bp.route('/<int:lottery_id>/cancel', methods=['POST'])
@login_required
@staff_required
def cancel(lottery_id):
    lottery = Lottery.query.get_or_404(lottery_id)
    ok, msg = lottery_service.cancel_lottery(lottery)
    if ok:
        log_operation(current_user.id, 'lottery_cancel', 'lottery', lottery.id,
                      f'取消抽奖: {lottery.title}')
        db.session.commit()
        flash(msg, 'success')
    else:
        flash(msg, 'error')
    return redirect(url_for('lottery_admin.detail', lottery_id=lottery.id))


@lottery_admin_bp.route('/<int:lottery_id>/delete', methods=['POST'])
@login_required
@staff_required
def delete(lottery_id):
    lottery = Lottery.query.get_or_404(lottery_id)
    if lottery.status == 'published':
        flash('已发布的抽奖请先取消再删除', 'error')
        return redirect(url_for('lottery_admin.detail', lottery_id=lottery.id))

    title = lottery.title
    db.session.delete(lottery)
    db.session.commit()

    log_operation(current_user.id, 'lottery_delete', 'lottery', lottery_id,
                  f'删除抽奖: {title}')
    db.session.commit()

    flash('抽奖已删除', 'success')
    return redirect(url_for('lottery_admin.index'))
