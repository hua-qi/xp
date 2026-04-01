from src.models import ExperienceType, ExperienceLevel


_TECH_KEYWORDS = {
    "react": ["react", "useeffect", "usestate", "hooks"],
    "vue": ["vue", "composition api", "ref", "reactive"],
    "typescript": ["typescript", "ts", "类型", "type"],
    "javascript": ["javascript", "js", "es6", "async", "await"],
    "python": ["python", "django", "flask", "fastapi"],
    "css": ["css", "scss", "less", "tailwind", "styled"],
    "node": ["node", "nodejs", "npm", "express"],
    "database": ["sql", "mysql", "postgresql", "mongodb", "redis"],
    "docker": ["docker", "container", "k8s", "kubernetes"],
    "git": ["git", "github", "gitlab", "commit", "merge"],
}

_SCENE_KEYWORDS = {
    "表单": ["表单", "form", "input", "validation", "校验"],
    "列表": ["列表", "list", "table", "grid", "pagination"],
    "异步": ["异步", "async", "await", "promise", "fetch", "api"],
    "状态管理": ["状态", "state", "redux", "vuex", "pinia", "mobx"],
    "路由": ["路由", "router", "navigation", "route", "页面跳转"],
    "性能优化": ["性能", "优化", "performance", "lazy", "cache", "memo"],
    "测试": ["测试", "test", "jest", "vitest", "cypress", "e2e"],
    "部署": ["部署", "deploy", "ci/cd", "pipeline", "build"],
    "UI 组件": ["组件", "component", "ui", "界面", "布局", "layout"],
    "样式": ["样式", "style", "css", "scss", "less", "tailwind", "styled"],
    "弹窗/模态": ["弹窗", "模态", "modal", "dialog", "popup", "overlay"],
    "CLI 工具": ["cli", "命令行", "command line", "终端", "terminal", "shell", "prompt"],
    "快捷键": ["快捷键", "keybinding", "shortcut", "按键", "hotkey"],
    "输入处理": ["输入", "input", "多行", "multiline", "换行", "enter"],
    "跨平台": ["跨平台", "兼容", "windows", "linux", "macos", "mac", "跨终端"],
    "数据库": ["数据库", "database", "sql", "query", "orm", "prisma"],
    "API 设计": ["api", "接口", "endpoint", "rest", "graphql"],
    "认证授权": ["认证", "授权", "auth", "login", "token", "jwt", "oauth"],
    "错误处理": ["错误", "error", "exception", "catch", "try", "debug", "排查"],
    "日志监控": ["日志", "log", "监控", "monitor", "trace", "metrics"],
    "配置管理": ["配置", "config", "env", "environment", "variable", "设置"],
    "文件操作": ["文件", "file", "目录", "folder", "path", "读写"],
    "依赖管理": ["依赖", "dependency", "npm", "pip", "package", "install"],
    "构建工具": ["构建", "build", "webpack", "vite", "rollup", "esbuild"],
    "类型系统": ["类型", "type", "typescript", "typecheck", "interface"],
    "代码规范": ["lint", "format", "prettier", "eslint", "规范", "风格"],
    "版本控制": ["git", "版本", "commit", "merge", "branch", "rebase"],
    "API 文档": ["api 文档", "api doc", "swagger", "openapi", "接口文档"],
    "README": ["readme", "项目介绍", "快速开始", "quick start"],
    "技术文档": ["技术文档", "tech doc", "documentation", "wiki", "指南", "guide"],
    "代码注释": ["注释", "comment", "docstring", "jsdoc", "typedoc"],
    "容器化": ["docker", "容器", "container", "镜像", "image", "compose"],
    "K8s": ["kubernetes", "k8s", "pod", "deployment", "service", "helm"],
    "云服务": ["aws", "azure", "gcp", "阿里云", "腾讯云", "云服务器"],
    "CI/CD": ["ci/cd", "jenkins", "github actions", "gitlab ci", "自动化部署"],
    "监控告警": ["监控", "告警", "alert", "prometheus", "grafana", "sentry"],
    "数据处理": ["数据处理", "etl", "pipeline", "清洗", "transform"],
    "数据分析": ["数据分析", "analysis", "pandas", "jupyter", "可视化"],
    "算法模型": ["算法", "模型", "机器学习", "ml", "深度学习", "训练"],
    "环境配置": ["环境", "environment", "setup", "安装", "初始化", "配置"],
    "权限管理": ["权限", "permission", "role", "rbac", "访问控制"],
    "安全措施": ["安全", "security", "加密", "xss", "csrf", "注入", "漏洞"],
    "性能调优": ["性能", "perf", "优化", "慢", "卡顿", "内存泄漏"],
}


def infer_tech_stack(text: str) -> list:
    text_lower = text.lower()
    return [tech for tech, kws in _TECH_KEYWORDS.items() if any(k in text_lower for k in kws)]


def infer_scene(text: str) -> list:
    text_lower = text.lower()
    return [scene for scene, kws in _SCENE_KEYWORDS.items() if any(k in text_lower for k in kws)]


def infer_type(task: str, decisions: str) -> ExperienceType:
    text = (task + decisions).lower()
    if any(k in text for k in ["bug", "fix", "修复", "报错", "error"]):
        return ExperienceType.BUGFIX
    if any(k in text for k in ["模式", "pattern", "架构", "规范"]):
        return ExperienceType.PATTERN
    return ExperienceType.FEATURE


def infer_level(task: str, decisions: str) -> ExperienceLevel:
    text = (task + decisions).lower()
    if any(k in text for k in ["架构", "模式", "pattern", "设计", "architecture"]):
        return ExperienceLevel.L1
    if any(k in text for k in ["bug", "fix", "修复", "报错", "error", "exception"]):
        return ExperienceLevel.L3
    return ExperienceLevel.L2
