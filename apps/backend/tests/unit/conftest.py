import pytest

# The checks of the "build it and run it" tests live in a shared module, not
# in a test file, so pytest wouldn't explain a failed assert there (it would
# say "AssertionError" and nothing about the values) unless told to.
pytest.register_assert_rewrite("generated_backend_e2e")
