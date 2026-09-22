from __future__ import annotations

from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.users.management.commands.init_groups import GROUP_MATRIX
from apps.users.models import User
from core.testing import PASSWORD, APITestCase, BaseTestCase, make_user

REGISTER_URL = "/api/users/register/"
ME_URL = "/api/users/me/"


class UserManagerTests(BaseTestCase):
    def test_create_user_normalises_email_and_hashes_password(self):
        user = User.objects.create_user(email="Alice@EXAMPLE.com", password=PASSWORD)
        self.assertEqual(user.email, "Alice@example.com")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIsNotNone(user.public_id)

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password=PASSWORD)

    def test_create_superuser(self):
        admin = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_superuser_must_be_staff(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="a@example.com", password=PASSWORD, is_staff=False)

    def test_str_is_email(self):
        self.assertEqual(str(make_user(email="bob@example.com")), "bob@example.com")


class InitGroupsCommandTests(BaseTestCase):
    def test_groups_get_the_matrix_permissions(self):
        for group_name, rules in GROUP_MATRIX.items():
            group = Group.objects.get(name=group_name)
            codenames = set(group.permissions.values_list("codename", flat=True))
            expected = {f"{action}_{model}" for _, model, actions in rules for action in actions}
            with self.subTest(group=group_name):
                self.assertEqual(codenames, expected)

    def test_command_is_idempotent(self):
        out = StringIO()
        call_command("init_groups", stdout=out)
        self.assertIn("tenants: updated", out.getvalue())
        self.assertEqual(Group.objects.filter(name__in=GROUP_MATRIX).count(), len(GROUP_MATRIX))


class RegisterTests(APITestCase):
    def payload(self, **overrides):
        data = {
            "email": "new@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "group": "tenants",
        }
        data.update(overrides)
        return data

    def test_register_creates_user_in_group(self):
        response = self.client.post(REGISTER_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["email"], "new@example.com")
        self.assertEqual(body["groups"], ["tenants"])
        self.assertNotIn("password", body)
        self.assertNotIn("id", body)
        user = User.objects.get(email="new@example.com")
        self.assertTrue(user.check_password(PASSWORD))

    def test_register_as_landlord(self):
        response = self.client.post(REGISTER_URL, self.payload(group="landlords"), format="json")
        self.assertEqual(response.json()["groups"], ["landlords"])

    def test_passwords_must_match(self):
        response = self.client.post(
            REGISTER_URL, self.payload(password_confirm="Other-pass-999"), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_weak_password_is_rejected(self):
        response = self.client.post(
            REGISTER_URL, self.payload(password="12345678", password_confirm="12345678"),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", {e["attr"] for e in response.json()["errors"]})

    def test_unknown_group_is_rejected(self):
        response = self.client.post(REGISTER_URL, self.payload(group="admins"), format="json")
        self.assertEqual(response.status_code, 400)

    def test_duplicate_email_is_rejected(self):
        make_user(email="new@example.com")
        response = self.client.post(REGISTER_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 400)


class ProfileTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user(group="tenants", first_name="Ann")

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get(ME_URL).status_code, 401)

    def test_me_returns_own_profile(self):
        self.login(self.user)
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["public_id"], str(self.user.public_id))

    def test_me_patch_updates_editable_fields_only(self):
        self.login(self.user)
        response = self.client.patch(
            ME_URL, {"first_name": "Anna", "email": "hacker@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Anna")
        self.assertNotEqual(self.user.email, "hacker@example.com")

    def test_retrieve_by_public_id(self):
        other = make_user()
        self.login(self.user)
        response = self.client.get(f"/api/users/{other.public_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], other.email)

    def test_there_is_no_user_list(self):
        self.login(self.user)
        self.assertIn(self.client.get("/api/users/").status_code, (404, 405))


class JWTAuthTests(APITestCase):
    def test_obtain_and_use_token(self):
        user = make_user(email="jwt@example.com")
        response = self.client.post(
            "/api/auth/token/", {"email": "jwt@example.com", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        tokens = response.json()
        self.assertIn("refresh", tokens)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.get(ME_URL).json()["email"], user.email)

        refreshed = self.client.post(
            "/api/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("access", refreshed.json())

    def test_wrong_password(self):
        make_user(email="jwt@example.com")
        response = self.client.post(
            "/api/auth/token/", {"email": "jwt@example.com", "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, 401)
