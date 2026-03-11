"""Skill registry for source-expandable REPL imports.

Manages ReplSkillExport entries and expands synthetic
``from rlm_repl_skills.<mod> import <sym>`` imports into inline source
before the AST rewriter runs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class ReplSkillExport:
    module: str
    name: str
    source: str
    requires: list[str] = field(default_factory=list)
    kind: str = "function"


@dataclass
class ExpandedSkillCode:
    original_code: str
    expanded_code: str
    expanded_symbols: list[str] = field(default_factory=list)
    expanded_modules: list[str] = field(default_factory=list)
    did_expand: bool = False


class SkillRegistry:
    def __init__(self) -> None:
        self._exports: dict[str, dict[str, ReplSkillExport]] = {}

    def register(self, export: ReplSkillExport) -> None:
        mod_exports = self._exports.setdefault(export.module, {})
        mod_exports[export.name] = export

    def resolve(self, module: str, names: list[str]) -> list[ReplSkillExport]:
        mod_exports = self._exports.get(module)
        if mod_exports is None:
            raise RuntimeError(
                f"Unknown synthetic module: {module!r}. "
                f"Available modules: {sorted(self._exports.keys())}"
            )
        results = []
        for name in names:
            export = mod_exports.get(name)
            if export is None:
                raise RuntimeError(
                    f"Unknown symbol {name!r} in module {module!r}. "
                    f"Available symbols: {sorted(mod_exports.keys())}"
                )
            results.append(export)
        return results

    def expand(self, code: str) -> ExpandedSkillCode:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ExpandedSkillCode(original_code=code, expanded_code=code, did_expand=False)

        # Find synthetic ImportFrom nodes
        synthetic_imports: list[tuple[str, list[str], ast.ImportFrom]] = []
        for node in tree.body:
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("rlm_repl_skills.")
            ):
                names = [alias.name for alias in node.names]
                synthetic_imports.append((node.module, names, node))

        if not synthetic_imports:
            return ExpandedSkillCode(original_code=code, expanded_code=code, did_expand=False)

        # Resolve all requested exports and their dependencies
        requested: dict[str, ReplSkillExport] = {}
        modules_seen: set[str] = set()
        for module, names, _ in synthetic_imports:
            modules_seen.add(module)
            for export in self.resolve(module, names):
                requested[export.name] = export

        # Collect all dependencies transitively
        all_exports: dict[str, ReplSkillExport] = {}
        queue = list(requested.values())
        while queue:
            export = queue.pop(0)
            if export.name in all_exports:
                continue
            all_exports[export.name] = export
            # Resolve dependencies from the same module
            for dep_name in export.requires:
                if dep_name not in all_exports:
                    mod_exports = self._exports.get(export.module, {})
                    dep = mod_exports.get(dep_name)
                    if dep is None:
                        raise RuntimeError(
                            f"Dependency {dep_name!r} required by {export.name!r} "
                            f"not found in module {export.module!r}"
                        )
                    queue.append(dep)

        # Topological sort by requires
        sorted_exports = self._topo_sort(all_exports)

        # Check for name conflicts with user-defined names
        user_names = self._collect_user_defined_names(tree, synthetic_imports)
        for export in sorted_exports:
            if export.name in user_names:
                raise RuntimeError(
                    f"Name conflict: skill export {export.name!r} conflicts with "
                    f"user-defined name in submitted code"
                )

        # Build expanded source
        # 1. Normal imports first
        normal_lines: list[str] = []
        code_lines: list[str] = []
        synthetic_nodes = {id(node) for _, _, node in synthetic_imports}
        first_non_import_idx = None

        for i, node in enumerate(tree.body):
            if id(node) in synthetic_nodes:
                continue
            if first_non_import_idx is None and not isinstance(node, (ast.Import, ast.ImportFrom)):
                first_non_import_idx = i
            source_segment = ast.get_source_segment(code, node)
            if source_segment is not None:
                if first_non_import_idx is None:
                    normal_lines.append(source_segment)
                else:
                    code_lines.append(source_segment)
            else:
                # Fallback: use line ranges
                start = node.lineno - 1
                end = node.end_lineno if node.end_lineno else node.lineno
                segment = "\n".join(code.splitlines()[start:end])
                if first_non_import_idx is None:
                    normal_lines.append(segment)
                else:
                    code_lines.append(segment)

        # 2. Skill source blocks (deduplicated, topo-sorted)
        skill_blocks: list[str] = []
        for export in sorted_exports:
            skill_blocks.append(f"# --- skill: {export.module}.{export.name} ---")
            skill_blocks.append(export.source)

        # 3. Assemble: normal imports, skill blocks, remaining code
        parts = []
        if normal_lines:
            parts.append("\n".join(normal_lines))
        if skill_blocks:
            parts.append("\n".join(skill_blocks))
        if code_lines:
            parts.append("\n".join(code_lines))

        expanded_code = "\n\n".join(parts)

        return ExpandedSkillCode(
            original_code=code,
            expanded_code=expanded_code,
            expanded_symbols=[e.name for e in sorted_exports],
            expanded_modules=sorted(modules_seen),
            did_expand=True,
        )

    def _topo_sort(self, exports: dict[str, ReplSkillExport]) -> list[ReplSkillExport]:
        """Topological sort of exports by requires dependencies."""
        visited: set[str] = set()
        result: list[ReplSkillExport] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            export = exports[name]
            for dep in export.requires:
                if dep in exports:
                    visit(dep)
            result.append(export)

        for name in exports:
            visit(name)
        return result

    def _collect_user_defined_names(
        self,
        tree: ast.Module,
        synthetic_imports: list[tuple[str, list[str], ast.ImportFrom]],
    ) -> set[str]:
        """Collect names defined by user code (excluding synthetic imports)."""
        synthetic_nodes = {id(node) for _, _, node in synthetic_imports}
        names: set[str] = set()
        for node in tree.body:
            if id(node) in synthetic_nodes:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        return names

    def clear(self) -> None:
        self._exports.clear()


# Module-level singleton
_registry = SkillRegistry()


def register_skill_export(export: ReplSkillExport) -> None:
    _registry.register(export)


def expand_skill_imports(code: str) -> ExpandedSkillCode:
    return _registry.expand(code)
