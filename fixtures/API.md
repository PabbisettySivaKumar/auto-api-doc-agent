# User API

The user service exposes the following endpoints.

## GET /users/{user_id}

Fetch a single user by id.

**Path params**

- `user_id` (int) — the user's id.

## POST /users

Create a new user.

**Body params**

- `name` (str)
- `email` (str)

## Helpers

`format_user(user)` renders a user as a display string.
