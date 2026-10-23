"""Shared result type for validators and preflight checks."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Literal

Level = Literal["error", "warning", "info"]


@dataclass
class Finding:
    level: Level
    code: str
    message: str
    where: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class FindingList:
    items: list[Finding] = field(default_factory=list)

    def error(self, code: str, message: str, where: str = "") -> None:
        self.items.append(Finding("error", code, message, where))

    def warning(self, code: str, message: str, where: str = "") -> None:
        self.items.append(Finding("warning", code, message, where))

    def info(self, code: str, message: str, where: str = "") -> None:
        self.items.append(Finding("info", code, message, where))

    def extend(self, other: "FindingList") -> None:
        self.items.extend(other.items)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.items if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.items if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
