import ast
from pathlib import Path

from fastapi_commons import api_keys, auth


def test_token_verifier_does_not_import_db_models() -> None:
    tree = ast.parse(Path(auth.__file__).read_text())
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}

    assert not {m for m in modules if m.startswith(('python3_commons.db', 'sqlalchemy'))}


def test_api_key_verifier_still_in_auth() -> None:
    assert auth.get_api_key_verifier is api_keys.get_api_key_verifier
