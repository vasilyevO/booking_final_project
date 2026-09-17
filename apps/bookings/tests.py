from django.core import mail
from django.test import TestCase


class BookingEmailTests(TestCase):
    """
    RU: on_commit НЕ срабатывает внутри TestCase: каждый тест обёрнут в
        транзакцию, которая откатывается, а не коммитится. Без
        captureOnCommitCallbacks письмо не отправится, mail.outbox останется
        пустым, и ошибку будешь искать в сигнале, которой там нет.
    EN: on_commit does NOT fire inside a TestCase: every test runs in a
        transaction that is rolled back, never committed. Without
        captureOnCommitCallbacks no email is sent, mail.outbox stays empty,
        and you end up hunting a bug in the signal that is not there.
    """

    def test_booking_creation_sends_two_emails(self):
        with self.captureOnCommitCallbacks(execute=True):
            create_booking(
                tenant=self.tenant,
                listing_id=self.listing.pk,
                start_date=self.tomorrow,
                end_date=self.day_after,
            )

        # RU: письма арендатору и владельцу
        # EN: one email to the tenant, one to the owner
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn(self.tenant.email, mail.outbox[0].recipients())