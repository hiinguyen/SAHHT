"""Rewards in the client's `[type, id, count]` form: decoding, rolling, granting.

The type numbers are game_util.getRewardByItemTable's. A grant changes the store, then
answers with what the client needs: a `reward` dict for the toast and a
`_client_cache_update` block, the only way new cards and items reach the client's state.
"""

from dataclasses import dataclass, field

from .handlers import Refused
from .player import gain_exp
from .progression import Rules

CURRENCY_BY_TYPE = {
    1: "food", 2: "metal", 3: "energy", 4: "crystal", 9: "coin", 10: "dirt_silver",
    11: "dirt_gold", 14: "star", 15: "silver", 16: "metalcore", 17: "grace", 18: "grace_high",
    20: "adv_crystal", 23: "refine_stone", 24: "pet_crystal", 26: "pet_exp_ball",
    27: "pet_skill_stone", 100: "arena_point",
}
CARD, ITEM, EQUIP, PLAYER_EXP, ACTION_POINT = 5, 6, 7, 8, 13
NOTHING = -1   # weighted lists use [-1, 0, 0, weight] for "no drop"


@dataclass
class Loot:
    """What a grant gives; built up from reward triples."""
    currencies: dict = field(default_factory=dict)
    items: dict = field(default_factory=dict)
    cards: list = field(default_factory=list)     # character ids
    player_exp: int = 0
    action_point: int = 0

    @classmethod
    def of(cls, triples) -> "Loot":
        loot = cls()
        for triple in triples:
            loot.add(*triple[:3])
        return loot

    def add(self, kind: int, ref, count: int) -> None:
        """One reward triple. Equipment (type 7) has no system yet and is not granted."""
        if count <= 0:
            return
        if kind in CURRENCY_BY_TYPE:
            key = CURRENCY_BY_TYPE[kind]
            self.currencies[key] = self.currencies.get(key, 0) + count
        elif kind == ITEM:
            self.items[int(ref)] = self.items.get(int(ref), 0) + count
        elif kind == CARD:
            self.cards.extend([int(ref)] * count)
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
    level: object         # LevelResult of the player exp, or None


def grant(svc, uid: str, loot: Loot, now: int) -> Granted:
    """Apply the loot inside one transaction and describe it for the client."""
    store = svc.store
    with store.transaction():
        store.change_wallet(uid, loot.currencies)
        store.change_items(uid, loot.items)
        card_ids = store.add_cards(uid, loot.cards)
        if loot.action_point:
            store.change_action_point(uid, loot.action_point, now)
        level = gain_exp(svc, uid, loot.player_exp, now) if loot.player_exp else None
    reward = dict(loot.currencies)
    if loot.action_point:
        reward["action_point"] = loot.action_point
    if loot.items:
        reward["item"] = [i for i, n in loot.items.items() for _ in range(n)]
    if card_ids:
        reward["cards"] = card_ids
    cache = client_cache(svc, uid, cards=card_ids, items=loot.items)
    return Granted(reward, cache, card_ids, level)


def client_cache(svc, uid: str, *, cards=(), removed_cards=(), items=()) -> dict:
    """_client_cache_update for changed cards and items. `remove` must always be present."""
    cache = {}
    if cards or removed_cards:
        player = svc.store.player_for_uid(uid)
        rules = Rules.load(svc.configs)
        wanted = {str(c) for c in cards}
        docs = {c["id"]: rules.card_document(c, player["level"])
                for c in svc.store.cards_for_player(uid) if c["id"] in wanted}
        cache["cards"] = {"cards": {"update": docs, "remove": [str(c) for c in removed_cards]}}
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
        for key, inner in (("cards", "cards"), ("item", "items")):
            if key not in cache:
                continue
            block = merged.setdefault(key, {inner: {"update": {}, "remove": []}})[inner]
            block["update"].update(cache[key][inner]["update"])
            block["remove"].extend(r for r in cache[key][inner]["remove"] if r not in block["remove"])
    return merged
