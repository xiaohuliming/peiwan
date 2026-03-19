"""
AI 助理小呢 — API 路由
"""
import traceback
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user

from app.services.assistant_service import chat

assistant_bp = Blueprint('assistant', __name__)


@assistant_bp.route('/chat', methods=['POST'])
@login_required
def chat_api():
    """POST /assistant/chat — 与助理小呢对话"""
    try:
        data = request.get_json(silent=True)
        if not data or not data.get('message', '').strip():
            return jsonify({'ok': False, 'error': '消息不能为空'}), 400

        user_message = data['message'].strip()
        history = data.get('history', [])

        # 简单限长保护
        if len(user_message) > 2000:
            return jsonify({'ok': False, 'error': '消息太长啦，请精简一下 😅'}), 400

        ok, reply, err = chat(user_message, conversation_history=history)

        if ok:
            return jsonify({'ok': True, 'reply': reply})
        else:
            return jsonify({'ok': False, 'error': err}), 500

    except Exception as e:
        current_app.logger.error(f'[Assistant] Route crash: {traceback.format_exc()}')
        return jsonify({'ok': False, 'error': f'助理服务异常，请稍后重试 😢'}), 500
