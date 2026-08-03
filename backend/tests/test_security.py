"""密码与访问令牌的纯单元测试。"""

import unittest
from uuid import uuid4

from backend.app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from backend.app.models.identity import User


class SecurityTests(unittest.TestCase):
    def test_password_is_hashed_and_verifiable(self):
        encoded = hash_password("a-strong-test-password")

        self.assertNotIn("a-strong-test-password", encoded)
        self.assertTrue(verify_password("a-strong-test-password", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_access_token_contains_authenticated_user_id(self):
        user = User(
            id=uuid4(),
            email="tester@example.com",
            display_name="Tester",
            password_hash="unused",
            role="researcher",
            is_active=True,
        )

        token, expires_in = create_access_token(user)

        self.assertEqual(decode_access_token(token), user.id)
        self.assertGreater(expires_in, 0)


if __name__ == "__main__":
    unittest.main()
