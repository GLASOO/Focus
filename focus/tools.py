"""Focus Agent 工具注册表（L2 工具层）。

之前 Phase 1-8 只实现了 L3-L7（韧性/记忆/路由/循环/交互），
L2 工具层被跳过——导致 Agent 只能空谈，不能执行。
这是"能正常会话但不能完成任务"的根因。

工具协议：
  - 每个工具实现 call(arg: str) -> str
  - 工具调用语法（在模型输出里）：
      <tool=工具名>参数</tool>
  - 一次呼吸可调用多个工具，按出现顺序执行
  - 工具结果回写 Graph（作为节点 hint/observation 落盘）

注意：工具执行有白名单 + 安全约束（禁止破坏性命令、限制路径）。
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Dict

# ── 安全约束 ────────────────────────────────────────
# 允许目录 = 环境变量 FOCUS_TOOL_DIRS（冒号分隔）或默认安全集
# （仓库自身所在目录 + /tmp）。2026-08-14 发布工程：去除个人目录预设。
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_DIRS = (
    [os.path.expanduser(p) for p in
     os.environ.get("FOCUS_TOOL_DIRS", "").split(":") if p.strip()]
    or [_REPO_DIR, "/tmp"]
)
_HOME = os.path.expanduser("~")

# 禁止片段：子串匹配（大小写不敏感）
FORBIDDEN_SUBSTRINGS = [
    "rm -rf", "mkfs", "dd if=", ":(){", "> /dev/sda",
    "chmod -R 777 /", "sudo",
]

# 禁止模式：正则匹配（解决子串匹配被管道中间内容绕过的问题）
# 任何下载工具管道到 shell 解释器 = 远程代码执行，必须拦截
FORBIDDEN_PATTERNS = [
    re.compile(r'\b(curl|wget|fetch)\b.*\|\s*(sh|bash|zsh|fish)\b', re.IGNORECASE),
    re.compile(r'\|\s*(sh|bash|zsh|fish)\b', re.IGNORECASE),  # 任何管道到 shell
    re.compile(r'\b(curl|wget)\b.*\b(-o|--)\s*/dev/(sd|nvme|disk)', re.IGNORECASE),  # 下载到块设备
    re.compile(r'\beval\b\s*\(', re.IGNORECASE),  # eval(
    re.compile(r'\bexec\b\s*\(', re.IGNORECASE),  # exec(
    re.compile(r'/dev/(sd[a-z]|nvme|disk\d)', re.IGNORECASE),  # 块设备访问
    # 2026-08-15 P0（审查 #3）：敏感目标与持久化后门
    re.compile(r'\bcrontab\b', re.IGNORECASE),
    re.compile(r'\.(zshrc|bashrc|bash_profile|profile)\b'),
    re.compile(r'/\.ssh\b'),
    re.compile(r'/etc/(passwd|sudoers|hosts)'),
    re.compile(r'\b(shutdown|reboot|halt)\b', re.IGNORECASE),
    re.compile(r'\blaunchctl\b', re.IGNORECASE),
    re.compile(r'\b(diskutil|fsck|mkfs)\b', re.IGNORECASE),
]


def _in_allowed(path: str) -> bool:
    ap = os.path.abspath(os.path.expanduser(path))
    return any(ap.startswith(d) for d in ALLOWED_DIRS)


class ToolRegistry:
    """工具注册表。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Callable[[str], str]] = {}
        self.register_defaults()

    def register(self, name: str, fn: Callable[[str], str]) -> None:
        self._tools[name] = fn

    def register_defaults(self) -> None:
        self.register("ls", self._ls)
        self.register("cat", self._cat)
        self.register("pwd", lambda _: os.getcwd())
        self.register("python", self._python)
        self.register("bash", self._bash)
        # 上网学习工具（此机无限 · 开放系统）
        try:
            from . import web as _web
            self.register("web_search", self._web_search)
            self.register("web_read", self._web_read)
        except Exception:
            pass

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())

    def call(self, name: str, arg: str) -> str:
        if name not in self._tools:
            return f"[工具不存在: {name}]"
        arg = arg.strip()
        # 2026-08-15 护栏：0.8B 有时把胡话当参数——太长即拒绝并给正例
        if len(arg) > 300:
            return ("[拒绝: 参数太长，像是把话当成了参数。参数应该短而具体。"
                    "示例：<tool=selfmap></tool> 或 <tool=ls>~/focus-agent</tool>]")
        # 智能路由：如果参数看起来是完整命令（含空格/管道/重定向/绝对路径+参数），
        # 自动降级到 bash 执行（小模型常见行为：把命令整体塞进工具参数）
        looks_like_cmd = (
            " | " in arg or " > " in arg or " && " in arg or " || " in arg
            or (" " in arg and arg.startswith("/"))
            or arg.startswith(("ls ", "cat ", "cd ", "find ", "grep ", "head ", "tail "))
        )
        if looks_like_cmd and name in ("ls", "cat", "python", "bash"):
            if name == "python" and not arg.startswith(("ls ", "cat ", "cd ")):
                pass  # python 参数保持原样
            else:
                return self._bash(arg)
        try:
            return self._tools[name](arg)
        except Exception as e:
            return f"[工具执行错误: {e}]"

    # ── 上网工具 ────────────────────────────────────
    def _web_search(self, arg: str) -> str:
        """搜索网络。返回结构化结果供 0.8B 阅读。"""
        try:
            from . import web as _web
            results = _web.web_search(arg.strip(), n=3)
            if not results:
                return "[搜索无结果]"
            return _web.format_search_for_model(arg.strip(), results)
        except Exception as e:
            return f"[web_search 错误: {e}]"

    def _web_read(self, arg: str) -> str:
        """读取网页内容。"""
        try:
            from . import web as _web
            text = _web.web_read(arg.strip())
            return text[:2000]  # 0.8B 上下文有限
        except Exception as e:
            return f"[web_read 错误: {e}]"

    # ── 内置工具 ────────────────────────────────────
    def _ls(self, arg: str) -> str:
        path = arg or "."
        if not _in_allowed(path):
            return f"[拒绝: 路径 {path} 不在允许目录]"
        try:
            items = sorted(os.listdir(os.path.expanduser(path)))
        except Exception as e:
            return f"[ls 错误: {e}]"
        return "\n".join(items) if items else "(空目录)"

    def _cat(self, arg: str) -> str:
        path = arg.strip()
        if not _in_allowed(path):
            return f"[拒绝: 路径 {path} 不在允许目录]"
        p = os.path.expanduser(path)
        if not os.path.isfile(p):
            return f"[文件不存在: {p}]"
        if os.path.getsize(p) > 50_000:
            return f"[文件过大，仅读前50KB]"
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:50_000]
        except Exception as e:
            return f"[cat 错误: {e}]"

    # 2026-08-15 P0 安全（WorkBuddy 审查 #1）：语义能力圈——
    # import 白名单 AST 审查 + 受限 __import__。危险模块一律拒，
    # 安全模块（math/json/re…）放行，让 python 工具真正有用。
    _ALLOWED_IMPORTS = frozenset((
        "math", "json", "re", "time", "datetime", "random", "statistics",
        "collections", "itertools", "functools", "string", "textwrap",
        "decimal", "fractions", "hashlib", "base64"))

    @classmethod
    def _check_code(cls, code: str):
        """AST 审查：返回 None 放行，否则返回拒绝理由。"""
        import ast
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"语法错误: {e}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] not in cls._ALLOWED_IMPORTS:
                        return f"禁止 import {a.name}（语义能力圈外）"
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root not in cls._ALLOWED_IMPORTS:
                    return f"禁止 from {node.module} import（语义能力圈外）"
        return None

    def _python(self, arg: str) -> str:
        """执行 Python 表达式/脚本（非交互，AST 审查 + 受限内置）。"""
        verdict = self._check_code(arg)
        if verdict:
            return f"[拒绝: {verdict}]"
        try:
            import io
            import contextlib
            # 2026-08-14 实机评测修复：空 builtins 导致 open/print 全禁，
            # 写文件必败。给白名单内置 + 受限 __import__（AST 已把关）
            import builtins as _b
            _allowed = self._ALLOWED_IMPORTS

            def _safe_import(name, *a, **kw):
                if name.split(".")[0] not in _allowed:
                    raise ImportError(f"{name} 在语义能力圈外")
                return __import__(name, *a, **kw)
            safe = {n: getattr(_b, n) for n in (
                "abs", "all", "any", "bool", "dict", "enumerate", "filter",
                "float", "format", "frozenset", "getattr", "hasattr", "int",
                "isinstance", "len", "list", "map", "max", "min", "open",
                "ord", "chr", "print", "range", "repr", "reversed", "round",
                "set", "slice", "sorted", "str", "sum", "tuple", "zip")}
            safe["__import__"] = _safe_import
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exec(compile(arg, "<agent>", "exec"), {"__builtins__": safe})
            out = buf.getvalue()
            return out[:2000] if out else "(无输出)"
        except Exception as e:
            return f"[python 错误: {type(e).__name__}: {e}]"

    def _bash(self, arg: str) -> str:
        """执行 shell 命令。

        安全策略：只拒绝危险关键词，不当路径检查
        （因为小模型可能把 "ls /path" 当参数整体传入）。
        """
        lowered = arg.lower()
        # 子串匹配（快速路径）
        if any(f in lowered for f in FORBIDDEN_SUBSTRINGS):
            return f"[拒绝: 命令含禁止片段]"
        # 正则匹配（防管道绕过）
        for pat in FORBIDDEN_PATTERNS:
            if pat.search(arg):
                return f"[拒绝: 命令含危险模式: {pat.pattern}]"
        try:
            r = subprocess.run(
                arg, shell=True, capture_output=True, text=True,
                timeout=30, cwd=_REPO_DIR,
            )
            out = (r.stdout or "") + (r.stderr or "")
            if not out:
                return f"(退出码 {r.returncode}, 无输出)"
            return out[:3000]
        except subprocess.TimeoutExpired:
            return "[超时: 命令超过30秒]"
        except Exception as e:
            return f"[bash 错误: {e}]"


def parse_tool_calls(text: str) -> list[tuple[str, str]]:
    """从模型输出里解析 <tool=名>参数</tool> 调用。

    兼容 stop 序列截断：模型可能在 </tool> 前被停止（text 无闭合标签），
    此时把 `<tool=名>` 到文本末尾当作参数。
    """
    import re
    calls = []
    # 先找完整闭合的（2026-08-15 容错：0.8B 有时写 [tool=名] 方括号变体）
    for m in re.finditer(r"[<\[]tool=([a-zA-Z_]+)[>\]](.*?)(?:</tool>|\[/tool\])",
                         text, re.DOTALL):
        calls.append((m.group(1), m.group(2)))
    # 再找未闭合的（无 </tool> 且不在已匹配区间内）
    open_pat = re.compile(r"[<\[]tool=([a-zA-Z_]+)[>\]]")
    closed_spans = [m.span() for m in re.finditer(
        r"[<\[]tool=[a-zA-Z_]+[>\]].*?(?:</tool>|\[/tool\])", text, re.DOTALL)]
    for m in open_pat.finditer(text):
        start = m.start()
        if any(s <= start < e for s, e in closed_spans):
            continue  # 已闭合匹配覆盖
        rest = text[m.end():]
        arg = rest.strip()  # 去首尾空白（模型常在 <tool=名> 后换行）
        if arg:
            calls.append((m.group(1), arg))
    return calls
