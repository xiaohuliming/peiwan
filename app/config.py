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
