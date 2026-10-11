# Package marker: makes `python -m unittest tests.test_contract` resolve to this
# repo. Without it, a user-site `tests` package shadows the directory on
# sys.path and the locked verify command fails with ModuleNotFoundError.
