from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models.user import User
from app.extensions import db
from app.utils.permissions import staff_required

companions_bp = Blueprint('companions', __name__)


@companions_bp.route('/')
@login_required
def index():
    # 客服+和老板可以查看陪玩列表 (老板用于点单场景)
    if not (current_user.is_staff or current_user.is_god):
        flash('无权访问', 'error')
        return redirect(url_for('dashboard.index'))

    page = request.args.get('page', 1, type=int)
    query = User.query.filter(User.role_filter_expr('player'))

    search_query = request.args.get('q')
    if search_query:
        query = query.filter(
            User.player_nickname.ilike(f'%{search_query}%') |
            User.username.ilike(f'%{search_query}%')
        )

    players = query.order_by(User.created_at.desc()).paginate(page=page, per_page=10)

    return render_template('companions/index.html', players=players)


@companions_bp.route('/toggle_status/<int:user_id>', methods=['POST'])
@login_required
@staff_required
def toggle_status(user_id):
    """启用/禁用陪玩 - 仅客服+"""
    user = User.query.get_or_404(user_id)
    if not user.is_player:
        flash('只能修改陪玩状态', 'error')
        return redirect(url_for('companions.index'))

    user.status = not user.status
    db.session.commit()

    status_msg = '启用' if user.status else '禁用'
    flash(f'陪玩 {user.player_nickname} 已{status_msg}', 'success')
    return redirect(url_for('companions.index'))
