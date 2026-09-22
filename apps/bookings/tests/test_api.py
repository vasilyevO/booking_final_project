from __future__ import annotations

from datetime import timedelta

from django.test import override_settings

from apps.bookings.models import Booking, BookingStatus
from core.testing import APITestCase, make_booking, make_listing, make_user, today

LIST_URL = "/api/bookings/"


def action_url(booking, action):
    return f"{LIST_URL}{booking.public_id}/{action}/"


class BookingCreateApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")
        cls.listing = make_listing(cls.owner)

    def payload(self, **overrides):
        data = {
            "listing": str(self.listing.public_id),
            "start_date": str(today() + timedelta(days=5)),
            "end_date": str(today() + timedelta(days=7)),
            "guests": 2,
        }
        data.update(overrides)
        return data

    def test_anonymous_is_rejected(self):
        self.assertEqual(self.client.post(LIST_URL, self.payload(), format="json").status_code, 401)

    def test_tenant_creates_booking(self):
        self.login(self.tenant)
        response = self.client.post(LIST_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["status"], BookingStatus.PENDING)
        self.assertEqual(body["nights"], 2)
        self.assertEqual(body["tenant_email"], self.tenant.email)
        self.assertEqual(body["listing_public_id"], str(self.listing.public_id))
        self.assertEqual(body["total_price"], "200.00")

    def test_client_cannot_set_price_or_status(self):
        self.login(self.tenant)
        response = self.client.post(
            LIST_URL, self.payload(total_price="1.00", status="confirmed"), format="json"
        )
        self.assertEqual(response.json()["total_price"], "200.00")
        self.assertEqual(response.json()["status"], BookingStatus.PENDING)

    def test_overlapping_dates_are_400(self):
        make_booking(self.listing, make_user(), start_offset=4, nights=3)
        self.login(self.tenant)
        response = self.client.post(LIST_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 400)

    def test_dates_in_the_past_are_400(self):
        self.login(self.tenant)
        response = self.client.post(
            LIST_URL,
            self.payload(start_date=str(today() - timedelta(days=2)), end_date=str(today())),
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_end_before_start_is_400(self):
        self.login(self.tenant)
        response = self.client.post(
            LIST_URL, self.payload(end_date=str(today() + timedelta(days=5))), format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_too_many_guests_is_400(self):
        self.login(self.tenant)
        self.assertEqual(
            self.client.post(LIST_URL, self.payload(guests=50), format="json").status_code, 400
        )

    def test_inactive_listing_is_400(self):
        hidden = make_listing(self.owner, is_active=False)
        self.login(self.tenant)
        response = self.client.post(
            LIST_URL, self.payload(listing=str(hidden.public_id)), format="json"
        )
        self.assertEqual(response.status_code, 400)


class BookingVisibilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")
        cls.stranger = make_user(group="tenants")
        cls.staff = make_user(is_staff=True)
        cls.booking = make_booking(make_listing(cls.owner), cls.tenant)

    def ids(self):
        return [item["public_id"] for item in self.client.get(LIST_URL).json()["results"]]

    def test_anonymous_list_is_401(self):
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)

    def test_participants_and_staff_see_booking(self):
        for user in (self.tenant, self.owner, self.staff):
            with self.subTest(user=user.email):
                self.login(user)
                self.assertEqual(self.ids(), [str(self.booking.public_id)])
                self.assertEqual(
                    self.client.get(f"{LIST_URL}{self.booking.public_id}/").status_code, 200
                )

    def test_stranger_sees_nothing(self):
        self.login(self.stranger)
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.client.get(f"{LIST_URL}{self.booking.public_id}/").status_code, 404)

    def test_there_is_no_update_or_delete(self):
        self.login(self.tenant)
        url = f"{LIST_URL}{self.booking.public_id}/"
        self.assertEqual(self.client.patch(url, {"guests": 3}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)


class BookingTransitionApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")
        cls.listing = make_listing(cls.owner)

    def setUp(self):
        super().setUp()
        self.booking = make_booking(self.listing, self.tenant, start_offset=10)

    def post(self, user, action, booking=None):
        self.login(user)
        return self.client.post(action_url(booking or self.booking, action))

    def status(self):
        self.booking.refresh_from_db()
        return self.booking.status

    def test_owner_confirms(self):
        response = self.post(self.owner, "confirm")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], BookingStatus.CONFIRMED)
        self.assertEqual(self.status(), BookingStatus.CONFIRMED)

    def test_owner_rejects(self):
        self.assertEqual(self.post(self.owner, "reject").status_code, 200)
        self.assertEqual(self.status(), BookingStatus.REJECTED)

    def test_tenant_cannot_confirm_or_reject(self):
        self.assertEqual(self.post(self.tenant, "confirm").status_code, 403)
        self.assertEqual(self.post(self.tenant, "reject").status_code, 403)
        self.assertEqual(self.status(), BookingStatus.PENDING)

    def test_both_parties_may_cancel(self):
        self.assertEqual(self.post(self.tenant, "cancel").status_code, 200)
        self.assertEqual(self.status(), BookingStatus.CANCELLED)

        other = make_booking(self.listing, make_user(), start_offset=20)
        self.assertEqual(self.post(self.owner, "cancel", other).status_code, 200)

    def test_stranger_cannot_act(self):
        stranger = make_user(group="landlords")
        for action in ("confirm", "reject", "cancel"):
            with self.subTest(action=action):
                self.assertEqual(self.post(stranger, action).status_code, 404)

    def test_invalid_transition_is_400(self):
        self.post(self.owner, "reject")
        response = self.post(self.owner, "confirm")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.status(), BookingStatus.REJECTED)

    @override_settings(BOOKING_CANCELLATION_DAYS=30)
    def test_cancel_after_deadline_is_400(self):
        response = self.post(self.tenant, "cancel")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.status(), BookingStatus.PENDING)

    def test_confirmed_booking_can_be_cancelled(self):
        self.post(self.owner, "confirm")
        self.assertEqual(self.post(self.tenant, "cancel").status_code, 200)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).status, BookingStatus.CANCELLED)


class BookingGroupPermissionTests(APITestCase):
    """
    RU: Групповые права на действия с бронью. Объектные проверки (чья бронь)
        существовали и раньше, а права групп из init_groups не применялись.
    EN: Group permissions for booking actions. The object-level checks
        (whose booking) already existed; the group permissions granted by
        init_groups were never enforced.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.other_landlord = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")
        cls.no_group = make_user()
        cls.listing = make_listing(cls.owner)

    def payload(self):
        return {
            "listing": str(self.listing.public_id),
            "start_date": str(today() + timedelta(days=20)),
            "end_date": str(today() + timedelta(days=22)),
            "guests": 1,
        }

    def test_user_without_group_cannot_book(self):
        self.login(self.no_group)
        response = self.client.post(LIST_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 403)

    def test_pure_landlord_cannot_book_someone_elses_listing(self):
        # RU: запрет своего жилья проверяет clean(); здесь чужое жильё —
        #     отказ должен прийти от группового права, а не от clean()
        # EN: the own-listing ban lives in clean(); this is someone else's
        #     listing — the refusal must come from the group permission
        self.login(self.other_landlord)
        response = self.client.post(LIST_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Booking.objects.filter(tenant=self.other_landlord).exists())

    def test_landlord_who_is_also_tenant_can_book(self):
        from django.contrib.auth.models import Group

        both = make_user(group="landlords")
        both.groups.add(Group.objects.get(name="tenants"))
        # RU: свежий объект — has_perm кэширует права на экземпляре
        # EN: a fresh instance — has_perm caches permissions on the object
        both = type(both).objects.get(pk=both.pk)
        self.login(both)
        response = self.client.post(LIST_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 201)

    def test_tenant_cannot_confirm_even_via_api(self):
        booking = make_booking(self.listing, self.tenant, start_offset=30)
        self.login(self.tenant)
        self.assertEqual(self.client.post(action_url(booking, "confirm")).status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.PENDING)

    def test_owner_can_cancel_their_listings_booking(self):
        # RU: у landlords раньше не было cancel_booking — с включённой
        #     проверкой прав владелец потерял бы возможность отмены
        # EN: landlords used to lack cancel_booking — with enforcement on,
        #     the owner would have lost the ability to cancel
        booking = make_booking(self.listing, self.tenant, start_offset=30)
        self.login(self.owner)
        response = self.client.post(action_url(booking, "cancel"))
        self.assertEqual(response.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.CANCELLED)
