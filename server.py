# server.py — ponte explícita p/ app da raiz (evita conflitos de módulo "app")
import os, importlib.util

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, "app.py")

spec = importlib.util.spec_from_file_location("root_app", APP_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader, "Erro ao montar spec do app.py"
spec.loader.exec_module(module)

# expõe o Flask app para o gunicorn
app = module.app
