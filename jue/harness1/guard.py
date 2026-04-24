"""Harness① — Jue安全边界层

代码写死的安全边界，绝对不可越过。
不走提示词判断，不走模型决策，纯代码拦截。
不存在"为了完成任务"的例外。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)
_HOOKS_INSTALLED = False


class BlockReason(str, Enum):
    """拦截原因分类"""
    COMMAND_BLOCKED = "command_blocked"
    PATH_FORBIDDEN = "path_forbidden"
    NETWORK_FORBIDDEN = "network_forbidden"
    RESOURCE_LIMIT = "resource_limit"
    INJECTION_DETECTED = "injection_detected"


@dataclass
class BlockResult:
    """拦截结果"""
    blocked: bool
    reason: BlockReason | None = None
    detail: str = ""
    tool_name: str = ""
    original_args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Harness1Config:
    """①安全层配置，从YAML加载"""
    # 命令黑名单（正则）
    blocked_commands: list[str] = field(default_factory=lambda: [
        r"rm\s+-rf\s+/",
        r"mkfs\.",
        r"dd\s+if=.*of=/dev/",
        r":\(\)\{\s*:\|:\&\s*\}\s*;",  # fork bomb
        r"chmod\s+777\s+/",
        r"curl\s+.*\|\s*sh",
        r"wget\s+.*\|\s*sh",
    ])

    # 路径黑名单（绝对路径前缀）
    forbidden_paths: list[str] = field(default_factory=lambda: [
        "/etc/shadow",
        "/etc/passwd",
        "/root/.ssh",
        "/etc/ssh",
    ])

    # 网络黑名单（域名正则）
    forbidden_network: list[str] = field(default_factory=lambda: [])

    # 资源限制
    max_command_timeout: int = 600        # 单条命令最长秒数
    max_file_size_mb: int = 50            # 单文件最大MB
    max_concurrent_processes: int = 10    # 最大并发进程数

    # 注入检测
    injection_patterns: list[str] = field(default_factory=lambda: [
        r"ignore\s+(previous|above|all)\s+instructions",
        r"you\s+are\s+now\s+",
        r"system\s*:\s*",
        r"<\|im_start\|>",
        r"\[INST\]",
    ])


class Harness1Guard:
    """Harness① 安全边界守卫

    在工具调用层之下加一层代码拦截。
    所有工具调用必须经过此守卫，被拦截的直接返回错误，不执行。

    设计原则：
    - 只做拦截，不做建议
    - 只做减法，不做加法
    - 拦截理由必须可审计
    - 配置从YAML加载，但运行时不可修改
    """

    def __init__(self, config: Harness1Config | None = None, config_path: Path | None = None):
        self._config = config or Harness1Config()
        self._config_path = config_path
        self._compiled_commands: list[re.Pattern] = []
        self._compiled_injections: list[re.Pattern] = []
        self._audit_log: list[dict[str, Any]] = []
        self._active_processes: int = 0
        self._compile_rules()

    def _compile_rules(self) -> None:
        """预编译所有正则规则"""
        for pattern in self._config.blocked_commands:
            try:
                self._compiled_commands.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logger.warning("Invalid command block pattern %r: %s", pattern, e)

        for pattern in self._config.injection_patterns:
            try:
                self._compiled_injections.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logger.warning("Invalid injection pattern %r: %s", pattern, e)

    # ── 核心拦截方法（第二段写）──

    def check(self, tool_name: str, args: dict[str, Any]) -> BlockResult:
        """统一拦截入口。所有工具调用必须经过此方法。"""

        # 1. 注入检测 — 对所有工具的字符串参数扫描
        for key, value in args.items():
            if isinstance(value, str):
                inj = self.check_injection(value)
                if inj.blocked:
                    inj.tool_name = tool_name
                    inj.original_args = args
                    self._log_block(inj)
                    return inj

        # 2. 终端命令检查
        if tool_name in ("terminal", "execute_code"):
            command = args.get("command", "") or args.get("code", "")
            if command:
                cmd_result = self.check_terminal_command(command)
                if cmd_result.blocked:
                    cmd_result.tool_name = tool_name
                    cmd_result.original_args = args
                    self._log_block(cmd_result)
                    return cmd_result

        # 3. 文件路径检查
        if tool_name in ("write_file", "read_file", "patch", "search_files"):
            path = args.get("path", "")
            if path:
                path_result = self.check_file_path(path)
                if path_result.blocked:
                    path_result.tool_name = tool_name
                    path_result.original_args = args
                    self._log_block(path_result)
                    return path_result

        # 4. 资源限制检查
        res_result = self.check_resource(tool_name, args)
        if res_result.blocked:
            res_result.tool_name = tool_name
            res_result.original_args = args
            self._log_block(res_result)
            return res_result

        self._log_pass(tool_name)
        return BlockResult(blocked=False, tool_name=tool_name)

    def check_terminal_command(self, command: str) -> BlockResult:
        """检查终端命令是否安全"""
        for pattern in self._compiled_commands:
            if pattern.search(command):
                return BlockResult(
                    blocked=True,
                    reason=BlockReason.COMMAND_BLOCKED,
                    detail=f"Command matches blocked pattern: {pattern.pattern}",
                )
        return BlockResult(blocked=False)

    def check_file_path(self, path: str) -> BlockResult:
        """检查文件路径是否允许访问"""
        resolved = str(Path(path).resolve())
        for forbidden in self._config.forbidden_paths:
            if resolved.startswith(forbidden) or resolved == forbidden:
                return BlockResult(
                    blocked=True,
                    reason=BlockReason.PATH_FORBIDDEN,
                    detail=f"Path matches forbidden prefix: {forbidden}",
                )
        return BlockResult(blocked=False)

    def check_injection(self, text: str) -> BlockResult:
        """检查文本是否包含注入模式"""
        for pattern in self._compiled_injections:
            if pattern.search(text):
                return BlockResult(
                    blocked=True,
                    reason=BlockReason.INJECTION_DETECTED,
                    detail=f"Text matches injection pattern: {pattern.pattern}",
                )
        return BlockResult(blocked=False)

    def check_resource(self, tool_name: str, args: dict[str, Any]) -> BlockResult:
        """检查资源使用是否超限"""
        # 超时检查
        if tool_name == "terminal":
            timeout = args.get("timeout", 0)
            if isinstance(timeout, (int, float)) and timeout > self._config.max_command_timeout:
                return BlockResult(
                    blocked=True,
                    reason=BlockReason.RESOURCE_LIMIT,
                    detail=f"Timeout {timeout}s exceeds max {self._config.max_command_timeout}s",
                )

        # 并发进程检查
        if tool_name == "terminal" and args.get("background"):
            if self._active_processes >= self._config.max_concurrent_processes:
                return BlockResult(
                    blocked=True,
                    reason=BlockReason.RESOURCE_LIMIT,
                    detail=f"Concurrent processes {self._active_processes} >= max {self._config.max_concurrent_processes}",
                )

        return BlockResult(blocked=False)

    # ── 审计日志 ──

    def _log_block(self, result: BlockResult) -> None:
        """记录拦截事件"""
        entry = {
            "blocked": result.blocked,
            "reason": result.reason.value if result.reason else None,
            "detail": result.detail,
            "tool_name": result.tool_name,
        }
        self._audit_log.append(entry)
        logger.info("Harness① BLOCK: %s on %s — %s", result.reason, result.tool_name, result.detail)

    def _log_pass(self, tool_name: str) -> None:
        """记录放行事件（debug级别）"""
        logger.debug("Harness① PASS: %s", tool_name)

    def get_audit_log(self) -> list[dict[str, Any]]:
        """获取审计日志"""
        return list(self._audit_log)

    # ── Hook注册（第三段写）──

    def install_hook(self) -> None:
        """将①安全层注册为Jue工具调用前置钩子

        通过Jue的plugin hook机制，在每次工具调用前
        执行①的安全检查。被拦截的调用直接返回错误信息，
        不会到达实际工具执行。

        这个方法在Jue启动时调用一次。
        """
        try:
            from hermes_cli.plugins import get_plugin_manager
        except ImportError:
            # 如果plugin系统不可用，用monkey-patch方式
            logger.warning("Jue plugin system not available, falling back to monkey-patch")
            self._install_hook_monkeypatch()
            return

        guard = self

        def harness1_pre_tool_call(
            tool_name: str,
            args: dict[str, Any],
            **kwargs,
        ) -> dict[str, str] | None:
            """返回None表示放行，返回标准block指令表示拦截"""
            result = guard.check(tool_name, args)
            if result.blocked:
                return {
                    "action": "block",
                    "message": (
                        f"[Harness① BLOCKED] {result.reason.value}: {result.detail}\n"
                        f"此操作被安全边界拦截，不可绕过。"
                    ),
                }
            return None

        manager = get_plugin_manager()
        manager._hooks.setdefault("pre_tool_call", []).append(harness1_pre_tool_call)
        logger.info("Harness① guard installed via plugin hook")

    def _install_hook_monkeypatch(self) -> None:
        """备用方案：monkey-patch handle_function_call

        在handle_function_call入口处插入①检查。
        如果被拦截，直接返回错误JSON，不执行原始函数。
        """
        import model_tools as _mt
        guard = self
        _original_handle = _mt.handle_function_call

        def _guarded_handle_function_call(
            function_name: str,
            function_args: dict[str, Any],
            **kwargs,
        ) -> str:
            result = guard.check(function_name, function_args)
            if result.blocked:
                return json.dumps({
                    "error": f"[Harness① BLOCKED] {result.reason.value}: {result.detail}",
                    "blocked_by": "harness1",
                    "reason": result.reason.value,
                    "detail": result.detail,
                }, ensure_ascii=False)
            return _original_handle(function_name, function_args, **kwargs)

        _mt.handle_function_call = _guarded_handle_function_call
        logger.info("Harness① guard installed via monkey-patch on handle_function_call")


# =============================================================================
# 便捷函数
# =============================================================================

def register_hooks(config: Harness1Config | None = None) -> Harness1Guard:
    """注册①安全层hook到model_tools

    用法：
        from jue.harness1.guard import register_hooks
        register_hooks()  # 使用默认配置
    """
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        logger.debug("Harness① hooks already installed; skipping duplicate registration")
        return Harness1Guard(config=config)
    guard = Harness1Guard(config=config)
    guard.install_hook()
    _HOOKS_INSTALLED = True
    return guard
