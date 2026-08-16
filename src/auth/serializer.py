from .models import User


def serialize_user(user: User) -> dict[str, int | str]:
    return {"id": user.id, "name": user.name, "email": user.email}
