"""Mail (notify.*): inbox, claiming, claim-all, the red dot and the welcome mail."""

import time
import unittest

from sahht_server import mail
from tests.test_gameplay import PlayerCase


class MailCase(PlayerCase):
    def send(self, content="hello", gift=(), **kwargs):
        svc = self.server.services
        with svc.store.transaction():
            return mail.send(svc, self.uid, content, gift, **kwargs)

    def inbox(self):
        return self.call("notify.messages")["data"]["messages"]


class InboxTests(MailCase):
    def test_new_player_gets_the_welcome_mail_once(self):
        messages = self.inbox()
        self.assertEqual([m["send_name"] for m in messages], ["sys"])
        self.assertTrue(messages[0]["gift"])
        self.assertIsNone(self.send(key="welcome"))

    def test_messages_carry_every_field_the_client_reads_newest_first(self):
        first = self.send("one\nsecond line", [[9, 0, 5]], title="T")
        second = self.send("two")
        messages = self.inbox()
        self.assertEqual([m["id"] for m in messages][:2], [str(second), str(first)])
        top = messages[1]
        self.assertEqual((top["content"], top["gift"], top["send_name"], top["title"]),
                         ("one\nsecond line", [[9, 0, 5]], "sys", "T"))

    def test_expired_mail_is_not_listed(self):
        self.send("old", ttl_days=0)
        self.assertNotIn("old", [m["content"] for m in self.inbox()])

    def test_red_dot_follows_unclaimed_mail(self):
        page = self.call("user.main_page")["data"]
        self.assertIs(page["alerts"]["notify"], True)
        self.call("notify.auto_read", message_id="|".join(m["id"] for m in self.inbox()))
        self.assertIs(self.call("user.main_page")["data"]["alerts"]["notify"], False)


class ClaimTests(MailCase):
    def setUp(self):
        super().setUp()
        self.call("notify.auto_read", message_id="|".join(m["id"] for m in self.inbox()))

    def test_read_grants_the_gift_and_returns_the_rest(self):
        keep = self.send("keep")
        mail_id = self.send("pay", [[9, 0, 300]])
        coin = self.call("user.main_page")["user_status"]["coin"]
        body = self.call("notify.read", message_id=str(mail_id))
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], coin + 300)
        self.assertEqual(body["data"]["reward"]["coin"], 300)
        self.assertEqual([m["id"] for m in body["data"]["messages"]], [str(keep)])

    def test_mail_without_a_gift_is_removed_by_read(self):
        mail_id = self.send("notice")
        body = self.call("notify.read", message_id=str(mail_id))
        self.assertEqual((body["status"], body["data"]["messages"]), (0, []))

    def test_claiming_twice_or_a_stranger_mail_is_refused(self):
        mail_id = self.send("once", [[9, 0, 1]])
        self.call("notify.read", message_id=str(mail_id))
        self.assertEqual(self.call("notify.read", message_id=str(mail_id))["status"], "error_param")
        self.assertEqual(self.call("notify.read", message_id="999")["status"], "error_param")
        self.assertEqual(self.call("notify.read", message_id="x")["status"], "error_param")

    def test_auto_read_claims_a_page_and_skips_unknown_ids(self):
        ids = [self.send(f"m{i}", [[9, 0, 10]]) for i in range(3)]
        coin = self.call("user.main_page")["user_status"]["coin"]
        body = self.call("notify.auto_read",
                         message_id="|".join(map(str, ids + [999, ids[0]])))
        self.assertEqual(body["data"]["reward"]["coin"], 30)
        self.assertEqual(body["user_status"]["coin"], coin + 30)
        self.assertEqual(body["data"]["messages"], [])

    def test_a_failed_grant_keeps_the_mail(self):
        mail_id = self.send("heroes", [[5, 99999, 1]])   # out of scope: grant refuses
        self.assertNotEqual(self.call("notify.read", message_id=str(mail_id))["status"], 0)
        self.assertEqual([m["id"] for m in self.inbox()], [str(mail_id)])


if __name__ == "__main__":
    unittest.main()
