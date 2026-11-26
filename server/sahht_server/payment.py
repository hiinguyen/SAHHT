"""Free recharge: payment.use_ticket and the VIP screen's shop.vip_buy_step.

The Vietnamese client has no payment gateway. ui_vip builds an order id
`<uid>_<server>_<pack>_<time>_<channel>`, native_helper.buyProduct appends `_<random>`
and sends it as cpOrderId once the player confirms paying in gold tickets. Tickets are
free here (player.FREE_TICKETS), so a purchase only grants the pack.
"""

import time

from . import grow_plan, welfare
from .handlers import Request, Services, fail, is_int, ok

ORDER_FIELDS = 4   # uid, server, pack, then the rest (time, channel, random)


def parse_order(cp_order_id: str):
    """(uid, charge.config key), or None for a malformed order id."""
    parts = cp_order_id.split("_", ORDER_FIELDS - 1)
    if len(parts) != ORDER_FIELDS:
        return None
    uid, server, pack, rest = parts
    if not (uid.isascii() and uid.isdigit() and server and is_int(pack) and rest):
        return None
    return uid, pack


def use_ticket(req: Request, svc: Services, player: dict):
    order_id = req.params.get("cpOrderId", "")
    parsed = parse_order(order_id)
    if parsed is None or parsed[0] != player["uid"]:
        return fail("error_param", "Mã đơn nạp không hợp lệ.")
    pack_id = parsed[1]
    pack = svc.configs.get("charge").get(pack_id)
    if pack is None:
        return fail("error_param", "Gói nạp không tồn tại.")
    is_growth_plan = pack_id == grow_plan.PACK_ID
    if not is_growth_plan and (pack.get("open_gift") or pack.get("is_show") != 1):
        # Monthly and weekly cards and voucher packs carry rewards of their own that no
        # system grants yet (roadmap phase 1). The growth plan has its own module.
        return fail("error_not_open", "Gói này chưa mở.")
    uid = player["uid"]
    with svc.store.transaction():
        if svc.store.payment_exists(order_id):
            return ok()   # the client resent an order that was already paid
        refusal = grow_plan.refuse_purchase(svc, uid) if is_growth_plan else None
        if refusal:
            return refusal
        bought = svc.store.payment_counts(uid).get(pack_id, 0)
        if pack.get("buy_times", 0) and bought >= pack["buy_times"]:
            return fail("error_buy_times", "Gói này đã mua đủ số lần.")
        coin = pack.get("coin", 0) + pack.get("gift_coin", 0)
        if pack.get("is_double") == 1 and bought == 0:
            coin += pack.get("coin", 0)   # "Nạp tiền lần đầu tặng <coin> Xu"
        svc.store.record_payment(uid, order_id, pack_id, int(time.time()))
        svc.store.change_wallet(uid, {"coin": coin, "vip_exp": pack.get("vip_exp", 0)})
        welfare.record_recharge(svc, uid, coin, int(time.time()))
        if is_growth_plan:
            grow_plan.activate(svc, uid)
    return ok()


BUYABLE = 2   # ui_vip onCellBtnClick: only 2 sends the purchase; anything else shows a
              # local "not finished claiming" tip and never asks the server


def vip_buy_step(req: Request, svc: Services, player: dict):
    """ui_vip counts `step` (VIP gift packs bought: none until the VIP shop exists) and
    walks `double_pay` with #, comparing to numeric pack ids. The monthly and weekly
    cards are reported buyable so a tap reaches use_ticket, which answers that the
    pack is not open yet instead of the client's misleading tip."""
    bought = svc.store.payment_counts(player["uid"])
    return ok({"step": [], "double_pay": sorted(int(p) for p in bought),
               "month_award": BUYABLE, "week_award": BUYABLE})


HANDLERS = {
    ("api", "payment.use_ticket"): use_ticket,
    ("api", "shop.vip_buy_step"): vip_buy_step,
}
