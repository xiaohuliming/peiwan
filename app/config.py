import os
import urllib.parse
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _init_ssl_ca_env():
    """
    在应用进程内兜底 CA 证书路径，避免部署环境未注入变量导致 aiohttp 验证失败。
    """
    ca_candidates = [
        os.environ.get('SSL_CERT_FILE'),
        os.environ.get('REQUESTS_CA_BUNDLE'),
        '/etc/ssl/certs/ca-certificates.crt',   # Debian/Ubuntu
        '/etc/pki/tls/certs/ca-bundle.crt',     # CentOS/RHEL
        '/etc/ssl/cert.pem',                    # macOS / 部分发行版
    ]
    ca_file = next((p for p in ca_candidates if p and os.path.exists(p)), None)

    if ca_file:
        os.environ.setdefault('SSL_CERT_FILE', ca_file)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', ca_file)
        os.environ.setdefault('CURL_CA_BUNDLE', ca_file)

    if os.path.isdir('/etc/ssl/certs'):
        os.environ.setdefault('SSL_CERT_DIR', '/etc/ssl/certs')


_init_ssl_ca_env()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    
    # Encode password to handle special characters
    password = urllib.parse.quote_plus('Ppm@050820')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'mysql+pymysql://root:{password}@localhost:3306/peiwan_admin'
        
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # KOOK Bot Configuration
    KOOK_TOKEN = os.environ.get('KOOK_TOKEN') or 'your-kook-bot-token'
    KOOK_BOT_ENABLED = os.environ.get('KOOK_BOT_ENABLED', 'false').lower() == 'true'

    # Site URL (用于生成 KOOK 消息中的跳转链接)
    PUBLIC_SITE_URL = os.environ.get('PUBLIC_SITE_URL', 'https://www.ennb.xin')
    SITE_URL = os.environ.get('SITE_URL', PUBLIC_SITE_URL)

    # KOOK AI 剧情游戏 LLM 配置（OpenAI-compatible Chat Completions）
    STORY_LLM_MODEL = os.environ.get('STORY_LLM_MODEL', 'deepseek-ai/DeepSeek-V4-Flash')
    STORY_LLM_API_URL = os.environ.get('STORY_LLM_API_URL', 'https://api.siliconflow.cn/v1/chat/completions')
    STORY_LLM_API_KEY = os.environ.get('STORY_LLM_API_KEY', '')
    STORY_LLM_TIMEOUT = int(os.environ.get('STORY_LLM_TIMEOUT', '45'))
    STORY_LLM_MAX_TOKENS = int(os.environ.get('STORY_LLM_MAX_TOKENS', '3500'))
    STORY_LLM_MIN_VISIBLE_CHARS = int(os.environ.get('STORY_LLM_MIN_VISIBLE_CHARS', '240'))
    STORY_DM_MIN_VISIBLE_CHARS = int(os.environ.get('STORY_DM_MIN_VISIBLE_CHARS', '8'))
    STORY_VISIBLE_MAX_CHARS = int(os.environ.get('STORY_VISIBLE_MAX_CHARS', '3200'))
    STORY_HISTORY_MAX_TURNS = int(os.environ.get('STORY_HISTORY_MAX_TURNS', '300'))
    STORY_HISTORY_MAX_CHARS = int(os.environ.get('STORY_HISTORY_MAX_CHARS', '600000'))
    STORY_LORE_MAX_CHARS = int(os.environ.get('STORY_LORE_MAX_CHARS', '9000'))
    STORY_LANGGRAPH_ENABLED = os.environ.get('STORY_LANGGRAPH_ENABLED', 'true').lower() == 'true'
    STORY_MEMORY_ENABLED = os.environ.get('STORY_MEMORY_ENABLED', 'false').lower() == 'true'
    STORY_MEMORY_BACKEND = os.environ.get('STORY_MEMORY_BACKEND', 'mem0_sdk')
    STORY_MEMORY_LIMIT = int(os.environ.get('STORY_MEMORY_LIMIT', '8'))
    STORY_MEMORY_MAX_CHARS = int(os.environ.get('STORY_MEMORY_MAX_CHARS', '2400'))

    # mem0 长期记忆配置。默认关闭；启用后可用 SDK 或独立 REST 服务。
    MEM0_API_URL = os.environ.get('MEM0_API_URL', 'http://127.0.0.1:8888')
    MEM0_API_KEY = os.environ.get('MEM0_API_KEY', '')
    MEM0_TIMEOUT = int(os.environ.get('MEM0_TIMEOUT', '12'))
    MEM0_LLM_PROVIDER = os.environ.get('MEM0_LLM_PROVIDER', 'deepseek')
    MEM0_LLM_MODEL = os.environ.get('MEM0_LLM_MODEL', STORY_LLM_MODEL)
    MEM0_LLM_API_KEY = os.environ.get('MEM0_LLM_API_KEY', STORY_LLM_API_KEY)
    MEM0_LLM_BASE_URL = os.environ.get('MEM0_LLM_BASE_URL', STORY_LLM_API_URL)
    MEM0_LLM_TEMPERATURE = float(os.environ.get('MEM0_LLM_TEMPERATURE', '0.1'))
    MEM0_LLM_MAX_TOKENS = int(os.environ.get('MEM0_LLM_MAX_TOKENS', '1200'))
    MEM0_EMBEDDER_PROVIDER = os.environ.get('MEM0_EMBEDDER_PROVIDER', 'fastembed')
    MEM0_EMBEDDER_MODEL = os.environ.get('MEM0_EMBEDDER_MODEL', 'BAAI/bge-small-zh-v1.5' if MEM0_EMBEDDER_PROVIDER == 'fastembed' else 'text-embedding-3-small')
    MEM0_EMBEDDER_API_KEY = os.environ.get('MEM0_EMBEDDER_API_KEY', os.environ.get('OPENAI_API_KEY', ''))
    MEM0_EMBEDDER_BASE_URL = os.environ.get('MEM0_EMBEDDER_BASE_URL', os.environ.get('OPENAI_BASE_URL', ''))
    MEM0_EMBEDDER_DIMS = int(os.environ.get('MEM0_EMBEDDER_DIMS', '512' if MEM0_EMBEDDER_PROVIDER == 'fastembed' else '0'))
    MEM0_VECTOR_PROVIDER = os.environ.get('MEM0_VECTOR_PROVIDER', 'qdrant')
    MEM0_COLLECTION_NAME = os.environ.get('MEM0_COLLECTION_NAME', 'kook_story_memories')
    MEM0_HISTORY_DB_PATH = os.environ.get('MEM0_HISTORY_DB_PATH', '')
    MEM0_QDRANT_URL = os.environ.get('MEM0_QDRANT_URL', '')
    MEM0_QDRANT_API_KEY = os.environ.get('MEM0_QDRANT_API_KEY', '')
    MEM0_QDRANT_HOST = os.environ.get('MEM0_QDRANT_HOST', '127.0.0.1')
    MEM0_QDRANT_PORT = int(os.environ.get('MEM0_QDRANT_PORT', '6333'))
    MEM0_QDRANT_PATH = os.environ.get('MEM0_QDRANT_PATH', '')
    MEM0_QDRANT_ON_DISK = os.environ.get('MEM0_QDRANT_ON_DISK', 'false').lower() == 'true'

    # WeChat OAuth (网页扫码登录/注册)
    WECHAT_APP_ID = os.environ.get('WECHAT_APP_ID', '')
    WECHAT_APP_SECRET = os.environ.get('WECHAT_APP_SECRET', '')
    WECHAT_OAUTH_SCOPE = os.environ.get('WECHAT_OAUTH_SCOPE', 'snsapi_login')
    # 建议在微信开放平台配置后显式写死此回调，避免反向代理域名差异
    WECHAT_OAUTH_REDIRECT_URI = os.environ.get('WECHAT_OAUTH_REDIRECT_URI', '')
    WECHAT_OAUTH_AUTHORIZE_URL = os.environ.get(
        'WECHAT_OAUTH_AUTHORIZE_URL',
        'https://open.weixin.qq.com/connect/qrconnect'
    )

    # SSL CA 证书配置（给 requests/aiohttp/khl 统一复用）
    SSL_CERT_FILE = os.environ.get('SSL_CERT_FILE')
    REQUESTS_CA_BUNDLE = os.environ.get('REQUESTS_CA_BUNDLE')
    SSL_CERT_DIR = os.environ.get('SSL_CERT_DIR')

    # Upload Configuration
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max-limit
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Login/Session: 超长登录态（近似永久）
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=3650)  # 10 years
    REMEMBER_COOKIE_DURATION = timedelta(days=3650)    # 10 years
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = True
