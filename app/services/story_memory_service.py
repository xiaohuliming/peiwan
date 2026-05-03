"""
AI 剧情长期记忆适配层。

第一版支持两种 mem0 接入方式：
- mem0_sdk：Flask 进程内用 mem0 Python SDK，适合单机试点。
- mem0_rest：调用独立 mem0 REST 服务，适合后续生产部署。

记忆层是增强能力，失败时只记录日志，不阻断剧情主流程。
"""
import os
import gc
from functools import lru_cache
from importlib import util as importlib_util
from urllib.parse import urlparse

import requests
from flask import current_app, has_app_context


def is_memory_enabled():
    return _config_bool('STORY_MEMORY_ENABLED', False)


def search_story_memories(kook_id, query, limit=None):
    if not is_memory_enabled():
        return []
    kook_id = str(kook_id or '').strip()
    query = str(query or '').strip()
    if not kook_id or not query:
        return []

    limit = int(limit or _config_int('STORY_MEMORY_LIMIT', 8))
    try:
        if _backend() == 'mem0_rest':
            return _search_rest(kook_id, query, limit)
        return _search_sdk(kook_id, query, limit)
    except Exception as exc:
        _log_warning('[StoryMemory] 检索失败: %s', exc)
        return []


def remember_story_turn(kook_id, user_id=None, user_input='', visible_text='', metadata=None):
    if not is_memory_enabled():
        return False
    kook_id = str(kook_id or '').strip()
    user_input = str(user_input or '').strip()
    visible_text = str(visible_text or '').strip()
    if not kook_id or not (user_input or visible_text):
        return False

    metadata = dict(metadata or {})
    if user_id:
        metadata['user_id'] = user_id
    metadata.setdefault('source', 'kook_story')

    messages = []
    if user_input:
        messages.append({'role': 'user', 'content': user_input})
    if visible_text:
        messages.append({'role': 'assistant', 'content': visible_text})

    try:
        if _backend() == 'mem0_rest':
            _add_rest(kook_id, messages, metadata)
        else:
            _add_sdk(kook_id, messages, metadata)
        return True
    except Exception as exc:
        _log_warning('[StoryMemory] 写入失败: %s', exc)
        return False


def memory_status_lines():
    health = memory_health_status(check_connection=False)
    status = '启用' if health['enabled'] else '关闭'
    ready = '就绪' if health['ready'] else '待配置'
    lines = [
        f"│ 长期记忆：{status}",
        f"│ 记忆后端：{health['backend']}",
        f"│ 记忆状态：{ready}",
    ]
    if health['backend'] == 'mem0_rest':
        lines.append(f"│ Mem0 API：{_config('MEM0_API_URL', '-') or '-'}")
    else:
        lines.append(
            "│ Mem0 SDK："
            f"{_config('MEM0_VECTOR_PROVIDER', 'qdrant')} / "
            f"{_config('MEM0_EMBEDDER_PROVIDER', 'fastembed')} / "
            f"{_config('MEM0_LLM_PROVIDER', 'deepseek')}"
        )
    for issue in health['issues'][:3]:
        lines.append(f"│ 记忆提示：{issue}")
    if not is_memory_enabled():
        lines.append("│ 开启方式：STORY_MEMORY_ENABLED=true")
    return lines


def memory_health_status(check_connection=False):
    """返回 mem0 配置健康状态；默认不做网络探测，避免页面渲染被外部服务拖慢。"""
    backend = _backend()
    enabled = is_memory_enabled()
    issues = []
    details = []

    if not enabled:
        issues.append('STORY_MEMORY_ENABLED=false，长期记忆当前关闭')

    if backend == 'mem0_rest':
        _append_rest_health(issues, details, check_connection)
    else:
        _append_sdk_health(issues, details, check_connection)

    blocking = [issue for issue in issues if not issue.startswith('STORY_MEMORY_ENABLED=false')]
    return {
        'enabled': enabled,
        'backend': backend,
        'ready': enabled and not blocking,
        'configured': not blocking,
        'issues': issues,
        'details': details,
    }


def reset_memory_client():
    _sdk_memory.cache_clear()
    gc.collect()


def _backend():
    backend = str(_config('STORY_MEMORY_BACKEND', 'mem0_sdk') or '').strip().lower()
    return backend if backend in ('mem0_sdk', 'mem0_rest') else 'mem0_sdk'


def _search_rest(kook_id, query, limit):
    url = _rest_url('/search')
    payload = {'query': query, 'user_id': kook_id, 'limit': limit}
    data = _request_rest('post', url, json=payload)
    return _extract_memory_texts(data, limit)


def _add_rest(kook_id, messages, metadata):
    url = _rest_url('/memories')
    payload = {'messages': messages, 'user_id': kook_id, 'metadata': metadata}
    _request_rest('post', url, json=payload)


def _request_rest(method, url, **kwargs):
    headers = kwargs.pop('headers', {})
    api_key = _config('MEM0_API_KEY', '')
    if api_key:
        headers['X-API-Key'] = api_key
    resp = requests.request(
        method,
        url,
        headers=headers,
        timeout=_config_int('MEM0_TIMEOUT', 12),
        **kwargs,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'mem0 REST {resp.status_code}: {resp.text[:300]}')
    if not resp.text:
        return {}
    return resp.json()


def _rest_url(path):
    base = str(_config('MEM0_API_URL', 'http://127.0.0.1:8888') or '').strip().rstrip('/')
    return f"{base}{path}"


def _search_sdk(kook_id, query, limit):
    memory = _sdk_memory()
    try:
        data = memory.search(query, filters={'user_id': kook_id}, top_k=limit)
    except TypeError:
        try:
            data = memory.search(query, user_id=kook_id, limit=limit)
        except TypeError:
            data = memory.search(query, user_id=kook_id)
    return _extract_memory_texts(data, limit)


def _add_sdk(kook_id, messages, metadata):
    memory = _sdk_memory()
    memory.add(messages, user_id=kook_id, metadata=metadata)


@lru_cache(maxsize=1)
def _sdk_memory():
    try:
        from mem0 import Memory
    except ImportError as exc:
        raise RuntimeError('未安装 mem0ai，请先 pip install mem0ai qdrant-client') from exc
    return Memory.from_config(_sdk_config())


def _sdk_config():
    llm_provider = _config('MEM0_LLM_PROVIDER', 'deepseek')
    llm_api_key = _config('MEM0_LLM_API_KEY', '') or _config('STORY_LLM_API_KEY', '')
    llm_model = _config('MEM0_LLM_MODEL', '') or _config('STORY_LLM_MODEL', 'deepseek-v4-flash')
    llm_base = _api_base(_config('MEM0_LLM_BASE_URL', '') or _config('STORY_LLM_API_URL', 'https://api.deepseek.com'))

    embedder_provider = _config('MEM0_EMBEDDER_PROVIDER', 'fastembed')
    embedder_api_key = _config('MEM0_EMBEDDER_API_KEY', '') or _config('OPENAI_API_KEY', '')
    embedder_model = _config('MEM0_EMBEDDER_MODEL', 'BAAI/bge-small-zh-v1.5' if embedder_provider == 'fastembed' else 'text-embedding-3-small')
    embedder_base = _config('MEM0_EMBEDDER_BASE_URL', '') or _config('OPENAI_BASE_URL', '')

    vector_config = {
        'collection_name': _config('MEM0_COLLECTION_NAME', 'kook_story_memories'),
    }
    embedding_dims = _config_int('MEM0_EMBEDDER_DIMS', _default_embedding_dims(embedder_provider, embedder_model))
    if embedding_dims > 0:
        vector_config['embedding_model_dims'] = embedding_dims

    qdrant_url = str(_config('MEM0_QDRANT_URL', '') or '').strip()
    qdrant_api_key = str(_config('MEM0_QDRANT_API_KEY', '') or '').strip()
    qdrant_path = str(_config('MEM0_QDRANT_PATH', '') or '').strip()
    if _config('MEM0_VECTOR_PROVIDER', 'qdrant') == 'qdrant':
        if qdrant_url and qdrant_api_key:
            vector_config['url'] = qdrant_url
            vector_config['api_key'] = qdrant_api_key
        elif qdrant_url:
            parsed = urlparse(qdrant_url)
            vector_config['host'] = parsed.hostname or _config('MEM0_QDRANT_HOST', '127.0.0.1')
            vector_config['port'] = parsed.port or _config_int('MEM0_QDRANT_PORT', 6333)
        elif qdrant_path:
            os.makedirs(qdrant_path, exist_ok=True)
            vector_config['path'] = qdrant_path
        else:
            vector_config['host'] = _config('MEM0_QDRANT_HOST', '127.0.0.1')
            vector_config['port'] = _config_int('MEM0_QDRANT_PORT', 6333)
        if _config_bool('MEM0_QDRANT_ON_DISK', False):
            vector_config['on_disk'] = True

    history_db_path = _config('MEM0_HISTORY_DB_PATH', '') or None
    if history_db_path:
        parent = os.path.dirname(history_db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    config = {
        'llm': {
            'provider': llm_provider,
            'config': {
                'model': _normalize_deepseek_model(llm_model) if llm_provider == 'deepseek' else llm_model,
                'api_key': llm_api_key,
                'temperature': _config_float('MEM0_LLM_TEMPERATURE', 0.1),
                'max_tokens': _config_int('MEM0_LLM_MAX_TOKENS', 1200),
            },
        },
        'embedder': {
            'provider': embedder_provider,
            'config': {
                'model': embedder_model,
                'api_key': embedder_api_key,
            },
        },
        'vector_store': {
            'provider': _config('MEM0_VECTOR_PROVIDER', 'qdrant'),
            'config': vector_config,
        },
        'history_db_path': history_db_path,
    }
    if llm_provider == 'deepseek' and llm_base:
        config['llm']['config']['deepseek_base_url'] = llm_base
    if embedder_base:
        config['embedder']['config']['openai_base_url'] = _api_base(embedder_base)
    if embedding_dims > 0:
        config['embedder']['config']['embedding_dims'] = embedding_dims
    if not config['history_db_path']:
        config.pop('history_db_path', None)
    return config


def _append_sdk_health(issues, details, check_connection):
    if importlib_util.find_spec('mem0') is None:
        issues.append('未安装 mem0ai，请执行 pip install -r requirements.txt')
    else:
        details.append('mem0ai 已安装')

    if importlib_util.find_spec('qdrant_client') is None and _config('MEM0_VECTOR_PROVIDER', 'qdrant') == 'qdrant':
        issues.append('未安装 qdrant-client，请执行 pip install -r requirements.txt')

    llm_provider = _config('MEM0_LLM_PROVIDER', 'deepseek')
    llm_key = _config('MEM0_LLM_API_KEY', '') or _config('STORY_LLM_API_KEY', '')
    if llm_provider in ('deepseek', 'openai', 'openai_structured', 'anthropic', 'gemini', 'together') and not llm_key:
        issues.append('缺少 MEM0_LLM_API_KEY 或 STORY_LLM_API_KEY')

    embedder_provider = _config('MEM0_EMBEDDER_PROVIDER', 'fastembed')
    embedder_key = _config('MEM0_EMBEDDER_API_KEY', '') or _config('OPENAI_API_KEY', '')
    if embedder_provider in ('openai', 'azure_openai', 'gemini', 'together') and not embedder_key:
        issues.append('缺少 MEM0_EMBEDDER_API_KEY；DeepSeek 不提供 embedding，需要单独配置向量模型 key')
    if embedder_provider == 'fastembed':
        if importlib_util.find_spec('fastembed') is None:
            issues.append('未安装 fastembed，请执行 pip install -r requirements.txt')
        else:
            details.append(f"FastEmbed：{_config('MEM0_EMBEDDER_MODEL', 'BAAI/bge-small-zh-v1.5')}")

    if _config('MEM0_VECTOR_PROVIDER', 'qdrant') == 'qdrant':
        qdrant_path = _config('MEM0_QDRANT_PATH', '')
        qdrant_url = _config('MEM0_QDRANT_URL', '')
        if qdrant_path:
            details.append(f"Qdrant 本地路径：{qdrant_path}")
        else:
            endpoint = qdrant_url or f"http://{_config('MEM0_QDRANT_HOST', '127.0.0.1')}:{_config_int('MEM0_QDRANT_PORT', 6333)}"
            details.append(f"Qdrant：{endpoint}")
            if check_connection:
                _check_qdrant(endpoint, issues)


def _append_rest_health(issues, details, check_connection):
    url = str(_config('MEM0_API_URL', '') or '').strip().rstrip('/')
    if not url:
        issues.append('缺少 MEM0_API_URL')
        return
    details.append(f"Mem0 REST：{url}")
    if check_connection:
        try:
            resp = requests.get(f'{url}/health', timeout=min(_config_int('MEM0_TIMEOUT', 12), 5))
            if resp.status_code == 404:
                resp = requests.get(url, timeout=min(_config_int('MEM0_TIMEOUT', 12), 5))
            if resp.status_code >= 400:
                issues.append(f'Mem0 REST 探测失败：HTTP {resp.status_code}')
        except Exception as exc:
            issues.append(f'Mem0 REST 无法连接：{exc}')


def _check_qdrant(endpoint, issues):
    headers = {}
    api_key = _config('MEM0_QDRANT_API_KEY', '')
    if api_key:
        headers['api-key'] = api_key
    try:
        resp = requests.get(f"{str(endpoint).rstrip('/')}/collections", headers=headers, timeout=3)
        if resp.status_code >= 400:
            issues.append(f'Qdrant 探测失败：HTTP {resp.status_code}')
    except Exception as exc:
        issues.append(f'Qdrant 无法连接：{exc}')


def _default_embedding_dims(provider, model):
    provider = str(provider or '').strip().lower()
    model = str(model or '').strip()
    if provider == 'fastembed':
        return {
            'BAAI/bge-small-zh-v1.5': 512,
            'jinaai/jina-embeddings-v2-base-zh': 768,
            'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2': 384,
            'sentence-transformers/paraphrase-multilingual-mpnet-base-v2': 768,
            'intfloat/multilingual-e5-large': 1024,
            'jinaai/jina-embeddings-v3': 1024,
            'thenlper/gte-large': 1024,
        }.get(model, 512)
    return 0


def _extract_memory_texts(data, limit):
    if isinstance(data, dict):
        items = data.get('results') or data.get('memories') or data.get('data') or []
    else:
        items = data or []
    texts = []
    for item in items:
        if isinstance(item, dict):
            text = item.get('memory') or item.get('text') or item.get('content')
        else:
            text = str(item)
        text = str(text or '').strip()
        if text:
            texts.append(text)
        if len(texts) >= limit:
            break
    return texts


def _normalize_deepseek_model(model):
    model = str(model or '').strip()
    if model in ('deepseek-ai/DeepSeek-V4-Flash', 'DeepSeek-V4-Flash', 'deepseek-chat', ''):
        return 'deepseek-v4-flash'
    return model


def _api_base(url):
    url = str(url or '').strip().rstrip('/')
    for suffix in ('/chat/completions', '/embeddings'):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
    if url.endswith('/v1'):
        return url
    return url


def _config(name, default=''):
    if has_app_context() and name in current_app.config:
        return current_app.config.get(name, default)
    import os
    return os.environ.get(name, default)


def _config_bool(name, default=False):
    value = _config(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _config_int(name, default=0):
    try:
        return int(_config(name, default))
    except (TypeError, ValueError):
        return int(default)


def _config_float(name, default=0.0):
    try:
        return float(_config(name, default))
    except (TypeError, ValueError):
        return float(default)


def _log_warning(message, *args):
    if has_app_context():
        current_app.logger.warning(message, *args)
