"""Rewards in the client's `[type, id, count]` form: decoding, rolling, granting.

The type numbers are game_util.getRewardByItemTable's. A grant changes the store, then
answers with what the client needs: a `reward` dict for the toast and a
`_client_cache_update` block, the only way new cards and items reach the client's state.
"""

import sys
from dataclasses import dataclass, field

from . import equipment
from .handlers import Refused
from .player import gain_exp
from .progression import Rules

CURRENCY_BY_TYPE = {
    1: "food", 2: "metal", 3: "energy", 4: "crystal", 9: "coin", 10: "dirt_silver",
    11: "dirt_gold", 14: "star", 15: "silver", 16: "metalcore", 17: "grace", 18: "grace_high",
    20: "adv_crystal", 21: "enchant", 23: "refine_stone", 24: "pet_crystal",
    26: "pet_exp_ball", 27: "pet_skill_stone", 33: "small_forge_stone",
    34: "middle_forge_stone", 35: "high_forge_stone", 41: "min_fate_stone",
    42: "mid_fate_stone", 43: "max_fate_stone", 100: "arena_point",
}
CARD, ITEM, EQUIP, PLAYER_EXP, ACTION_POINT, GEM = 5, 6, 7, 8, 13, 19
NOTHING = -1   # weighted lists use [-1, 0, 0, weight] for "no drop"


@dataclass
class Loot:
    """What a grant gives; built up from reward triples."""
    currencies: dict = field(default_factory=dict)
    items: dict = field(default_factory=dict)
    cards: list = field(default_factory=list)     # character ids
    equips: list = field(default_factory=list)    # equip.config ids
    gems: dict = field(default_factory=dict)      # plain gem key -> count
    player_exp: int = 0
    action_point: int = 0

    @classmethod
    def of(cls, triples) -> "Loot":
        loot = cls()
        for triple in triples:
            loot.add(*triple[:3])
        return loot

    def merge(self, other: "Loot") -> None:
        """Add everything another loot holds."""
        for key, count in other.currencies.items():
            self.currencies[key] = self.currencies.get(key, 0) + count
        for item, count in other.items.items():
            self.items[item] = self.items.get(item, 0) + count
        for key, count in other.gems.items():
            self.gems[key] = self.gems.get(key, 0) + count
        self.cards.extend(other.cards)
        self.equips.extend(other.equips)
        self.player_exp += other.player_exp
        self.action_point += other.action_point

    def add(self, kind: int, ref, count: int) -> None:
        """One reward triple; equipment becomes an equipment instance."""
        if count <= 0:
            return
        if kind in CURRENCY_BY_TYPE:
            key = CURRENCY_BY_TYPE[kind]
            self.currencies[key] = self.currencies.get(key, 0) + count
        elif kind == ITEM:
            self.items[int(ref)] = self.items.get(int(ref), 0) + count
        elif kind == CARD:
            self.cards.extend([int(ref)] * count)
        elif kind == EQUIP:
            self.equips.extend([int(ref)] * count)
        elif kind == GEM:
            self.gems[str(ref)] = self.gems.get(str(ref), 0) + count
        elif kind == PLAYER_EXP:
            self.player_exp += count
        elif kind == ACTION_POINT:
            self.action_point += count


def roll(entries, rng):
    """One entry of a weighted list `[[type, id, count, weight], ...]`, or None for no drop."""
    total = sum(e[3] for e in entries if len(e) > 3 and e[3] > 0)
    if total <= 0:
        return None
    pick = rng.uniform(0, total)
    for entry in entries:
        if len(entry) > 3 and entry[3] > 0:
            pick -= entry[3]
            if pick <= 0:
                return None if entry[0] == NOTHING else entry[:3]
    return None


def open_box(groups, rng) -> list:
    """box.config: each group draws `num` entries from its weighted `reward` list."""
    drops = []
    for group in groups:
        for _ in range(group.get("num", 0)):
            if (entry := roll(group.get("reward", []), rng)) is not None:
                drops.append(entry)
    return drops


def pay(svc, uid: str, costs: dict) -> None:
    """Spend currencies; raises Refused (rolling back the transaction) when one is short."""
    costs = {k: -int(v) for k, v in costs.items() if v}
    if costs and not svc.store.change_wallet(uid, costs):
        raise Refused("error_not_enough", "Không đủ tài nguyên.")


@dataclass(frozen=True)
class Granted:
    reward: dict          # toast dict (game_util.rewardTipsByDataTable)
    cache: dict           # _client_cache_update
    card_ids: list        # instance ids of the new cards
    equip_ids: list        # instance ids of the new equipment
    level: object         # LevelResult of the player exp, or None


def grant(svc, uid: str, loot: Loot, now: int) -> Granted:
    """Apply the loot inside one transaction and describe it for the client."""
    late = [c for c in loot.cards if not svc.scope.card_in_scope(c)]
    if late:
        # A data bug, never a player action: no config reward should lead past the cut.
        print(f"refused out-of-scope heroes {late} for player {uid}", file=sys.stderr)
        raise Refused("error_scope", "Phần thưởng không hợp lệ.")
    store = svc.store
    with store.transaction():
        if loot.equips and store.equipment_count(uid) + len(loot.equips) > equipment.EQUIP_MAX:
            raise Refused("error_equip_full",
                          f"Túi trang bị đã đầy ({equipment.EQUIP_MAX}).")
        store.change_wallet(uid, loot.currencies)
        store.change_items(uid, loot.items)
        store.change_gems(uid, loot.gems)
        card_ids = store.add_cards(uid, loot.cards)
        equip_ids = store.add_equipment(uid, loot.equips)
        if loot.action_point:
            store.change_action_point(uid, loot.action_point, now)
        level = gain_exp(svc, uid, loot.player_exp, now) if loot.player_exp else None
    reward = dict(loot.currencies)
    if loot.action_point:
        reward["action_point"] = loot.action_point
    if loot.items:
        reward["item"] = [i for i, n in loot.items.items() for _ in range(n)]
    if loot.gems:
        reward["gem"] = [key for key, n in loot.gems.items() for _ in range(n)]
    if card_ids:
        reward["cards"] = card_ids
    if equip_ids:
        reward["equip"] = equip_ids
    cache = client_cache(svc, uid, cards=card_ids, equips=equip_ids, items=loot.items,
                         gems=loot.gems)
    return Granted(reward, cache, card_ids, equip_ids, level)


def client_cache(svc, uid: str, *, cards=(), removed_cards=(), equips=(),
                 removed_equips=(), items=(), gems=()) -> dict:
    """_client_cache_update for changed cards, equipment, items and gems (`gems` is the
    keys whose stack changed). `remove` must always be present."""
    cache = {}
    if gems:
        owned = svc.store.gems(uid)
        cache["gem"] = {"_gem": {"update": {k: owned[k] for k in gems if k in owned},
                                 "remove": [k for k in gems if k not in owned]}}
    if cards or removed_cards:
        player = svc.store.player_for_uid(uid)
        rules = Rules.load(svc.configs)
        wanted = {str(c) for c in cards}
        docs = {c["id"]: rules.card_document(c, player["level"])
                for c in svc.store.cards_for_player(uid) if c["id"] in wanted}
        equipment.add_bound_equipment(svc.configs, svc.store.equipment_rows(uid), docs)
        cache["cards"] = {"cards": {"update": docs, "remove": [str(c) for c in removed_cards]}}
    if equips or removed_equips:
        wanted = {str(e) for e in equips}
        docs = {e["id"]: equipment.document(e) for e in svc.store.equipment_rows(uid)
                if e["id"] in wanted}
        cache["equip"] = {"_equip": {"update": docs,
                                     "remove": [str(e) for e in removed_equips]}}
    if items:
        owned = svc.store.items(uid)
        details = svc.configs.get("item")
        update = {}
        for item_id in items:
            count = owned.get(int(item_id), 0)
            if count:
                stack = details.get(str(item_id), {}).get("stack") or count
                update[str(item_id)] = [min(stack, count - i) for i in range(0, count, stack)]
        removed = [str(i) for i in items if not owned.get(int(i))]
        cache["item"] = {"items": {"update": update, "remove": removed}}
    return cache


def merge_cache(*caches) -> dict:
    """Combine cache blocks; later card/item updates win, removals accumulate."""
    merged = {}
    for cache in caches:
        for key, inner in (("cards", "cards"), ("equip", "_equip"), ("item", "items"),
                           ("gem", "_gem")):
            if key not in cache:
                continue
            block = merged.setdefault(key, {inner: {"update": {}, "remove": []}})[inner]
            block["update"].update(cache[key][inner]["update"])
            block["remove"].extend(r for r in cache[key][inner]["remove"] if r not in block["remove"])
    return merged
