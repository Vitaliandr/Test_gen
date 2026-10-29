import argparse
import getpass
import sys

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from sitegen.settings import KEYRING_SERVICE, KEYRING_USER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ключ OpenRouter в хранилище учётных данных системы")
    parser.add_argument("--delete", action="store_true", help="удалить ключ из хранилища")
    args = parser.parse_args(argv)

    try:
        if args.delete:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            print("ключ удалён из хранилища")
            return 0
        # getpass, чтоб ключ не остался в истории
        key = getpass.getpass("Ключ OpenRouter (ввод не отображается): ").strip()
        if not key.startswith("sk-or-"):
            print("не похоже на ключ OpenRouter, он начинается с sk-or-")
            return 1
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    except PasswordDeleteError:
        print("в хранилище ключа нет")
        return 1
    except KeyringError as e:
        print(f"хранилище недоступно: {type(e).__name__}")
        return 1
    print("ключ сохранён, из .env его теперь можно удалить")
    return 0


if __name__ == "__main__":
    sys.exit(main())
