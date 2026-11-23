"""The 2018 content scope: which client modules, screens, heroes and cities this server serves.

Data only, read from data/scope_2018.json and checked once at startup. A module is the
part of an /api/ method before the dot. `open` is flipped by hand when a feature is done;
a module with `phase: null` is out of scope for good and can never be open.
"""

import copy
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "scope_2018.json"
UNCLASSIFIED = "CHUA_PHAN_LOAI"   # marks a draft entry nobody has reviewed yet


class ScopeError(ValueError):
    """The scope file is malformed; the server must not start with it."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScopeError(message)


def _check_module(name, entry) -> None:
    _require(isinstance(entry, dict), f"module {name}: must be an object")
    phase, is_open = entry.get("phase", "missing"), entry.get("open")
    _require(phase is None or _is_int(phase), f"module {name}: phase must be an integer or null")
    _require(isinstance(is_open, bool), f"module {name}: open must be true or false")
    _require(not (phase is None and is_open), f"module {name}: out of scope (phase null) but open")
    _require(isinstance(entry.get("reason", ""), str), f"module {name}: reason must be text")


def _check_quiet(method, entry) -> None:
    _require(isinstance(entry, dict), f"quiet {method}: must be an object")
    _require(isinstance(entry.get("body"), dict), f"quiet {method}: body must be an object")
    evidence = entry.get("evidence")
    _require(isinstance(evidence, str) and evidence.strip() != "", f"quiet {method}: evidence missing")


def _check_view(view, entry, modules) -> None:
    _require(view.isdigit(), f"view {view}: id must be a number")
    _require(isinstance(entry, dict), f"view {view}: must be an object")
    _require(("module" in entry) != ("open" in entry), f"view {view}: needs exactly one of module, open")
    if "module" in entry:
        _require(entry["module"] in modules, f"view {view}: unknown module {entry['module']}")
    else:
        _require(isinstance(entry["open"], bool), f"view {view}: open must be true or false")
        _require(isinstance(entry.get("reason"), str) and entry["reason"].strip() != "",
                 f"view {view}: a view not tied to a module needs a reason")
    _require(isinstance(entry.get("reason", ""), str), f"view {view}: reason must be text")


@dataclass(frozen=True)
class Scope:
    card_id_max: int
    city_order_max: int | None
    modules: dict
    quiet: dict
    views: dict          # view id (int) -> entry

    @classmethod
    def load(cls, path=DEFAULT_PATH) -> "Scope":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ScopeError(f"{path}: {exc}") from exc
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw) -> "Scope":
        _require(isinstance(raw, dict), "scope must be an object")
        card_max, city_max = raw.get("card_id_max"), raw.get("city_order_max", "missing")
        _require(_is_int(card_max), "card_id_max must be an integer")
        _require(city_max is None or _is_int(city_max), "city_order_max must be an integer or null")
        modules, quiet, views = raw.get("modules"), raw.get("quiet"), raw.get("views")
        for part, value in (("modules", modules), ("quiet", quiet), ("views", views)):
            _require(isinstance(value, dict), f"{part} must be an object")
        for name, entry in modules.items():
            _check_module(name, entry)
        for method, entry in quiet.items():
            _check_quiet(method, entry)
        for view, entry in views.items():
            _check_view(view, entry, modules)
        return cls(card_max, city_max, modules, quiet, {int(v): e for v, e in views.items()})

    def card_in_scope(self, c_id) -> bool:
        return int(c_id) <= self.card_id_max

    def city_order_in_scope(self, order) -> bool:
        return self.city_order_max is None or int(order) <= self.city_order_max

    def quiet_body(self, method: str) -> dict | None:
        entry = self.quiet.get(method)
        return None if entry is None else copy.deepcopy(entry["body"])

    def module_open(self, module: str) -> bool:
        return bool(self.modules.get(module, {}).get("open"))

    def closed_views(self) -> list:
        """Every view id the client must hide, for user.main_page's `inreview`."""
        def is_open(entry):
            return self.module_open(entry["module"]) if "module" in entry else entry["open"]
        return sorted(view for view, entry in self.views.items() if not is_open(entry))
