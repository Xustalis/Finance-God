from app.core.security import hash_password, verify_password


def test_hash_password_accepts_short_password_and_verifies_it():
    hashed = hash_password("demo123456")

    assert verify_password("demo123456", hashed)
    assert not verify_password("wrong-password", hashed)
