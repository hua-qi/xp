from __future__ import annotations
import json
import re
from typing import Optional


_FRAMEWORK_HINTS = {
    "react": "react",
    "react-dom": "react",
    "next": "nextjs",
    "vue": "vue",
    "nuxt": "nuxtjs",
    "angular": "angular",
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "gin": "gin",
    "echo": "echo",
    "fiber": "fiber",
    "spring": "spring",
    "express": "express",
}


def parse_manifest(manifest: Optional[str]) -> dict:
    if not manifest or not manifest.strip():
        return {"language": "unknown", "frameworks": [], "top_dependencies": []}

    text = manifest.strip()

    if text.startswith("{"):
        return _parse_package_json(text)
    if "module " in text and "require (" in text:
        return _parse_go_mod(text)
    if "[project]" in text or "dependencies" in text:
        return _parse_pyproject_toml(text)

    return {"language": "unknown", "frameworks": [], "top_dependencies": []}


def _parse_package_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"language": "unknown", "frameworks": [], "top_dependencies": []}

    deps = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))

    top_deps = list(deps.keys())[:10]
    frameworks = _detect_frameworks(top_deps)

    return {"language": "javascript", "frameworks": frameworks, "top_dependencies": top_deps}


def _parse_pyproject_toml(text: str) -> dict:
    deps = []
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "dependencies = [" or stripped.startswith("dependencies = ["):
            in_deps = True
        if in_deps:
            match = re.search(r'"([a-zA-Z0-9_\-]+)', stripped)
            if match:
                deps.append(match.group(1).lower())
        if in_deps and "]" in stripped and not stripped.startswith("dependencies"):
            in_deps = False

    inline = re.findall(r'dependencies\s*=\s*\[([^\]]+)\]', text, re.DOTALL)
    if inline:
        deps = re.findall(r'"([a-zA-Z0-9_\-]+)', inline[0])
        deps = [d.lower() for d in deps]

    top_deps = deps[:10]
    frameworks = _detect_frameworks(top_deps)

    return {"language": "python", "frameworks": frameworks, "top_dependencies": top_deps}


def _parse_go_mod(text: str) -> dict:
    deps = []
    for line in text.splitlines():
        if re.search(r'github\.com/[^/]+/([^\s/]+)', line):
            match = re.search(r'github\.com/[^/]+/([^\s/]+)', line)
            pkg = match.group(1).lower()
            deps.append(pkg)

    top_deps = list(dict.fromkeys(deps))[:10]
    frameworks = _detect_frameworks(top_deps)

    return {"language": "go", "frameworks": frameworks, "top_dependencies": top_deps}


def _detect_frameworks(dep_names: list[str]) -> list[str]:
    found = []
    for dep in dep_names:
        dep_lower = dep.lower()
        if dep_lower in _FRAMEWORK_HINTS:
            fw = _FRAMEWORK_HINTS[dep_lower]
            if fw not in found:
                found.append(fw)
    return found
