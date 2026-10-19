## Development

Assuming you are running uv.

Setup pypi config `$HOME/.pypirc`

```
[testpypi]
  username = __token__
  password = pypi-...
```

```bash
make check  # ruff, and the tests
make build  # sdist and wheel in dist/
make publish-test  # Publishes to pypi test
make publish  # Publishes to pypi
```
