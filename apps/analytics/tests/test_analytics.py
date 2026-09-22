from __future__ import annotations

from apps.analytics.models import ListingStats, ListingView, SearchQuery
from apps.analytics.services import register_listing_view
from core.testing import APITestCase, BaseTestCase, make_listing, make_user


class RegisterListingViewTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.listing = make_listing(make_user())

    def views(self):
        return ListingStats.objects.get(listing=self.listing).views_count

    def test_one_view_per_user_per_day(self):
        user = make_user()
        register_listing_view(listing_id=self.listing.pk, user=user)
        register_listing_view(listing_id=self.listing.pk, user=user)
        register_listing_view(listing_id=self.listing.pk, user=make_user())
        self.assertEqual(self.views(), 2)
        self.assertEqual(ListingView.objects.count(), 2)
        self.assertIsNotNone(ListingStats.objects.get(listing=self.listing).last_viewed_at)

    def test_anonymous_views_are_deduplicated_by_session(self):
        register_listing_view(listing_id=self.listing.pk, session_key="s1")
        register_listing_view(listing_id=self.listing.pk, session_key="s1")
        register_listing_view(listing_id=self.listing.pk, session_key="s2")
        self.assertEqual(self.views(), 2)
        self.assertIsNone(ListingView.objects.first().user)

    def test_view_does_not_touch_listing_row(self):
        updated_at = self.listing.updated_at
        register_listing_view(listing_id=self.listing.pk, user=make_user())
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.updated_at, updated_at)


class AnalyticsApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.staff = make_user(is_staff=True)
        cls.own = make_listing(cls.owner, title="Own")
        cls.foreign = make_listing(make_user(), title="Foreign")
        ListingStats.objects.create(listing=cls.own, views_count=5)
        ListingStats.objects.create(listing=cls.foreign, views_count=9)
        for keyword, times in (("koeln", 3), ("balcony", 1)):
            for _ in range(times):
                SearchQuery.objects.create(keyword=keyword)

    def test_requires_authentication(self):
        for path in ("popular-keywords", "popular-listings"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(f"/api/analytics/{path}/").status_code, 401)

    def test_popular_keywords(self):
        self.login(self.owner)
        response = self.client.get("/api/analytics/popular-keywords/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), [{"keyword": "koeln", "total": 3}, {"keyword": "balcony", "total": 1}]
        )

    def test_owner_sees_only_own_listings(self):
        self.login(self.owner)
        data = self.client.get("/api/analytics/popular-listings/").json()
        self.assertEqual(data, [{
            "public_id": str(self.own.public_id), "title": "Own", "views_count": 5,
        }])

    def test_staff_sees_all_listings_by_popularity(self):
        self.login(self.staff)
        data = self.client.get("/api/analytics/popular-listings/").json()
        self.assertEqual([row["title"] for row in data], ["Foreign", "Own"])

    def test_search_through_api_feeds_popular_keywords(self):
        self.client.get("/api/listings/", {"search": "Köln"})
        self.login(self.owner)
        data = self.client.get("/api/analytics/popular-keywords/").json()
        self.assertEqual(data[0], {"keyword": "koeln", "total": 4})
