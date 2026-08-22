from src.config import load_settings


def main() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        load_dotenv = None

    if load_dotenv:
        load_dotenv()

    load_settings()
    print("Configuration found. Real NetEase-to-Spotify sync is not implemented yet.")


if __name__ == "__main__":
    main()
