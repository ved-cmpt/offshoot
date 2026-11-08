"""The published demo accounts (ADR-050).

Short usernames and one simple password, shown on the sign-in page. They are not secrets: the
demo holds synthetic data only, and in demo mode no account can be changed, disabled or added
(`app/routers/users.py`), so a visitor cannot lock the others out.
"""

from dataclasses import dataclass

# Published on purpose. Argon2id still hashes it like any other password.
DEMO_PASSWORD = "demo1234"  # noqa: S105


@dataclass(frozen=True)
class DemoUser:
    username: str
    email: str
    password: str
    display_name: str
    role: str

    def public(self) -> dict[str, str]:
        return {
            "username": self.username,
            "email": self.email,
            "password": self.password,
            "display_name": self.display_name,
            "role": self.role,
        }


DEMO_USERS = (
    DemoUser("viewer", "viewer@demo.offshoot.dev", DEMO_PASSWORD, "Vera Viewer", "VIEWER"),
    DemoUser("engineer", "engineer@demo.offshoot.dev", DEMO_PASSWORD, "Eli Engineer", "ENGINEER"),
    DemoUser("architect", "architect@demo.offshoot.dev", DEMO_PASSWORD, "Ari Architect", "ARCHITECT"),
    DemoUser("admin", "admin@demo.offshoot.dev", DEMO_PASSWORD, "Ada Admin", "ADMIN"),
)
DEMO_EMAILS = frozenset(user.email for user in DEMO_USERS)
DEMO_USERNAMES = frozenset(user.username for user in DEMO_USERS)


def demo_accounts(_settings: object = None) -> list[DemoUser]:
    return list(DEMO_USERS)
