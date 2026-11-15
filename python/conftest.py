from hypothesis import settings

settings.register_profile(
    "mutation", max_examples=10, deadline=None, derandomize=True
)
