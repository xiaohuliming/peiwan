from decimal import Decimal
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.extensions import db
from app.models.project import Project, ProjectItem
from app.utils.permissions import admin_required
from app.services.log_service import log_operation

project_admin_bp = Blueprint('project_admin', __name__, template_folder='../templates')


@project_admin_bp.route('/')
@login_required
@admin_required
def index():
    projects = Project.query.order_by(Project.sort_order, Project.id).all()
    return render_template('admin/projects.html', projects=projects)


@project_admin_bp.route('/add', methods=['POST'])
@login_required
@admin_required
def add_project():
    name = request.form.get('name', '').strip()
    sort_order = request.form.get('sort_order', 0, type=int)
    if not name:
        flash('项目名称不能为空', 'error')
        return redirect(url_for('project_admin.index'))

    if Project.query.filter_by(name=name).first():
        flash('项目名称已存在', 'error')
        return redirect(url_for('project_admin.index'))

    project = Project(name=name, sort_order=sort_order)
    db.session.add(project)
    db.session.commit()

    log_operation(current_user.id, 'project_add', 'project', project.id, f'添加项目: {name}')
    db.session.commit()

    flash('项目添加成功', 'success')
    return redirect(url_for('project_admin.index'))


@project_admin_bp.route('/<int:project_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)
    project.name = request.form.get('name', project.name).strip()
    project.sort_order = request.form.get('sort_order', project.sort_order, type=int)
    project.status = 'status' in request.form
    db.session.commit()

    log_operation(current_user.id, 'project_edit', 'project', project.id, f'编辑项目: {project.name}')
    db.session.commit()

    flash('项目更新成功', 'success')
    return redirect(url_for('project_admin.index'))


@project_admin_bp.route('/<int:project_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    name = project.name
    # 删除所有子项目
    ProjectItem.query.filter_by(project_id=project_id).delete()
    db.session.delete(project)
    db.session.commit()

    log_operation(current_user.id, 'project_delete', 'project', project_id, f'删除项目: {name}')
    db.session.commit()

    flash('项目已删除', 'success')
    return redirect(url_for('project_admin.index'))


@project_admin_bp.route('/<int:project_id>/items/add', methods=['POST'])
@login_required
@admin_required
def add_item(project_id):
    project = Project.query.get_or_404(project_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('子项目名称不能为空', 'error')
        return redirect(url_for('project_admin.index'))

    item = ProjectItem(
        project_id=project.id,
        name=name,
        price_casual=Decimal(request.form.get('price_casual', '0') or '0'),
        price_tech=Decimal(request.form.get('price_tech', '0') or '0'),
        price_god=Decimal(request.form.get('price_god', '0') or '0'),
        # 巅峰档沿用旧字段 price_pro，兼容历史表单参数
        price_pro=Decimal(request.form.get('price_peak', request.form.get('price_pro', '0')) or '0'),
        price_devil=Decimal(request.form.get('price_devil', request.form.get('price_peak', request.form.get('price_pro', '0'))) or '0'),
        commission_rate=Decimal(request.form.get('commission_rate', '80') or '80'),
        billing_type=request.form.get('billing_type', 'hour'),
        project_type=request.form.get('project_type', 'normal'),
        sort_order=request.form.get('sort_order', 0, type=int),
    )
    db.session.add(item)
    db.session.commit()

    log_operation(current_user.id, 'item_add', 'project_item', item.id,
                  f'添加子项目: {project.name} - {name}')
    db.session.commit()

    flash('子项目添加成功', 'success')
    return redirect(url_for('project_admin.index'))


@project_admin_bp.route('/items/<int:item_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_item(item_id):
    item = ProjectItem.query.get_or_404(item_id)
    item.name = request.form.get('name', item.name).strip()
    item.price_casual = Decimal(request.form.get('price_casual', '0') or '0')
    item.price_tech = Decimal(request.form.get('price_tech', '0') or '0')
    item.price_god = Decimal(request.form.get('price_god', '0') or '0')
    item.price_pro = Decimal(request.form.get('price_peak', request.form.get('price_pro', '0')) or '0')
    item.price_devil = Decimal(request.form.get('price_devil', request.form.get('price_peak', request.form.get('price_pro', str(item.price_devil or 0)))) or '0')
    item.commission_rate = Decimal(request.form.get('commission_rate', '80') or '80')
    item.billing_type = request.form.get('billing_type', 'hour')
    item.project_type = request.form.get('project_type', 'normal')
    item.sort_order = request.form.get('sort_order', 0, type=int)
    item.status = 'status' in request.form
    db.session.commit()

    log_operation(current_user.id, 'item_edit', 'project_item', item.id,
                  f'编辑子项目: {item.project.name} - {item.name}')
    db.session.commit()

    flash('子项目更新成功', 'success')
    return redirect(url_for('project_admin.index'))


@project_admin_bp.route('/items/<int:item_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_item(item_id):
    item = ProjectItem.query.get_or_404(item_id)
    desc = f'{item.project.name} - {item.name}'
    db.session.delete(item)
    db.session.commit()

    log_operation(current_user.id, 'item_delete', 'project_item', item_id, f'删除子项目: {desc}')
    db.session.commit()

    flash('子项目已删除', 'success')
    return redirect(url_for('project_admin.index'))
