from __future__ import annotations

import argparse
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Xiaoasi Mail Gateway 部署密钥")
    parser.add_argument("--admin-username", default="admin")
    args = parser.parse_args()

    print(f"ADMIN_USERNAME={args.admin_username}")
    print(f"ADMIN_PASSWORD={secrets.token_urlsafe(24)}")
    print(f"DATA_ENCRYPTION_KEY={secrets.token_urlsafe(48)}")
    print(f"MAILBOX_SESSION_SECRET={secrets.token_urlsafe(48)}")


if __name__ == "__main__":
    main()
