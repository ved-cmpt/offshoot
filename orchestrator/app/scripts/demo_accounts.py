"""The published demo accounts. Passwords come from settings."""

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class DemoUser:
    email: str
    password: str
    display_name: str
    role: str

    def public(self) -> dict[str, str]:
        return {"email": self.email, "password": self.password, "display_name": self.display_name, "role": self.role}


def demo_accounts(settings: Settings) -> list[DemoUser]:
    return [
        DemoUser(
            "viewer@demo.offshoot.dev",
            settings.demo_password_viewer.get_secret_value(),
            "Vera Viewer",
            "VIEWER",
        ),
        DemoUser(
            "engineer@demo.offshoot.dev",
            settings.demo_password_engineer.get_secret_value(),
            "Eli Engineer",
            "ENGINEER",
        ),
        DemoUser(
            "architect@demo.offshoot.dev",
            settings.demo_password_architect.get_secret_value(),
            "Ari Architect",
            "ARCHITECT",
        ),
        DemoUser(
            "admin@demo.offshoot.dev",
            settings.demo_password_admin.get_secret_value(),
            "Ada Admin",
            "ADMIN",
        ),
    ]
