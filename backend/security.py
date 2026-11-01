"""Password hashing helpers and the local password-hash utility."""

from __future__ import annotations

import argparse
import getpass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_password_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Mật khẩu phải có ít nhất 12 ký tự.")
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, TypeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Tạo Argon2id hash cho mật khẩu quản trị.")
    parser.add_argument("command", choices=("hash-password",))
    parser.parse_args()
    password = getpass.getpass("Mật khẩu quản trị (tối thiểu 12 ký tự): ")
    confirmation = getpass.getpass("Nhập lại mật khẩu: ")
    if password != confirmation:
        parser.error("Hai mật khẩu không khớp.")
    try:
        print(hash_password(password))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()