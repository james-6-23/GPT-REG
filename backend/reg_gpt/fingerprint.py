import random
import re
from typing import Any, Dict, List, Optional

_FP_IMPERSONATE_CANDIDATES = [
    "chrome142", "chrome136", "chrome133a", "chrome131", "chrome124",
    "chrome123", "chrome120", "chrome119", "chrome116", "chrome110",
    "chrome107", "chrome104", "chrome101", "chrome100", "chrome99",
    "edge101", "edge99",
    "firefox144", "firefox135", "firefox133", "tor145",
    "safari2601", "safari260", "safari184", "safari180", "safari170",
    "safari15_5", "safari15_3",
]

_FP_LANG_PRIMARY = [
    "en-US", "en-US", "en-US", "en-US",
    "en-GB", "en-GB",
    "en-CA", "en-AU", "en-NZ", "en-IE",
]

_FP_LANG_SECONDARY = [
    "en-GB", "en-AU", "en-CA", "en-NZ",
    "en-IE", "en-SG", "en-ZA", "en-IN",
]

_FP_PLATFORM_POOL = ['"Windows"', '"macOS"', '"Linux"']
_FP_WIN_VERSION_POOL = ['"10.0.0"', '"10.0.0"', '"10.0.0"', '"11.0.0"', '"11.0.0"']
_FP_MAC_VERSION_POOL = ['"13.0.0"', '"13.1.0"', '"14.0.0"', '"14.4.0"', '"15.0.0"']
_FP_ANDROID_VERSION_POOL = ['"12.0.0"', '"13.0.0"', '"14.0.0"', '"15.0.0"']
_FP_IOS_VERSION_POOL = ['"16.0.0"', '"17.0.0"', '"18.0.0"']

_FP_VIEWPORT_POOL_DESKTOP = [
    (1920, 1080), (1920, 1080), (1920, 1080),
    (2560, 1440), (2560, 1440),
    (1440, 900), (1366, 768), (1536, 864),
    (1680, 1050), (1280, 800), (1600, 900),
    (2560, 1600), (3840, 2160),
]

_FP_VIEWPORT_POOL_MOBILE = [
    (360, 800), (360, 780), (360, 760),
    (375, 667), (375, 812), (375, 812),
    (390, 844), (390, 844), (393, 852),
    (412, 915), (414, 896), (428, 926), (430, 932),
]

_FP_TIMEZONE_POOL = [
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Toronto", "America/Vancouver", "America/Phoenix", "America/Anchorage",
    "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Amsterdam",
    "Europe/Stockholm", "Europe/Zurich", "Europe/Dublin",
    "Asia/Tokyo", "Asia/Seoul", "Asia/Singapore", "Asia/Hong_Kong", "Asia/Kolkata",
    "Australia/Sydney", "Pacific/Auckland", "Africa/Johannesburg",
]

_FP_TZ_BY_LANG = {
    "en-US": [
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
        "America/Phoenix", "America/Anchorage",
    ],
    "en-CA": ["America/Toronto", "America/Vancouver"],
    "en-GB": ["Europe/London"],
    "en-IE": ["Europe/Dublin", "Europe/London"],
    "en-AU": ["Australia/Sydney"],
    "en-NZ": ["Pacific/Auckland", "Australia/Sydney"],
    "en-SG": ["Asia/Singapore", "Asia/Hong_Kong"],
    "en-IN": ["Asia/Kolkata"],
    "en-ZA": ["Africa/Johannesburg"],
}


def imp_family(imp: str) -> str:
    if imp.startswith("chrome"):
        return "chrome"
    if imp.startswith("edge"):
        return "edge"
    if imp.startswith("firefox"):
        return "firefox"
    if imp.startswith("tor"):
        return "tor"
    if imp.startswith("safari"):
        return "safari"
    return "other"


def imp_engine(imp: str) -> str:
    family = imp_family(imp)
    if family in ("chrome", "edge"):
        return "chromium"
    if family in ("firefox", "tor"):
        return "gecko"
    if family == "safari":
        return "webkit"
    return "other"


def imp_is_mobile(imp: str) -> bool:
    name = imp.lower()
    return ("android" in name) or ("ios" in name)


def imp_version_num(imp: str) -> int:
    match = re.search(r"(\d+)", imp)
    return int(match.group(1)) if match else -1


def resolve_impersonate_pool() -> List[str]:
    versioned_supported: set[str] = set()
    aliases_supported: set[str] = set()
    try:
        from curl_cffi.requests.impersonate import BrowserType, REAL_TARGET_MAP

        aliases_supported = set(REAL_TARGET_MAP.keys())
        for browser_type in BrowserType:
            name = str(browser_type.value)
            family = imp_family(name)
            if family not in ("chrome", "edge", "firefox", "tor", "safari"):
                continue
            if any(ch.isdigit() for ch in name):
                versioned_supported.add(name)
    except Exception:
        versioned_supported = set()
        aliases_supported = set()

    pool = [name for name in _FP_IMPERSONATE_CANDIDATES if name in versioned_supported]
    extras = [name for name in versioned_supported if name not in pool]

    family_order = {
        "chrome": 0,
        "edge": 1,
        "firefox": 2,
        "safari": 3,
        "tor": 4,
        "other": 9,
    }

    def sort_key(name: str) -> tuple[int, int, int, str]:
        family = imp_family(name)
        mobile_rank = 1 if imp_is_mobile(name) else 0
        return (family_order.get(family, 9), mobile_rank, -imp_version_num(name), name)

    extras.sort(key=sort_key)
    pool.extend(extras)
    if pool:
        return pool
    if "chrome" in aliases_supported:
        return ["chrome"]
    if aliases_supported:
        return [sorted(aliases_supported)[0]]
    return ["chrome"]


FP_IMPERSONATE_POOL = resolve_impersonate_pool()


def choose_timezone(primary_lang: str) -> str:
    pool = _FP_TZ_BY_LANG.get(primary_lang)
    if pool:
        return random.choice(pool)
    return random.choice(_FP_TIMEZONE_POOL)


def choose_viewport(is_mobile: bool) -> tuple[int, int]:
    pool = _FP_VIEWPORT_POOL_MOBILE if is_mobile else _FP_VIEWPORT_POOL_DESKTOP
    return random.choice(pool)


def build_fingerprint(
    imp_override: Optional[str] = None,
    primary_lang_override: Optional[str] = None,
    accept_language_override: Optional[str] = None,
    platform_override: Optional[str] = None,
    os_ver_override: Optional[str] = None,
) -> Dict[str, Any]:
    imp = imp_override or random.choice(FP_IMPERSONATE_POOL)
    family = imp_family(imp)
    engine = imp_engine(imp)
    is_mobile = imp_is_mobile(imp)

    if accept_language_override:
        accept_language = accept_language_override
        primary = (primary_lang_override or accept_language.split(",", 1)[0].split(";", 1)[0]).strip()
    else:
        primary = primary_lang_override or random.choice(_FP_LANG_PRIMARY)
        n_extra = random.randint(0, 2)
        extras = random.sample(_FP_LANG_SECONDARY, min(n_extra, len(_FP_LANG_SECONDARY)))
        q_vals = sorted([round(random.uniform(0.75, 0.93), 2) for _ in extras], reverse=True)
        lang_parts = [primary]
        for tag, q in zip(extras, q_vals):
            lang_parts.append(f"{tag};q={q}")
        lang_parts.append(f"en;q={round(random.uniform(0.60, 0.74), 2)}")
        accept_language = ",".join(dict.fromkeys(lang_parts))

    if "android" in imp:
        platform = '"Android"'
        os_ver = random.choice(_FP_ANDROID_VERSION_POOL)
    elif "ios" in imp:
        platform = '"iOS"'
        os_ver = random.choice(_FP_IOS_VERSION_POOL)
    else:
        platform_pool = ['"macOS"'] if family == "safari" else _FP_PLATFORM_POOL
        platform = random.choice(platform_pool)
        if platform == '"Windows"':
            os_ver = random.choice(_FP_WIN_VERSION_POOL)
        elif platform == '"macOS"':
            os_ver = random.choice(_FP_MAC_VERSION_POOL)
        else:
            os_ver = '"5.15.0"'

    if platform_override:
        platform = str(platform_override)
    if os_ver_override:
        os_ver = str(os_ver_override)

    viewport_w, viewport_h = choose_viewport(is_mobile)
    timezone = choose_timezone(primary)
    ver_num = "".join(filter(str.isdigit, imp)) or "124"

    return {
        "impersonate": imp,
        "family": family,
        "engine": engine,
        "is_mobile": is_mobile,
        "lang_primary": primary,
        "accept_language": accept_language,
        "platform": platform,
        "os_ver": os_ver,
        "viewport_w": viewport_w,
        "viewport_h": viewport_h,
        "timezone": timezone,
        "browser_ver": ver_num,
        "chrome_ver": ver_num,
    }


def build_fp_headers(fp: Dict[str, Any]) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Accept-Language": fp["accept_language"],
        "X-Timezone": fp["timezone"],
    }
    if fp.get("engine") == "chromium":
        brand = "Microsoft Edge" if fp.get("family") == "edge" else "Google Chrome"
        ver = str(fp.get("browser_ver") or fp.get("chrome_ver") or "124")
        mobile = "?1" if fp.get("is_mobile") else "?0"
        headers.update({
            "Sec-CH-UA": f'"Chromium";v="{ver}", "{brand}";v="{ver}", "Not_A Brand";v="24"',
            "Sec-CH-UA-Mobile": mobile,
            "Sec-CH-UA-Platform": fp["platform"],
            "Sec-CH-Viewport-Width": str(fp["viewport_w"]),
        })
    return headers
