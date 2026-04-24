"""
Shared platform registry for Jue Agent.

Single source of truth for platform metadata consumed by both
skills_config (label display) and tools_config (default toolset
resolution).  Import ``PLATFORMS`` from here instead of maintaining
duplicate dicts in each module.
"""

from collections import OrderedDict
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    """Metadata for a single platform entry."""
    label: str
    default_toolset: str


# Ordered so that TUI menus are deterministic.
PLATFORMS: OrderedDict[str, PlatformInfo] = OrderedDict([
    ("cli",            PlatformInfo(label="🖥️  CLI",            default_toolset="jue-cli")),
    ("telegram",       PlatformInfo(label="📱 Telegram",        default_toolset="jue-telegram")),
    ("discord",        PlatformInfo(label="💬 Discord",         default_toolset="jue-discord")),
    ("slack",          PlatformInfo(label="💼 Slack",           default_toolset="jue-slack")),
    ("whatsapp",       PlatformInfo(label="📱 WhatsApp",        default_toolset="jue-whatsapp")),
    ("signal",         PlatformInfo(label="📡 Signal",          default_toolset="jue-signal")),
    ("bluebubbles",    PlatformInfo(label="💙 BlueBubbles",     default_toolset="jue-bluebubbles")),
    ("email",          PlatformInfo(label="📧 Email",           default_toolset="jue-email")),
    ("homeassistant",  PlatformInfo(label="🏠 Home Assistant",  default_toolset="jue-homeassistant")),
    ("mattermost",     PlatformInfo(label="💬 Mattermost",      default_toolset="jue-mattermost")),
    ("matrix",         PlatformInfo(label="💬 Matrix",          default_toolset="jue-matrix")),
    ("dingtalk",       PlatformInfo(label="💬 DingTalk",        default_toolset="jue-dingtalk")),
    ("feishu",         PlatformInfo(label="🪽 Feishu",          default_toolset="jue-feishu")),
    ("wecom",          PlatformInfo(label="💬 WeCom",           default_toolset="jue-wecom")),
    ("wecom_callback", PlatformInfo(label="💬 WeCom Callback",  default_toolset="jue-wecom-callback")),
    ("weixin",         PlatformInfo(label="💬 Weixin",          default_toolset="jue-weixin")),
    ("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="jue-qqbot")),
    ("webhook",        PlatformInfo(label="🔗 Webhook",         default_toolset="jue-webhook")),
    ("api_server",     PlatformInfo(label="🌐 API Server",      default_toolset="jue-api-server")),
])


def platform_label(key: str, default: str = "") -> str:
    """Return the display label for a platform key, or *default*."""
    info = PLATFORMS.get(key)
    return info.label if info is not None else default
