# Migrations (Alembic)

The schema is defined by the ORM models in `app/models/`. Alembic tracks changes.

```bash
# create a migration after changing a model
alembic revision --autogenerate -m "describe your change"

# apply migrations
alembic upgrade head

# roll back one
alembic downgrade -1
```

On a **fresh** database the app also runs `create_all()` on startup, so it boots
with zero setup even before you run Alembic. Once you start editing models, use
Alembic migrations as the source of truth for schema changes.
