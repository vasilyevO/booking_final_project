# apps/listings/management/commands/seed_demo.py
"""
Populates the database with demo data using Faker.

    python manage.py seed_demo --flush
    python manage.py seed_demo --landlords 8 --tenants 25 --listings 40 --seed 42
    python manage.py seed_demo --languages de,ru
"""
from __future__ import annotations

import io
import random
from datetime import datetime, time, timedelta
from itertools import cycle
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from djmoney.money import Money
from faker import Faker

from apps.analytics.models import ListingStats, ListingView, SearchQuery
from apps.bookings.models import Booking, BookingStatus
from apps.listings.models import Listing, ListingPhoto, PropertyType
from apps.reviews.models import Review
from apps.users.models import User

# every demo account lives on one domain — that is the only marker --flush
# uses to decide what may be deleted, so real users are never touched.
DEMO_DOMAIN = "demo.local"
DEMO_PASSWORD = "demo-pass-2024"

# a fixed city list rather than faker.city(): real German spellings with
# umlauts are needed to exercise city_normalized.
CITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Köln", ("Altstadt", "Ehrenfeld", "Nippes", "Sülz")),
    ("München", ("Schwabing", "Haidhausen", "Sendling")),
    ("Berlin", ("Mitte", "Kreuzberg", "Prenzlauer Berg", "Neukölln")),
    ("Hamburg", ("Altona", "St. Pauli", "Eimsbüttel")),
    ("Düsseldorf", ("Bilk", "Oberkassel", "Flingern")),
    ("Frankfurt am Main", ("Bornheim", "Sachsenhausen")),
    ("Stuttgart", ("West", "Bad Cannstatt")),
    ("Leipzig", ("Plagwitz", "Südvorstadt")),
)

# titles are built from templates: faker.sentence() produces nonsense that
# makes it impossible to tell whether search works.
TITLE_TEMPLATES = {
    "en": "{adj} {kind} with {feature} in {district}",
    "de": "{adj} {kind} mit {feature} in {district}",
    "ru": "{adj} {kind} с {feature}, {district}",
}
WORDS = {
    "en": {
        "adj": ("Bright", "Cosy", "Spacious", "Quiet", "Modern", "Charming"),
        "kind": {
            PropertyType.APARTMENT: "apartment", PropertyType.HOUSE: "house",
            PropertyType.STUDIO: "studio", PropertyType.ROOM: "room",
        },
        "feature": ("a balcony", "a river view", "a garden", "a fireplace", "parking"),
        "extra": (
            "Fully equipped kitchen, fast Wi-Fi and a washing machine.",
            "Two minutes from the underground, supermarkets around the corner.",
            "Quiet backyard, no traffic noise at night.",
            "Freshly renovated, new furniture throughout.",
        ),
    },
    "de": {
        "adj": ("Helle", "Gemütliche", "Geräumige", "Ruhige", "Moderne", "Charmante"),
        "kind": {
            PropertyType.APARTMENT: "Wohnung", PropertyType.HOUSE: "Haus",
            PropertyType.STUDIO: "Studio", PropertyType.ROOM: "Zimmer",
        },
        "feature": ("Balkon", "Rheinblick", "Garten", "Kamin", "Stellplatz"),
        "extra": (
            "Voll ausgestattete Küche, schnelles WLAN und Waschmaschine.",
            "Zwei Minuten zur U-Bahn, Supermärkte um die Ecke.",
            "Ruhiger Hinterhof, nachts kein Verkehrslärm.",
            "Frisch renoviert, komplett neue Möbel.",
        ),
    },
    "ru": {
        "adj": ("Светлая", "Уютная", "Просторная", "Тихая", "Современная", "Милая"),
        "kind": {
            PropertyType.APARTMENT: "квартира", PropertyType.HOUSE: "дом",
            PropertyType.STUDIO: "студия", PropertyType.ROOM: "комната",
        },
        "feature": ("балконом", "видом на реку", "садом", "камином", "парковкой"),
        "extra": (
            "Полностью оборудованная кухня, быстрый Wi-Fi и стиральная машина.",
            "Две минуты до метро, супермаркеты за углом.",
            "Тихий двор, ночью не слышно машин.",
            "После свежего ремонта, вся мебель новая.",
        ),
    },
}

REVIEW_TEXTS = {
    5: ("Perfect stay, exactly as described.", "Great host, spotless flat, would come back."),
    4: ("Very good overall, only the shower was a bit weak.", "Nice place, slightly noisy street."),
    3: ("Fine for the price, nothing special.", "Average. Clean, but the furniture is tired."),
    2: ("Photos are nicer than reality. Check-in took ages.", "Too cold, heating barely worked."),
    1: ("Not as advertised, would not book again.", "Dirty kitchen and no hot water."),
}

SEARCH_NOISE = ("balcony", "garden", "zentrum", "studio", "cheap", "wifi", "parking", "ruhig")


def _aware(day, hour: int = 12) -> datetime:
    """
    A date into an aware datetime in the current timezone — with USE_TZ=True
    a naive value raises a RuntimeWarning and lands in the database as UTC.
    """
    return timezone.make_aware(datetime.combine(day, time(hour=hour)))


class Command(BaseCommand):
    """
    Creates a coherent demo dataset: users in groups, listings with
    translations and photos, bookings across the whole status timeline,
    reviews on completed bookings, and analytics rows.
    """

    help = "Populate the database with Faker-generated demo data"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--landlords", type=int, default=6)
        parser.add_argument("--tenants", type=int, default=20)
        parser.add_argument("--listings", type=int, default=30)
        parser.add_argument(
            "--bookings-per-listing", type=int, default=4,
            help="Upper bound; the actual count varies per listing",
        )
        parser.add_argument(
            "--seed", type=int, default=2024,
            help="Random seed — the same seed produces the same dataset",
        )
        parser.add_argument(
            "--flush", action="store_true",
            help=f"Delete every object owned by @{DEMO_DOMAIN} accounts first",
        )
        parser.add_argument(
            "--no-photos", action="store_true",
            help="Skip image generation (faster, writes no files to MEDIA_ROOT)",
        )
        # demo users' languages come from an argument, so profiles need no
        # manual fixing in the shell after every database recreation.
        # Booking emails go out in the recipient's language, so the
        # difference is visible immediately.
        parser.add_argument(
            "--languages", default="en,de,ru",
            help="Comma-separated language codes spread round-robin across demo users",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        # seed both generators — otherwise a rerun yields a different database
        self.rng = random.Random(options["seed"])
        self.fake = Faker("de_DE")
        Faker.seed(options["seed"])

        self.language_cycle = self._language_cycle(options["languages"])

        if options["flush"]:
            self._flush()

        # groups and exchange rates are preconditions, not data. Without the
        # rates, price_base is computed against an empty Rate table and
        # silently stays in the original currency.
        call_command("init_groups", verbosity=0)
        # update_rates prints its result regardless of verbosity
        call_command("update_rates", verbosity=0, stdout=io.StringIO())

        landlords = self._create_users(options["landlords"], "landlords")
        tenants = self._create_users(options["tenants"], "tenants")
        if not landlords or not tenants:
            raise CommandError("Need at least one landlord and one tenant")

        listings = self._create_listings(options["listings"], landlords)
        if not options["no_photos"]:
            self._create_photos(listings)

        bookings = self._create_bookings(listings, tenants, options["bookings_per_listing"])
        reviews = self._create_reviews(bookings)
        views = self._create_analytics(listings, tenants)

        self._report(landlords, tenants, listings, bookings, reviews, views)

    # -------------------------------------------------------------- languages

    def _language_cycle(self, raw: str):
        """
        Validates the codes against settings.LANGUAGES and returns an
        endless iterator. The check matters because User.language declares
        choices, and those only apply in full_clean(); get_or_create never
        calls it, so a typo such as "du" would be stored silently and fail
        later — inside override() when an email is sent.
        """
        codes = [code.strip() for code in raw.split(",") if code.strip()]
        if not codes:
            raise CommandError("--languages must list at least one code")

        known = {code for code, _name in settings.LANGUAGES}
        unknown = sorted(set(codes) - known)
        if unknown:
            raise CommandError(
                f"Unknown language codes: {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(known))}"
            )

        # cycle hands out languages round-robin: landlord1 -> en,
        # landlord2 -> de, landlord3 -> ru, landlord4 -> en. Tenants
        # continue the same sequence, so the two parties of a booking
        # almost always end up in different languages.
        return cycle(codes)

    # ------------------------------------------------------------------ flush

    def _flush(self) -> None:
        """
        Deletes demo data in reverse dependency order: almost every relation
        is PROTECT, so an arbitrary order fails. all_objects is used because
        the default manager hides soft-deleted rows, which would otherwise
        survive the cleanup.
        """
        users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        listings = Listing.all_objects.filter(owner__in=users)
        reviews = Review.all_objects.filter(listing__in=listings)
        bookings = Booking.objects.filter(listing__in=listings)

        # simple-history keeps its own tables with no FK to the originals —
        # a cascade misses them, so clear them explicitly once the rows are
        # gone (each delete writes one more history record). They are
        # matched by id: history_user is empty for rows written outside a
        # request, which is how the seeder writes them.
        history = {
            Listing: list(listings.values_list("id", flat=True)),
            Booking: list(bookings.values_list("id", flat=True)),
            Review: list(reviews.values_list("id", flat=True)),
        }

        reviews.delete()
        ListingView.objects.filter(listing__in=listings).delete()
        ListingStats.objects.filter(listing__in=listings).delete()
        SearchQuery.objects.filter(user__in=users).delete()
        bookings.delete()
        ListingPhoto.objects.filter(listing__in=listings).delete()
        removed = listings.delete()[0] + users.delete()[0]

        for model, ids in history.items():
            model.history.model.objects.filter(id__in=ids).delete()
        self.stdout.write(self.style.WARNING(f"flushed: {removed} rows"))

    # ------------------------------------------------------------------ users

    def _create_users(self, count: int, group_name: str) -> list[User]:
        """
        Creates users and assigns them to role groups. The password is
        shared: this is demo data, not real accounts.
        """
        group = Group.objects.get(name=group_name)
        users: list[User] = []

        for index in range(count):
            # the index guarantees uniqueness — faker repeats names while
            # the model declares email unique.
            email = f"{group_name[:-1]}{index + 1}@{DEMO_DOMAIN}"
            language = next(self.language_cycle)
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": self.fake.first_name(),
                    "last_name": self.fake.last_name(),
                    "phone": self.fake.numerify("+49 1## #######"),
                    "language": language,
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
            else:
                # get_or_create leaves existing rows untouched, so the
                # language is updated explicitly — otherwise a rerun with a
                # different --languages would change nothing.
                user.language = language
                user.save(update_fields=["language"])
            user.groups.add(group)
            users.append(user)

        self.stdout.write(f"{group_name}: {len(users)}")
        return users

    # --------------------------------------------------------------- listings

    def _create_listings(self, count: int, landlords: list[User]) -> list[Listing]:
        """
        Listings in all three languages at once. title_en/de/ru are written
        explicitly: assigning to title fills only the active language's
        column, while FULLTEXT search queries the request language's column.
        """
        listings: list[Listing] = []

        for _ in range(count):
            city, districts = self.rng.choice(CITIES)
            district = self.rng.choice(districts)
            property_type = self.rng.choice(PropertyType.values)
            rooms = 1 if property_type == PropertyType.STUDIO else self.rng.randint(1, 5)

            # 80% in EUR — otherwise a "cheaper than 100 EUR" query stops
            # being representative. The other currencies are there to show
            # price_base and the frozen rate at work.
            currency = "EUR" if self.rng.random() < 0.8 else self.rng.choice(
                [c for c in settings.CURRENCIES if c != "EUR"]
            )
            amount = Decimal(self.rng.randrange(3500, 26000, 50)) / 100

            listing = Listing(
                owner=self.rng.choice(landlords),
                city=city,
                district=district,
                address=f"{self.fake.street_name()} {self.rng.randint(1, 180)}",
                postal_code=self.fake.postcode(),
                price_per_night=Money(amount, currency),
                rooms=rooms,
                property_type=property_type,
                # some listings are unpublished — the feed must hide them
                is_active=self.rng.random() > 0.12,
                created_at=timezone.now() - timedelta(days=self.rng.randint(1, 400)),
            )
            for lang in ("en", "de", "ru"):
                title, description = self._text(lang, property_type, district, rooms)
                setattr(listing, f"title_{lang}", title)
                setattr(listing, f"description_{lang}", description)

            # full_clean() inside ValidatedModel.save() runs exactly as on a
            # live request — the seeder exercises the model, not bypasses it.
            listing.save()
            listings.append(listing)

        self.stdout.write(f"listings: {len(listings)}")
        return listings

    def _text(self, lang: str, property_type: str, district: str, rooms: int) -> tuple[str, str]:
        """
        Title and description in a single language.
        """
        words = WORDS[lang]
        title = TITLE_TEMPLATES[lang].format(
            adj=self.rng.choice(words["adj"]),
            kind=words["kind"][property_type],
            feature=self.rng.choice(words["feature"]),
            district=district,
        )
        description = " ".join(
            (
                title + ".",
                self.rng.choice(words["extra"]),
                self.rng.choice(words["extra"]),
                f"{rooms} / {district}.",
            )
        )
        return title[:200], description

    # ----------------------------------------------------------------- photos

    def _create_photos(self, listings: list[Listing]) -> int:
        """
        Generates images with Pillow instead of shipping files: the fixture
        stays self-contained and the repository carries no binaries.
        position is a multiple of 10 — the same step as services.reorder_photos.
        """
        from PIL import Image, ImageDraw

        created = 0
        for listing in listings:
            for index in range(self.rng.randint(1, 4)):
                colour = (
                    self.rng.randint(60, 200),
                    self.rng.randint(60, 200),
                    self.rng.randint(60, 200),
                )
                image = Image.new("RGB", (800, 600), colour)
                ImageDraw.Draw(image).text(
                    (30, 30),
                    f"{listing.city}\n{listing.property_type}\n#{index + 1}",
                    fill=(255, 255, 255),
                )
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=70)

                photo = ListingPhoto(
                    listing=listing,
                    caption_en=f"View {index + 1}",
                    caption_de=f"Ansicht {index + 1}",
                    caption_ru=f"Вид {index + 1}",
                    position=(index + 1) * 10,
                )
                # save=False — the row does not exist yet; the filename is
                # built by listing_photo_path from listing_id and a UUID.
                photo.image.save(
                    f"demo_{index + 1}.jpg", ContentFile(buffer.getvalue()), save=False
                )
                photo.save()
                created += 1

        self.stdout.write(f"photos: {created}")
        return created

    # --------------------------------------------------------------- bookings

    def _create_bookings(
        self, listings: list[Listing], tenants: list[User], per_listing: int
    ) -> list[Booking]:
        """
        Bookings are laid out on one timeline per listing, the cursor moving
        from past to future — so the intervals provably never overlap and
        the "dates taken" check rejects nothing.
        """
        today = timezone.localdate()
        bookings: list[Booking] = []

        for listing in listings:
            # an owner cannot book their own property — the rule of
            # validate_not_own_listing, and the data must obey it.
            candidates = [t for t in tenants if t.pk != listing.owner_id]
            if not candidates:
                continue
            cursor = today - timedelta(days=self.rng.randint(150, 240))
            count = self.rng.randint(1, per_listing)
            # some bookings must lie in the future, otherwise the pending
            # and confirmed statuses never appear: _status_for derives them
            # from the dates.
            first_future = self.rng.randint(0, count - 1)

            for index in range(count):
                if index == first_future and cursor < today:
                    cursor = today - timedelta(days=self.rng.randint(0, 4))
                cursor += timedelta(days=self.rng.randint(2, 20))
                start = cursor
                end = cursor + timedelta(days=self.rng.randint(2, 12))
                cursor = end

                bookings.append(
                    self._make_booking(
                        listing=listing,
                        tenant=self.rng.choice(candidates),
                        start=start,
                        end=end,
                        status=self._status_for(start, end, today),
                    )
                )

        self.stdout.write(f"bookings: {len(bookings)}")
        return bookings

    def _status_for(self, start, end, today) -> str:
        """
        The status is derived from the dates rather than picked at random:
        a completed booking in the future would break both the state
        machine and the reviews.
        """
        if end <= today:
            roll = self.rng.random()
            if roll < 0.75:
                return BookingStatus.COMPLETED
            return BookingStatus.CANCELLED if roll < 0.9 else BookingStatus.REJECTED
        if start <= today:
            return BookingStatus.CONFIRMED
        return self.rng.choice(
            (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.CONFIRMED)
        )

    def _make_booking(self, *, listing, tenant, start, end, status: str) -> Booking:
        """
        The price, rate and title snapshots mirror services.create_booking().
        The save uses skip_validation: clean() forbids creating a booking in
        the past, yet those historical rows are exactly what is needed —
        without them there are neither completed bookings nor reviews.
        """
        booking = Booking(
            listing=listing,
            tenant=tenant,
            start_date=start,
            end_date=end,
            guests=self.rng.randint(1, min(2 * listing.rooms, 20)),
            discount_percent=self.rng.choice((0, 0, 0, 5, 10, 15)),
            status=status,
            price_per_night_snapshot=listing.price_per_night,
            listing_title_snapshot=listing.title,
            created_at=_aware(start - timedelta(days=self.rng.randint(3, 40))),
        )
        booking.total_price = booking.calculate_total()

        # the rate is frozen together with the amount, exactly as in the
        # service — otherwise revenue reports diverge from real data.
        base_amount = Listing._to_base_currency(booking.total_price)
        booking.total_price_base = base_amount
        booking.exchange_rate = (
            base_amount / booking.total_price.amount
            if booking.total_price.amount
            else Decimal("1")
        ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

        if status in (BookingStatus.CONFIRMED, BookingStatus.COMPLETED):
            booking.confirmed_at = booking.created_at + timedelta(
                hours=self.rng.randint(1, 48)
            )
        elif status in (BookingStatus.CANCELLED, BookingStatus.REJECTED):
            booking.cancelled_at = booking.created_at + timedelta(
                hours=self.rng.randint(1, 72)
            )

        booking.save(skip_validation=True)
        return booking

    # ---------------------------------------------------------------- reviews

    def _create_reviews(self, bookings: list[Booking]) -> int:
        """
        A review only on a completed booking — Review.clean() allows nothing
        else, and the rule is genuinely exercised here.
        """
        created = 0
        for booking in bookings:
            if booking.status != BookingStatus.COMPLETED or self.rng.random() > 0.65:
                continue
            # skewed towards good ratings — that is what real data looks like
            rating = self.rng.choices((5, 4, 3, 2, 1), weights=(45, 28, 15, 8, 4))[0]
            Review(
                booking=booking,
                rating=rating,
                text=self.rng.choice(REVIEW_TEXTS[rating]),
                created_at=_aware(booking.end_date + timedelta(days=self.rng.randint(1, 10))),
            ).save()
            created += 1

        self.stdout.write(f"reviews: {created}")
        return created

    # -------------------------------------------------------------- analytics

    def _create_analytics(self, listings: list[Listing], tenants: list[User]) -> int:
        """
        Views are recorded per day — the (listing, user, session_key,
        viewed_on) uniqueness forbids two rows on one day, so duplicates are
        filtered out before insertion. The ListingStats counter is written
        as a final number rather than incremented per view.
        """
        today = timezone.localdate()
        stats: list[ListingStats] = []
        total_views = 0

        for listing in listings:
            seen: set[tuple[int | None, str, object]] = set()
            records: list[ListingView] = []

            for _ in range(self.rng.randint(0, 40)):
                day = today - timedelta(days=self.rng.randint(0, 90))
                # a third of the views are anonymous — de-duplicated by
                # session_key, since in MySQL NULL != NULL and user is no key.
                if self.rng.random() < 0.35:
                    user_id, session = None, self.fake.sha1()[:32]
                else:
                    user_id, session = self.rng.choice(tenants).pk, ""
                if (user_id, session, day) in seen:
                    continue
                seen.add((user_id, session, day))
                records.append(
                    ListingView(
                        listing=listing,
                        user_id=user_id,
                        session_key=session,
                        viewed_on=day,
                        created_at=_aware(day, hour=self.rng.randint(0, 23)),
                    )
                )

            ListingView.objects.bulk_create(records)
            total_views += len(records)
            stats.append(
                ListingStats(
                    listing=listing,
                    views_count=len(records),
                    bookings_count=listing.bookings.count(),
                    last_viewed_at=max((r.created_at for r in records), default=None),
                )
            )

        ListingStats.objects.bulk_create(stats, ignore_conflicts=True)

        keywords = [city.lower() for city, _ in CITIES] + list(SEARCH_NOISE)
        queries = [
            SearchQuery(
                user=self.rng.choice(tenants) if self.rng.random() < 0.7 else None,
                # the normalised form, exactly as ListingViewSet.list writes it
                keyword=self.rng.choice(keywords),
                results_count=self.rng.randint(0, 40),
                created_at=timezone.now() - timedelta(hours=self.rng.randint(1, 2000)),
            )
            for _ in range(300)
        ]
        SearchQuery.objects.bulk_create(queries)

        self.stdout.write(f"views: {total_views}, search queries: {len(queries)}")
        return total_views

    # ----------------------------------------------------------------- report

    def _report(self, landlords, tenants, listings, bookings, reviews, views) -> None:
        by_status: dict[str, int] = {status: 0 for status in BookingStatus.values}
        for booking in bookings:
            by_status[booking.status] += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("demo data ready"))
        self.stdout.write(f"  users     : {len(landlords)} landlords, {len(tenants)} tenants")
        self.stdout.write(f"  password  : {DEMO_PASSWORD}  (e.g. landlord1@{DEMO_DOMAIN})")
        self.stdout.write(f"  listings  : {len(listings)}")
        self.stdout.write(
            f"  bookings  : {len(bookings)} — "
            + ", ".join(f"{name} {count}" for name, count in by_status.items() if count)
        )
        self.stdout.write(f"  reviews   : {reviews}")
        self.stdout.write(f"  views     : {views}")

        # the language breakdown shows at a glance whom to test emails with
        by_language: dict[str, list[str]] = {}
        for user in landlords + tenants:
            by_language.setdefault(user.language, []).append(user.email)
        self.stdout.write("  languages :")
        for code in sorted(by_language):
            emails = by_language[code]
            sample = ", ".join(emails[:3])
            more = f" (+{len(emails) - 3})" if len(emails) > 3 else ""
            self.stdout.write(f"      {code}: {len(emails)} — {sample}{more}")
