import copy
import os
import shutil
import threading
import time
import tomllib
from typing import Any, Dict, List

from reg_gpt.cfmail_pool import normalize_cfmail_accounts, normalize_host

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_ROOT = os.path.join(SCRIPT_DIR, 'runtime')
LOG_DIR = os.path.join(RUNTIME_ROOT, 'logs')
STATE_DIR = os.path.join(RUNTIME_ROOT, 'state')
DATA_DIR = os.path.join(RUNTIME_ROOT, 'data')
TOKEN_DIR = os.path.join(DATA_DIR, 'Token-OpenAi')


def _resolve_config_path() -> str:
    """按优先级查找配置文件位置：项目根目录 > backend 同级 > runtime/config/"""
    # 本地开发：根目录 reg_config.toml（SCRIPT_DIR = backend/，上一级 = 项目根）
    project_root = os.path.dirname(SCRIPT_DIR)
    candidate = os.path.join(project_root, 'reg_config.toml')
    if os.path.isfile(candidate):
        return candidate
    # Docker / 旧布局：SCRIPT_DIR 下直接放
    candidate = os.path.join(SCRIPT_DIR, 'reg_config.toml')
    if os.path.isfile(candidate):
        return candidate
    # runtime/config/ 下
    candidate = os.path.join(RUNTIME_ROOT, 'config', 'reg_config.toml')
    if os.path.isfile(candidate):
        return candidate
    # 默认：写到项目根目录
    return os.path.join(project_root, 'reg_config.toml')


CONFIG_PATH = _resolve_config_path()
CONFIG_DIR = os.path.dirname(CONFIG_PATH)
RUNTIME_LOG_PATH = os.path.join(LOG_DIR, 'runtime.log')

LEGACY_CONFIG_PATH = os.path.join(SCRIPT_DIR, 'reg_config.toml')
LEGACY_LOG_PATH = os.path.join(SCRIPT_DIR, 'runtime.log')
LEGACY_RUNTIME_STATE_PATH = os.path.join(SCRIPT_DIR, 'runtime_state.json')
LEGACY_CPA_STATE_PATH = os.path.join(SCRIPT_DIR, 'cpa_state.json')
LEGACY_TOKEN_DIR = os.path.join(SCRIPT_DIR, 'Token-OpenAi')

_DEFAULT_TRUSTED_ORIGINS = ['http://127.0.0.1:5050', 'http://localhost:5050']
_PROVIDER_ORDER = ['mailapi_pool', 'cfmail', 'cloudflare', 'duckmail', 'tempmail_lol', 'lamail']
_PROVIDERS_WITH_ENTRIES = {'mailapi_pool', 'cloudflare', 'duckmail', 'tempmail_lol', 'lamail'}
_DEFAULT_MAILAPI_POOL_DOMAINS = [
    '*.icoa.qzz.io',
    '*.icoe.pp.ua',
    '*.icoa.pp.ua',
    '*.uoou.cc.cd',
    '*.icoa.ccwu.cc',
    '*.icoa.us.ci',
    'icoa.vex.mom',
    'icoa.zle.ee',
    'icoamail.sylu.net',
    'chat-ui.webn.cc',
    'codex.vision.moe',
    '*.ice.qq11.top',
    '*.myanglealtman.tech',
    '*.ice.lyzswx.eu.org',
    'a.i00.de5.net',
    '*.ice.aoko.cc.cd',
    '*.ice.aoko.eu.cc',
    '*.ice.chaldea.eu.cc',
    '*.ice.mssk.eu.cc',
    '*.ice.mssk.qzz.io',
    '*.linux.archerguo.de5.net',
    '*.linux.airforceone.online',
    '*.ice.kitakamis.online',
    '*.ice.0987134.xyz',
    '*.ice.icecodex.us.ci',
    '*.ice.icecodex.ccwu.cc',
    '*.ice.oo.oogoo.top',
    '*.ice.jiayou0328.ccwu.cc',
    '*.ice.jiayou0328.us.ci',
    'icoa.raw.mom',
    'icoa.raw.best',
    '*.icecream.707979.xyz',
    '*.ice.help.itbasee.top',
    '*.ice.863973.dpdns.org',
    '*.ice.tinytiger.top',
    '*.ice.yucici.qzz.io',
    '*.love.biaozi.de5.net',
    '*.love.dogge.de5.net',
    '*.love.mobil.dpdns.org',
    '*.love.vercel.dpdns.org',
    '*.love.google.nyc.mn',
]
_DEFAULT_MAILAPI_POOL_API_BASES = [
    'https://mailapizv.uton.me',
]

DEFAULT_CONFIG_TOML = """\
# ============================================================
#  Reg-GPT 统一配置文件
#  主程序运行、WebUI 与安全配置统一保存在这里
# ============================================================

[email]
selection_mode = "random_enabled"

[email.otp]
wait_timeout_seconds = 120
retry_wait_timeout_seconds = 60

[email.weight]
default_score = 100
min_score = 20
max_score = 200
success_delta = 8
failure_delta = 20

[email.providers.cfmail]
enabled = false
type = "cfmail"
label = "CFMail 账号池"
profile = "auto"
fail_threshold = 3
cooldown_seconds = 1800

[email.providers.cloudflare]
enabled = false
type = "cloudflare"
label = "Cloudflare 邮箱"
worker_url = ""
email_domain = ""
api_secret = ""

[email.providers.duckmail]
enabled = false
type = "duckmail"
label = "DuckMail"
api_base = "https://api.duckmail.sbs"
bearer = ""
email_domain = "duckmail.sbs"

[email.providers.tempmail_lol]
enabled = false
type = "tempmail_lol"
label = "TempMail.lol"
api_base = "https://api.tempmail.lol/v2"
api_key = ""
domain = ""

[email.providers.lamail]
enabled = false
type = "lamail"
label = "LaMail"
api_base = "https://maliapi.215.im/v1"
api_key = ""
domain = ""

[network]
enabled = true
proxy = "http://127.0.0.1:7890"

[cpa]
enabled = false
management_url = ""
management_token = ""
upload_proxy_mode = "default"
custom_proxy = ""
timeout = 15
active_probe = true
probe_timeout = 8
probe_workers = 12
delete_workers = 8
max_active_probes = 120
auto_sync_on_success = true
health_probe_mode = "auto"

[codex_proxy]
enabled = false
base_url = ""
admin_key = ""
upload_proxy_url = ""
auto_sync_on_success = true
timeout = 15

[run]
sleep_min = 5
sleep_max = 30
max_success = 0
workers = 1
once = false

[webui]
host = "127.0.0.1"
port = 5050

[oauth]
enabled = true
host = "127.0.0.1"
port = 1455
timeout = 300
mock = false

[security]
username = "admin"
password_hash = ""
api_token = ""
session_secret = ""
session_minutes = 480
secure_cookie = false
login_rate_limit = 8
login_window_seconds = 900
csrf_enabled = true
trusted_origins = ["http://127.0.0.1:5050", "http://localhost:5050"]
"""

_config_lock = threading.Lock()
_config_cache_lock = threading.Lock()
_config_cache: Dict[str, Any] | None = None
_config_cache_mtime_ns: int | None = None
_CONFIG_PERSIST_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.35, 0.5)


def ensure_runtime_layout() -> None:
    for path in (RUNTIME_ROOT, CONFIG_DIR, LOG_DIR, STATE_DIR, DATA_DIR, TOKEN_DIR):
        os.makedirs(path, exist_ok=True)


def _copy_legacy_file_if_missing(legacy_path: str, target_path: str) -> bool:
    if not legacy_path or not target_path:
        return False
    if os.path.exists(target_path) or not os.path.isfile(legacy_path):
        return False
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    shutil.copy2(legacy_path, target_path)
    return True


def _copy_legacy_tree_if_needed(legacy_path: str, target_path: str) -> bool:
    if not legacy_path or not target_path:
        return False
    if not os.path.isdir(legacy_path):
        return False
    os.makedirs(target_path, exist_ok=True)
    if os.listdir(target_path):
        return False
    for name in os.listdir(legacy_path):
        src = os.path.join(legacy_path, name)
        dst = os.path.join(target_path, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    return True


def _safe_int(value: Any, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _normalize_domain_pattern(value: Any) -> str:
    text = normalize_host(value).lower()
    if not text:
        return ''
    wildcard = text.startswith('*.')
    if wildcard:
        text = text[2:]
    text = text.strip('.')
    if not text or '.' not in text:
        return ''
    return f'*.{text}' if wildcard else text


def _normalize_domain_patterns(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    items: List[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _normalize_domain_pattern(raw)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _normalize_api_base(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    if not (text.startswith('https://') or text.startswith('http://')):
        text = f'https://{text.lstrip("/")}'
    return text.rstrip('/')


def _normalize_api_bases(values: Any) -> List[str]:
    if isinstance(values, str):
        values = [item.strip() for item in values.replace(',', '\n').splitlines() if item.strip()]
    if not isinstance(values, list):
        return []
    items: List[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _normalize_api_base(raw)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _quote_toml(value: str) -> str:
    escaped = (value or '').replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def _quote_toml_list(values: List[str]) -> str:
    return '[' + ', '.join(_quote_toml(v) for v in values) + ']'


def _normalize_choice(value: Any, default: str, allowed: set[str]) -> str:
    text = str(value or '').strip().lower()
    if not text:
        return default
    return text if text in allowed else default


def _safe_string(value: Any, default: str = '') -> str:
    return str(value or default or '').strip()


def _ensure_config_file() -> None:
    ensure_runtime_layout()
    _copy_legacy_file_if_missing(LEGACY_CONFIG_PATH, CONFIG_PATH)
    if os.path.exists(CONFIG_PATH):
        return
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(dump_config_toml(normalize_config({})))


def _is_retryable_config_io_error(exc: Exception) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, 'winerror', None)
    return winerror == 5


def _write_config_direct(content: str) -> None:
    with open(CONFIG_PATH, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())


def _read_config_file() -> Dict[str, Any]:
    _ensure_config_file()
    with open(CONFIG_PATH, 'rb') as fh:
        return tomllib.load(fh)


def _update_cache(data: Dict[str, Any]) -> None:
    global _config_cache, _config_cache_mtime_ns
    try:
        stat = os.stat(CONFIG_PATH)
        mtime_ns = stat.st_mtime_ns
    except OSError:
        mtime_ns = None
    with _config_cache_lock:
        _config_cache = copy.deepcopy(data)
        _config_cache_mtime_ns = mtime_ns


def load_or_create_config(force_reload: bool = False) -> Dict[str, Any]:
    _ensure_config_file()
    try:
        stat = os.stat(CONFIG_PATH)
        mtime_ns = stat.st_mtime_ns
    except OSError:
        mtime_ns = None

    with _config_cache_lock:
        if not force_reload and _config_cache is not None and _config_cache_mtime_ns == mtime_ns:
            return copy.deepcopy(_config_cache)

    data = _read_config_file()
    _update_cache(data)
    return copy.deepcopy(data)


def _default_provider_block(name: str) -> Dict[str, Any]:
    defaults: Dict[str, Dict[str, Any]] = {
        'mailapi_pool': {
            'enabled': True,
            'type': 'mailapi_pool',
            'label': '域名池邮箱',
            'api_base': 'https://mailapizv.uton.me',
            'api_bases': list(_DEFAULT_MAILAPI_POOL_API_BASES),
            'api_key': 'linuxdo',
            'domains': list(_DEFAULT_MAILAPI_POOL_DOMAINS),
            'entries': [],
        },
        'cfmail': {
            'enabled': False,
            'type': 'cfmail',
            'label': 'CFMail 账号池',
            'profile': 'auto',
            'fail_threshold': 3,
            'cooldown_seconds': 1800,
            'accounts': [],
        },
        'cloudflare': {
            'enabled': False,
            'type': 'cloudflare',
            'label': 'Cloudflare 邮箱',
            'worker_url': '',
            'email_domain': '',
            'api_secret': '',
            'entries': [],
        },
        'duckmail': {
            'enabled': False,
            'type': 'duckmail',
            'label': 'DuckMail',
            'api_base': 'https://api.duckmail.sbs',
            'bearer': '',
            'email_domain': 'duckmail.sbs',
            'entries': [],
        },
        'tempmail_lol': {
            'enabled': False,
            'type': 'tempmail_lol',
            'label': 'TempMail.lol',
            'api_base': 'https://api.tempmail.lol/v2',
            'api_key': '',
            'domain': '',
            'entries': [],
        },
        'lamail': {
            'enabled': False,
            'type': 'lamail',
            'label': 'LaMail',
            'api_base': 'https://maliapi.215.im/v1',
            'api_key': '',
            'domain': '',
            'entries': [],
        },
    }
    return copy.deepcopy(defaults.get(name, {'enabled': False, 'type': name, 'label': f'{name} 邮箱'}))


def _legacy_provider_has_value(provider_type: str, raw: Dict[str, Any]) -> bool:
    if provider_type == 'mailapi_pool':
        return any(
            raw.get(key)
            for key in ('api_base', 'api_bases', 'api_key', 'domains', 'enabled_email_domains', 'mail_domain_options', 'mail_api_url', 'mail_api_urls')
        )
    if provider_type == 'cloudflare':
        return any(raw.get(key) for key in ('worker_url', 'email_domain', 'api_secret'))
    if provider_type == 'duckmail':
        return any(raw.get(key) for key in ('api_base', 'bearer', 'email_domain'))
    if provider_type == 'tempmail_lol':
        return bool(raw.get('api_base'))
    if provider_type == 'lamail':
        return any(raw.get(key) for key in ('api_base', 'api_key', 'domain'))
    return False


def _normalize_email_entry(provider_type: str, raw: Dict[str, Any] | None, defaults: Dict[str, Any], index: int) -> Dict[str, Any]:
    data = raw or {}
    label_default = str(defaults.get('label') or f'条目 {index + 1}').strip() or f'条目 {index + 1}'
    normalized: Dict[str, Any] = {
        'enabled': _safe_bool(data.get('enabled', defaults.get('enabled', False)), bool(defaults.get('enabled', False))),
        'label': _safe_string(data.get('label'), label_default) or label_default,
    }

    if provider_type == 'mailapi_pool':
        domains = data.get('domains')
        if not isinstance(domains, list):
            domains = data.get('enabled_email_domains')
        if not isinstance(domains, list):
            domains = data.get('mail_domain_options')
        api_bases_raw = data.get('api_bases')
        if api_bases_raw is None:
            api_bases_raw = data.get('mail_api_urls')
        api_base = _normalize_api_base(data.get('api_base') or data.get('mail_api_url') or defaults.get('api_base') or '')
        default_api_bases = [] if (data.get('api_base') or data.get('mail_api_url')) else (defaults.get('api_bases') or [])
        api_bases = _normalize_api_bases(api_bases_raw or default_api_bases)
        if not api_base and api_bases:
            api_base = api_bases[0]
        if not api_bases and api_base:
            api_bases = [api_base]
        normalized['api_base'] = api_base
        normalized['api_bases'] = api_bases
        normalized['api_key'] = _safe_string(data.get('api_key') or data.get('mail_api_key') or defaults.get('api_key'))
        normalized['domains'] = _normalize_domain_patterns(domains or defaults.get('domains') or [])
        return normalized

    if provider_type == 'cloudflare':
        normalized['worker_url'] = _safe_string(data.get('worker_url') or defaults.get('worker_url'))
        normalized['email_domain'] = normalize_host(data.get('email_domain') or defaults.get('email_domain') or '')
        normalized['api_secret'] = _safe_string(data.get('api_secret') or defaults.get('api_secret'))
        return normalized

    if provider_type == 'duckmail':
        normalized['api_base'] = _safe_string(data.get('api_base') or defaults.get('api_base') or 'https://api.duckmail.sbs').rstrip('/')
        normalized['bearer'] = _safe_string(data.get('bearer') or defaults.get('bearer'))
        normalized['email_domain'] = normalize_host(data.get('email_domain') or defaults.get('email_domain') or 'duckmail.sbs') or 'duckmail.sbs'
        return normalized

    if provider_type == 'tempmail_lol':
        normalized['api_base'] = _safe_string(data.get('api_base') or defaults.get('api_base') or 'https://api.tempmail.lol/v2').rstrip('/')
        normalized['api_key'] = _safe_string(data.get('api_key') or defaults.get('api_key'))
        normalized['domain'] = _safe_string(data.get('domain') or defaults.get('domain'))
        return normalized

    if provider_type == 'lamail':
        normalized['api_base'] = _safe_string(data.get('api_base') or defaults.get('api_base') or 'https://maliapi.215.im/v1').rstrip('/')
        normalized['api_key'] = _safe_string(data.get('api_key') or defaults.get('api_key'))
        normalized['domain'] = normalize_host(data.get('domain') or defaults.get('domain') or '')
        return normalized

    return normalized


def _default_entries_for_provider(provider_type: str, defaults: Dict[str, Any]) -> List[Dict[str, Any]]:
    if provider_type != 'mailapi_pool':
        return []
    return [_normalize_email_entry(provider_type, defaults, defaults, 0)]


def _entries_from_legacy_provider(provider_type: str, raw: Dict[str, Any], defaults: Dict[str, Any]) -> List[Dict[str, Any]]:
    if _legacy_provider_has_value(provider_type, raw):
        return [_normalize_email_entry(provider_type, raw, defaults, 0)]
    return _default_entries_for_provider(provider_type, defaults)


def _derive_provider_fields_from_entry(provider_type: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    if provider_type == 'mailapi_pool':
        return {
            'api_base': _safe_string(entry.get('api_base')),
            'api_bases': list(entry.get('api_bases') or []),
            'api_key': _safe_string(entry.get('api_key')),
            'domains': list(entry.get('domains') or []),
        }
    if provider_type == 'cloudflare':
        return {
            'worker_url': _safe_string(entry.get('worker_url')),
            'email_domain': _safe_string(entry.get('email_domain')),
            'api_secret': _safe_string(entry.get('api_secret')),
        }
    if provider_type == 'duckmail':
        return {
            'api_base': _safe_string(entry.get('api_base')),
            'bearer': _safe_string(entry.get('bearer')),
            'email_domain': _safe_string(entry.get('email_domain')),
        }
    if provider_type == 'tempmail_lol':
        return {
            'api_base': _safe_string(entry.get('api_base')),
            'api_key': _safe_string(entry.get('api_key')),
            'domain': _safe_string(entry.get('domain')),
        }
    if provider_type == 'lamail':
        return {
            'api_base': _safe_string(entry.get('api_base')),
            'api_key': _safe_string(entry.get('api_key')),
            'domain': _safe_string(entry.get('domain')),
        }
    return {}


def _normalize_email_provider(name: str, data: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = data or {}
    defaults = _default_provider_block(name)
    provider_type = str(raw.get('type') or defaults.get('type') or name).strip().lower() or name
    normalized: Dict[str, Any] = {
        'enabled': _safe_bool(raw.get('enabled', defaults.get('enabled', False)), bool(defaults.get('enabled', False))),
        'type': provider_type,
        'label': str(raw.get('label') or defaults.get('label') or f'{name} 邮箱').strip() or f'{name} 邮箱',
    }

    if provider_type == 'cfmail':
        normalized['profile'] = str(raw.get('profile') or raw.get('cfmail_profile') or defaults.get('profile') or 'auto').strip() or 'auto'
        normalized['fail_threshold'] = _safe_int(raw.get('fail_threshold', defaults.get('fail_threshold', 3)), 3, 1)
        normalized['cooldown_seconds'] = _safe_int(raw.get('cooldown_seconds', defaults.get('cooldown_seconds', 1800)), 1800, 0)
        normalized['accounts'] = normalize_cfmail_accounts(raw.get('accounts') or defaults.get('accounts') or [])
        return normalized

    if provider_type in _PROVIDERS_WITH_ENTRIES:
        raw_entries = raw.get('entries')
        entries: List[Dict[str, Any]] = []
        if isinstance(raw_entries, list):
            for idx, item in enumerate(raw_entries):
                if not isinstance(item, dict):
                    continue
                entries.append(_normalize_email_entry(provider_type, item, defaults, idx))
        if not entries:
            entries = _entries_from_legacy_provider(provider_type, raw, defaults)

        normalized['entries'] = entries
        if entries:
            normalized.update(_derive_provider_fields_from_entry(provider_type, entries[0]))
        else:
            normalized.update(_derive_provider_fields_from_entry(provider_type, _normalize_email_entry(provider_type, {}, defaults, 0)))
        return normalized

    return normalized


def normalize_config(data: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = data or {}
    raw_email_cfg = raw.get('email') if isinstance(raw.get('email'), dict) else {}
    raw_email_providers = raw_email_cfg.get('providers') if isinstance(raw_email_cfg.get('providers'), dict) else {}
    otp_cfg = raw_email_cfg.get('otp') if isinstance(raw_email_cfg.get('otp'), dict) else {}
    weight_cfg = raw_email_cfg.get('weight') if isinstance(raw_email_cfg.get('weight'), dict) else {}
    legacy_cf_cfg = raw.get('cloudflare') if isinstance(raw.get('cloudflare'), dict) else {}
    net_cfg = raw.get('network') if isinstance(raw.get('network'), dict) else {}
    cpa_cfg = raw.get('cpa') if isinstance(raw.get('cpa'), dict) else {}
    cp_cfg = raw.get('codex_proxy') if isinstance(raw.get('codex_proxy'), dict) else {}
    run_cfg = raw.get('run') if isinstance(raw.get('run'), dict) else {}
    webui_cfg = raw.get('webui') if isinstance(raw.get('webui'), dict) else raw.get('server') if isinstance(raw.get('server'), dict) else {}
    oauth_cfg = raw.get('oauth') if isinstance(raw.get('oauth'), dict) else {}
    sec_cfg = raw.get('security') if isinstance(raw.get('security'), dict) else {}

    sleep_min = _safe_int(run_cfg.get('sleep_min'), 5, 1)
    sleep_max = _safe_int(run_cfg.get('sleep_max'), 30, sleep_min)
    min_weight_score = _safe_int(weight_cfg.get('min_score'), 20, 1)
    max_weight_score = _safe_int(weight_cfg.get('max_score'), 200, min_weight_score)
    default_weight_score = _safe_int(weight_cfg.get('default_score'), 100, min_weight_score)
    default_weight_score = min(max_weight_score, default_weight_score)

    trusted_origins = sec_cfg.get('trusted_origins')
    if isinstance(trusted_origins, str):
        trusted_origins = [line.strip() for line in trusted_origins.splitlines() if line.strip()]
    elif not isinstance(trusted_origins, list):
        trusted_origins = list(_DEFAULT_TRUSTED_ORIGINS)

    providers: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_email_providers, dict):
        for provider_name, provider_data in raw_email_providers.items():
            providers[str(provider_name)] = _normalize_email_provider(str(provider_name), provider_data or {})

    if 'cloudflare' in providers:
        merged_cf = dict(legacy_cf_cfg)
        merged_cf.update(providers['cloudflare'])
        providers['cloudflare'] = _normalize_email_provider('cloudflare', merged_cf)
    else:
        providers['cloudflare'] = _normalize_email_provider('cloudflare', legacy_cf_cfg)

    for provider_name in _PROVIDER_ORDER:
        if provider_name not in providers:
            providers[provider_name] = _normalize_email_provider(provider_name, {})

    return {
        'email': {
            'selection_mode': str(raw_email_cfg.get('selection_mode') or 'first_enabled').strip() or 'first_enabled',
            'otp': {
                'wait_timeout_seconds': _safe_int(otp_cfg.get('wait_timeout_seconds'), 120, 10),
                'retry_wait_timeout_seconds': _safe_int(otp_cfg.get('retry_wait_timeout_seconds'), 60, 10),
            },
            'weight': {
                'default_score': default_weight_score,
                'min_score': min_weight_score,
                'max_score': max_weight_score,
                'success_delta': _safe_int(weight_cfg.get('success_delta'), 8, 1),
                'failure_delta': _safe_int(weight_cfg.get('failure_delta'), 20, 1),
            },
            'providers': providers,
        },
        'network': {
            'enabled': _safe_bool(net_cfg.get('enabled', True), True),
            'proxy': str(net_cfg.get('proxy') or '').strip(),
        },
        'cpa': {
            'enabled': _safe_bool(cpa_cfg.get('enabled', False), False),
            'management_url': str(cpa_cfg.get('management_url') or '').strip(),
            'management_token': str(cpa_cfg.get('management_token') or '').strip(),
            'upload_proxy_mode': _normalize_choice(cpa_cfg.get('upload_proxy_mode'), 'default', {'default', 'direct', 'custom'}),
            'custom_proxy': str(cpa_cfg.get('custom_proxy') or '').strip(),
            'timeout': _safe_int(cpa_cfg.get('timeout'), 15, 1),
            'active_probe': _safe_bool(cpa_cfg.get('active_probe', True), True),
            'probe_timeout': _safe_int(cpa_cfg.get('probe_timeout'), 8, 1),
            'probe_workers': _safe_int(cpa_cfg.get('probe_workers'), 12, 1),
            'delete_workers': _safe_int(cpa_cfg.get('delete_workers'), 8, 1),
            'max_active_probes': _safe_int(cpa_cfg.get('max_active_probes'), 120, 0),
            'auto_sync_on_success': _safe_bool(cpa_cfg.get('auto_sync_on_success', True), True),
            'health_probe_mode': _normalize_choice(cpa_cfg.get('health_probe_mode'), 'auto', {'auto', 'openai', 'codex'}),
        },
        'codex_proxy': {
            'enabled': _safe_bool(cp_cfg.get('enabled', False), False),
            'base_url': str(cp_cfg.get('base_url') or '').strip(),
            'admin_key': str(cp_cfg.get('admin_key') or '').strip(),
            'upload_proxy_url': str(cp_cfg.get('upload_proxy_url') or '').strip(),
            'auto_sync_on_success': _safe_bool(cp_cfg.get('auto_sync_on_success', True), True),
            'timeout': _safe_int(cp_cfg.get('timeout'), 15, 1),
        },
        'run': {
            'sleep_min': sleep_min,
            'sleep_max': sleep_max,
            'max_success': _safe_int(run_cfg.get('max_success'), 0, 0),
            'workers': _safe_int(run_cfg.get('workers'), 1, 1),
            'once': _safe_bool(run_cfg.get('once', False), False),
        },
        'webui': {
            'host': str(webui_cfg.get('host') or '127.0.0.1').strip() or '127.0.0.1',
            'port': _safe_int(webui_cfg.get('port'), 5050, 1),
        },
        'oauth': {
            'enabled': _safe_bool(oauth_cfg.get('enabled', True), True),
            'host': str(oauth_cfg.get('host') or '127.0.0.1').strip() or '127.0.0.1',
            'port': _safe_int(oauth_cfg.get('port'), 1455, 1),
            'timeout': _safe_int(oauth_cfg.get('timeout'), 300, 10),
            'mock': _safe_bool(oauth_cfg.get('mock', False), False),
        },
        'security': {
            'username': str(sec_cfg.get('username') or 'admin').strip() or 'admin',
            'password_hash': str(sec_cfg.get('password_hash') or '').strip(),
            'api_token': str(sec_cfg.get('api_token') or '').strip(),
            'session_secret': str(sec_cfg.get('session_secret') or '').strip(),
            'session_minutes': _safe_int(sec_cfg.get('session_minutes'), 480, 5),
            'secure_cookie': _safe_bool(sec_cfg.get('secure_cookie', False), False),
            'login_rate_limit': _safe_int(sec_cfg.get('login_rate_limit'), 8, 3),
            'login_window_seconds': _safe_int(sec_cfg.get('login_window_seconds'), 900, 60),
            'csrf_enabled': _safe_bool(sec_cfg.get('csrf_enabled', True), True),
            'trusted_origins': [str(item).strip() for item in trusted_origins if str(item).strip()],
        },
    }


def _sorted_provider_names(providers: Dict[str, Any]) -> List[str]:
    extra = [name for name in providers.keys() if name not in _PROVIDER_ORDER]
    return [name for name in _PROVIDER_ORDER if name in providers] + sorted(extra)


def _dump_provider_lines(provider_name: str, provider: Dict[str, Any]) -> List[str]:
    provider_type = str(provider.get('type') or provider_name).strip().lower() or provider_name
    lines = [
        f'[email.providers.{provider_name}]',
        f"enabled = {'true' if provider.get('enabled') else 'false'}",
        f"type = {_quote_toml(provider_type)}",
        f"label = {_quote_toml(str(provider.get('label') or ''))}",
    ]

    if provider_type == 'cfmail':
        lines.extend([
            f"profile = {_quote_toml(str(provider.get('profile') or 'auto'))}",
            f"fail_threshold = {int(provider.get('fail_threshold') or 3)}",
            f"cooldown_seconds = {int(provider.get('cooldown_seconds') or 1800)}",
            '',
        ])
        accounts = normalize_cfmail_accounts(provider.get('accounts') or [])
        for account in accounts:
            lines.extend([
                f'[[email.providers.{provider_name}.accounts]]',
                f"name = {_quote_toml(account['name'])}",
                f"worker_domain = {_quote_toml(account['worker_domain'])}",
                f"email_domain = {_quote_toml(account['email_domain'])}",
                f"admin_password = {_quote_toml(account['admin_password'])}",
                f"enabled = {'true' if account.get('enabled') else 'false'}",
                '',
            ])
        if not accounts:
            lines.append('')
        return lines

    if provider_type in _PROVIDERS_WITH_ENTRIES:
        lines.append('')
        entries = provider.get('entries') or []
        if not isinstance(entries, list):
            entries = []
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            entry_label = str(entry.get('label') or f'条目 {idx + 1}').strip() or f'条目 {idx + 1}'
            lines.extend([
                f'[[email.providers.{provider_name}.entries]]',
                f"enabled = {'true' if entry.get('enabled') else 'false'}",
                f"label = {_quote_toml(entry_label)}",
            ])
            if provider_type == 'mailapi_pool':
                api_bases = list(entry.get('api_bases') or [])
                if not api_bases and entry.get('api_base'):
                    api_bases = [str(entry.get('api_base') or '')]
                lines.extend([
                    f"api_base = {_quote_toml(str(entry.get('api_base') or ''))}",
                    f"api_bases = {_quote_toml_list(api_bases)}",
                    f"api_key = {_quote_toml(str(entry.get('api_key') or ''))}",
                    f"domains = {_quote_toml_list(list(entry.get('domains') or []))}",
                    '',
                ])
                continue
            if provider_type == 'cloudflare':
                lines.extend([
                    f"worker_url = {_quote_toml(str(entry.get('worker_url') or ''))}",
                    f"email_domain = {_quote_toml(str(entry.get('email_domain') or ''))}",
                    f"api_secret = {_quote_toml(str(entry.get('api_secret') or ''))}",
                    '',
                ])
                continue
            if provider_type == 'duckmail':
                lines.extend([
                    f"api_base = {_quote_toml(str(entry.get('api_base') or ''))}",
                    f"bearer = {_quote_toml(str(entry.get('bearer') or ''))}",
                    f"email_domain = {_quote_toml(str(entry.get('email_domain') or ''))}",
                    '',
                ])
                continue
            if provider_type == 'tempmail_lol':
                lines.extend([
                    f"api_base = {_quote_toml(str(entry.get('api_base') or ''))}",
                    f"api_key = {_quote_toml(str(entry.get('api_key') or ''))}",
                    f"domain = {_quote_toml(str(entry.get('domain') or ''))}",
                    '',
                ])
                continue
            if provider_type == 'lamail':
                lines.extend([
                    f"api_base = {_quote_toml(str(entry.get('api_base') or ''))}",
                    f"api_key = {_quote_toml(str(entry.get('api_key') or ''))}",
                    f"domain = {_quote_toml(str(entry.get('domain') or ''))}",
                    '',
                ])
                continue
        if not entries:
            lines.append('')
        return lines

    lines.append('')
    return lines


def dump_config_toml(cfg: Dict[str, Any]) -> str:
    normalized = normalize_config(cfg)
    email_cfg = normalized['email']
    otp_cfg = email_cfg['otp']
    weight_cfg = email_cfg['weight']
    net_cfg = normalized['network']
    cpa_cfg = normalized['cpa']
    cp_cfg = normalized['codex_proxy']
    run_cfg = normalized['run']
    webui_cfg = normalized['webui']
    oauth_cfg = normalized['oauth']
    sec_cfg = normalized['security']

    lines = [
        '# ============================================================',
        '#  Reg-GPT 统一配置文件',
        '#  主程序运行、WebUI 与安全配置统一保存在这里',
        '# ============================================================',
        '',
        '[email]',
        f"selection_mode = {_quote_toml(email_cfg['selection_mode'])}",
        '',
        '[email.otp]',
        f"wait_timeout_seconds = {int(otp_cfg['wait_timeout_seconds'])}",
        f"retry_wait_timeout_seconds = {int(otp_cfg['retry_wait_timeout_seconds'])}",
        '',
        '[email.weight]',
        f"default_score = {int(weight_cfg['default_score'])}",
        f"min_score = {int(weight_cfg['min_score'])}",
        f"max_score = {int(weight_cfg['max_score'])}",
        f"success_delta = {int(weight_cfg['success_delta'])}",
        f"failure_delta = {int(weight_cfg['failure_delta'])}",
        '',
    ]

    providers = email_cfg.get('providers') or {}
    for provider_name in _sorted_provider_names(providers):
        lines.extend(_dump_provider_lines(provider_name, providers[provider_name]))

    lines.extend([
        '[network]',
        f"enabled = {'true' if net_cfg['enabled'] else 'false'}",
        f"proxy = {_quote_toml(net_cfg['proxy'])}",
        '',
        '[cpa]',
        f"enabled = {'true' if cpa_cfg['enabled'] else 'false'}",
        f"management_url = {_quote_toml(cpa_cfg['management_url'])}",
        f"management_token = {_quote_toml(cpa_cfg['management_token'])}",
        f"upload_proxy_mode = {_quote_toml(cpa_cfg['upload_proxy_mode'])}",
        f"custom_proxy = {_quote_toml(cpa_cfg['custom_proxy'])}",
        f"timeout = {int(cpa_cfg['timeout'])}",
        f"active_probe = {'true' if cpa_cfg['active_probe'] else 'false'}",
        f"probe_timeout = {int(cpa_cfg['probe_timeout'])}",
        f"probe_workers = {int(cpa_cfg['probe_workers'])}",
        f"delete_workers = {int(cpa_cfg['delete_workers'])}",
        f"max_active_probes = {int(cpa_cfg['max_active_probes'])}",
        f"auto_sync_on_success = {'true' if cpa_cfg['auto_sync_on_success'] else 'false'}",
        f"health_probe_mode = {_quote_toml(cpa_cfg['health_probe_mode'])}",
        '',
        '[codex_proxy]',
        f"enabled = {'true' if cp_cfg['enabled'] else 'false'}",
        f"base_url = {_quote_toml(cp_cfg['base_url'])}",
        f"admin_key = {_quote_toml(cp_cfg['admin_key'])}",
        f"upload_proxy_url = {_quote_toml(cp_cfg['upload_proxy_url'])}",
        f"auto_sync_on_success = {'true' if cp_cfg['auto_sync_on_success'] else 'false'}",
        f"timeout = {int(cp_cfg['timeout'])}",
        '',
        '[run]',
        f"sleep_min = {int(run_cfg['sleep_min'])}",
        f"sleep_max = {int(run_cfg['sleep_max'])}",
        f"max_success = {int(run_cfg['max_success'])}",
        f"workers = {int(run_cfg['workers'])}",
        f"once = {'true' if run_cfg['once'] else 'false'}",
        '',
        '[webui]',
        f"host = {_quote_toml(webui_cfg['host'])}",
        f"port = {int(webui_cfg['port'])}",
        '',
        '[oauth]',
        f"enabled = {'true' if oauth_cfg['enabled'] else 'false'}",
        f"host = {_quote_toml(oauth_cfg['host'])}",
        f"port = {int(oauth_cfg['port'])}",
        f"timeout = {int(oauth_cfg['timeout'])}",
        f"mock = {'true' if oauth_cfg['mock'] else 'false'}",
        '',
        '[security]',
        f"username = {_quote_toml(sec_cfg['username'])}",
        f"password_hash = {_quote_toml(sec_cfg['password_hash'])}",
        f"api_token = {_quote_toml(sec_cfg['api_token'])}",
        f"session_secret = {_quote_toml(sec_cfg['session_secret'])}",
        f"session_minutes = {int(sec_cfg['session_minutes'])}",
        f"secure_cookie = {'true' if sec_cfg['secure_cookie'] else 'false'}",
        f"login_rate_limit = {int(sec_cfg['login_rate_limit'])}",
        f"login_window_seconds = {int(sec_cfg['login_window_seconds'])}",
        f"csrf_enabled = {'true' if sec_cfg['csrf_enabled'] else 'false'}",
        f"trusted_origins = {_quote_toml_list(list(sec_cfg['trusted_origins']))}",
        '',
    ])
    return '\n'.join(lines)


def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_config(cfg)
    content = dump_config_toml(normalized)
    _ensure_config_file()
    with _config_lock:
        temp_path = f"{CONFIG_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
        last_exc: Exception | None = None
        for attempt, delay in enumerate(_CONFIG_PERSIST_RETRY_DELAYS, start=1):
            try:
                with open(temp_path, 'w', encoding='utf-8', newline='\n') as fh:
                    fh.write(content)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temp_path, CONFIG_PATH)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass
                if _is_retryable_config_io_error(exc) and attempt < len(_CONFIG_PERSIST_RETRY_DELAYS):
                    time.sleep(delay)
                    continue
                if _is_retryable_config_io_error(exc):
                    _write_config_direct(content)
                    last_exc = None
                    break
                raise
    _update_cache(normalized)
    return copy.deepcopy(normalized)
