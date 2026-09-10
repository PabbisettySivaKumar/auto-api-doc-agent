"""Toy user API — the 'before' version used by the fixtures demo."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/users/{user_id}")
def get_user(user_id: int):
    """Fetch a single user by id."""
    return {"id": user_id}


@app.post("/users")
def create_user(name: str, email: str):
    """Create a new user."""
    return {"name": name, "email": email}


def format_user(user: dict) -> str:
    """Render a user as a display string."""
    return f"{user['name']} <{user['email']}>"
