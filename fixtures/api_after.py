"""Toy user API — the 'after' version used by the fixtures demo.

Changes vs. before:
  * get_user gained a `verbose: bool = False` query param
  * create_user gained a required `role: str` param
  * a new DELETE /users/{user_id} endpoint was added
  * format_user's signature is unchanged
"""

from fastapi import FastAPI

app = FastAPI()


@app.get("/users/{user_id}")
def get_user(user_id: int, verbose: bool = False):
    """Fetch a single user by id, optionally with extended detail."""
    return {"id": user_id}


@app.post("/users")
def create_user(name: str, email: str, role: str):
    """Create a new user with an assigned role."""
    return {"name": name, "email": email, "role": role}


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    """Delete a user by id."""
    return {"deleted": user_id}


def format_user(user: dict) -> str:
    """Render a user as a display string."""
    return f"{user['name']} <{user['email']}>"
