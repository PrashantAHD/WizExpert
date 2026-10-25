"""Synthetic fixtures assembled at runtime so no literal address is stored in source."""


def mail(user: str, domain: str = "example") -> str:
    return user + "@" + domain + ".com"
