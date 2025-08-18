# ==========================
# PROJETO: MEI ROBÔ
# SPRINT DROP A — BACKEND + FRONTEND MÍNIMO
# ==========================
# Estrutura de arquivos sugerida neste drop:
#
# backend/
#   main.py
#   services/
#     auth.py
#     db.py
#     coupons.py
#     schedule.py
#   requirements.txt
#   openapi.json
# frontend/
#   public/
#     assets/
#       layout.js
#       styles.css
#       logo.png          # coloque aqui o ícone 1024x1024 (pode começar com um placeholder)
#     partials/
#       header.html
#       footer.html
#   pages/
#     ativar.html
#     admin-cupons.html
#     agenda.html
#     dashboard.html
#     login.html          # opcional nesta etapa, se já usa Firebase Auth embutido
#   firebase.json         # host estático
#   .firebaserc           # projeto


############################
# backend/requirements.txt
############################
# Pinar versões estáveis para Render (Py3.11)
Flask==3.0.3
Gunicorn==22.0.0
flask-cors==4.0.1
firebase-admin==6.5.0
google-cloud-firestore==2.16.0
python-dateutil==2.9.0.post0
pytz==2024.1


############################
# backend/services/db.py
############################
import os
from datetime import datetime
from google.cloud import firestore
import firebase_admin
from firebase_admin import credentials, firestore as fa_firestore

# Inicialização Firebase Admin + Firestore
_project_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not firebase_admin._apps:
    if _project_creds:
        firebase_admin.initialize_app()
    else:
        # Em dev local, permitir init sem credenciais explícitas se já configurado via ADC
        firebase_admin.initialize_app()

db = fa_firestore.client()


def get_doc(path: str):
    snap = db.document(path).get()
    return snap.to_dict() if snap.exists else None


def set_doc(path: str, data: dict):
    db.document(path).set(data, merge=True)


def update_doc(path: str, data: dict):
    db.document(path).set(data, merge=True)


def add_doc(path: str, data: dict):
    return db.collection(path).add(data)[1].id


def query_collection(path: str, **filters):
    ref = db.collection(path)
    for k, v in filters.items():
        ref = ref.where(k, "==", v)
    return [ {"id": d.id, **d.to_dict()} for d in ref.stream() ]


def now_ts():
    return datetime.utcnow().isoformat() + "Z"


############################
# backend/services/auth.py
############################
import os
import functools
from flask import request, g, jsonify
from firebase_admin import auth
from .db import get_doc

ADMIN_CLAIM_KEY = "role"
ADMIN_CLAIM_VALUE = "admin"


def _verify_token_from_header():
    """Verifica o bearer token do Firebase Auth e injeta g.user (uid, claims)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1]
    decoded = auth.verify_id_token(token)
    return {
        "uid": decoded.get("uid"),
        "email": decoded.get("email"),
        "claims": decoded,
    }


def auth_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            user = _verify_token_from_header()
        except Exception:
            return jsonify({"erro":"auth/invalid-token"}), 401
        if not user:
            return jsonify({"erro":"auth/missing-token"}), 401
        g.user = type("User", (), user)
        # Bootstrap do documento do profissional, se não existir
        prof_path = f"profissionais/{g.user.uid}"
        if get_doc(prof_path) is None:
            from .db import set_doc
            set_doc(prof_path, {
                "perfil": {"segmento": None, "especializacao": None},
                "plano": {"status":"bloqueado", "origem": None, "expiraEm": None, "quotaMensal": 0},
                "createdAt": now_ts()
            })
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        resp = auth_required(lambda: None)()
        if resp is not None:  # auth_required retornou uma resposta (erro)
            return resp
        # Checa custom claim de admin
        claims = getattr(g.user, "claims", {})
        if claims.get(ADMIN_CLAIM_KEY) != ADMIN_CLAIM_VALUE:
            return jsonify({"erro":"auth/not-admin"}), 403
        return fn(*args, **kwargs)
    return wrapper


############################
# backend/services/coupons.py
############################
from datetime import datetime, timezone
from .db import db, get_doc, set_doc, update_doc, query_collection

COL_CUPONS = "cuponsAtivacao"


def criar_cupom(body: dict, criado_por: str):
    codigo = body.get("codigo")
    if not codigo:
        # gera código simples AAAAA-1111
        import random, string
        codigo = "".join(random.choices(string.ascii_uppercase, k=5)) + "-" + "".join(random.choices(string.digits, k=4))
    cupom = {
        "codigo": codigo.upper(),
        "tipo": body.get("tipo", "trial"),  # trial | desconto
        "valor": body.get("valor"),
        "expiraEm": body.get("expiraEm"),
        "usosMax": int(body.get("usosMax", 1)),
        "usos": 0,
        "ativo": True,
        "criadoPorUid": criado_por,
        "escopo": body.get("escopo", "global"),  # global | uid
        "uidDestino": body.get("uidDestino"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    db.collection(COL_CUPONS).document().set(cupom)
    return cupom


def find_cupom_by_codigo(codigo: str):
    res = db.collection(COL_CUPONS).where("codigo", "==", codigo.upper()).limit(1).stream()
    for d in res:
        c = d.to_dict()
        c["_id"] = d.id
        return c
    return None


def validar_consumir_cupom(cupom: dict, uid: str):
    if not cupom or not cupom.get("ativo"):
        return False, "Cupom inválido ou inativo.", None
    # expiração
    exp = cupom.get("expiraEm")
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt:
                return False, "Cupom expirado.", None
        except Exception:
            return False, "Formato de expiração inválido.", None
    # escopo
    if cupom.get("escopo") == "uid" and cupom.get("uidDestino") != uid:
        return False, "Este cupom não é destinado a este usuário.", None
    if cupom.get("usos") >= cupom.get("usosMax", 1):
        return False, "Limite de usos atingido.", None

    # Consome
    doc_ref = db.collection(COL_CUPONS).document(cupom["_id"])
    doc_ref.update({"usos": cupom.get("usos", 0) + 1})

    # Novo plano
    plano = {"status":"ativo", "origem":"cupom", "expiraEm": exp, "quotaMensal": 10000}
    return True, "ok", plano


############################
# backend/services/schedule.py
############################
from datetime import datetime, timedelta
import pytz
from dateutil import parser
from .db import db

WEEKEND = {5, 6}  # 5=Saturday, 6=Sunday


def _parse_dt(dt_iso: str):
    return parser.isoparse(dt_iso).astimezone(pytz.UTC)


def validar_agendamento_v1(uid: str, data: dict):
    # Campos obrigatórios
    for k in ["clienteId", "servicoId", "dataHora"]:
        if not data.get(k):
            return False, f"Campo obrigatório: {k}", None

    start = _parse_dt(data["dataHora"]).replace(second=0, microsecond=0)
    now = datetime.utcnow().replace(tzinfo=pytz.UTC)

    # +2 dias
    if start < now + timedelta(days=2):
        return False, "+2 dias mínimos para agendar.", None
    # Sem fim de semana
    if start.weekday() in WEEKEND:
        return False, "Sem fins de semana.", None

    dur = int(data.get("duracaoMin", 0)) or 30
    end = start + timedelta(minutes=dur)

    # Conflito simples
    col = db.collection(f"profissionais/{uid}/agendamentos").where("estado", "in", ["solicitado", "confirmado"]).stream()
    for d in col:
        ag = d.to_dict()
        ag_start = _parse_dt(ag["dataHora"])
        ag_end   = ag_start + timedelta(minutes=int(ag.get("duracaoMin",30)))
        if not (end <= ag_start or start >= ag_end):
            return False, "Conflito de horário.", None

    novo = {
        "clienteId": data["clienteId"],
        "servicoId": data["servicoId"],
        "dataHora": start.isoformat(),
        "duracaoMin": dur,
        "estado": "solicitado",
        "origem": data.get("origem", "dashboard"),
        "observacoes": data.get("observacoes"),
    }
    return True, "ok", novo


def salvar_agendamento(uid: str, ag: dict):
    ref = db.collection(f"profissionais/{uid}/agendamentos").document()
    ref.set(ag)
    ag["id"] = ref.id
    return ag


def atualizar_estado_agendamento(uid: str, ag_id: str, body: dict):
    acao = body.get("acao")
    ref = db.document(f"profissionais/{uid}/agendamentos/{ag_id}")
    snap = ref.get()
    if not snap.exists:
        raise ValueError("Agendamento não encontrado")
    ag = snap.to_dict()

    if acao == "confirmar":
        ag["estado"] = "confirmado"
    elif acao == "cancelar":
        ag["estado"] = "cancelado"
    elif acao == "reagendar":
        nova = body.get("dataHora")
        if not nova:
            raise ValueError("Data/hora obrigatória para reagendar")
        ag["dataHora"] = nova
        ag["estado"] = "solicitado"
    else:
        raise ValueError("Ação inválida")

    ref.set(ag, merge=True)
    ag["id"] = ag_id
    return ag


############################
# backend/openapi.json
############################
{
  "openapi": "3.1.0",
  "info": {"title": "MEI Robô API", "version": "1.0.0"},
  "paths": {
    "/licencas/status": {"get": {"summary": "Status da licença"}},
    "/licencas/ativar-cupom": {"post": {"summary": "Ativar via cupom"}},
    "/admin/cupons": {"post": {"summary": "Gerar cupom"}},
    "/agendamentos": {"get": {"summary": "Listar"}, "post": {"summary": "Criar"}},
    "/agendamentos/{id}": {"patch": {"summary": "Atualizar estado"}},
    "/healthz": {"get": {"summary": "Health"}}
  }
}


############################
# backend/main.py
############################
import os
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from services.auth import auth_required, admin_required
from services.db import get_doc, set_doc, update_doc
from services.coupons import criar_cupom, find_cupom_by_codigo, validar_consumir_cupom
from services.schedule import validar_agendamento_v1, salvar_agendamento, atualizar_estado_agendamento

app = Flask(__name__)
CORS(app, supports_credentials=True)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True}), 200


@app.get("/docs")
def docs():
    return send_from_directory(os.path.dirname(__file__), "openapi.json")


# /licencas/status
@app.get("/licencas/status")
@auth_required
def licenca_status():
    from flask import g
    uid = g.user.uid
    prof = get_doc(f"profissionais/{uid}") or {}
    plano = prof.get("plano", {"status":"bloqueado"})
    return jsonify(plano), 200


# /licencas/ativar-cupom
@app.post("/licencas/ativar-cupom")
@auth_required
def ativar_cupom():
    from flask import g
    uid = g.user.uid
    codigo = (request.json or {}).get("codigo", "").strip().upper()
    cupom = find_cupom_by_codigo(codigo)
    ok, msg, plano = validar_consumir_cupom(cupom, uid)
    if not ok:
        return jsonify({"erro": msg}), 400
    update_doc(f"profissionais/{uid}", {"plano": plano})
    return jsonify({"status":"ativo","origem":"cupom"}), 200


# /admin/cupons (POST)
@app.post("/admin/cupons")
@admin_required
def admin_criar_cupom():
    from flask import g
    body = request.get_json() or {}
    cupom = criar_cupom(body, criado_por=g.user.uid)
    return jsonify(cupom), 201


# /agendamentos (GET/POST)
@app.get("/agendamentos")
@auth_required
def listar_agendamentos():
    from flask import g
    from services.db import db
    docs = db.collection(f"profissionais/{g.user.uid}/agendamentos").order_by("dataHora").stream()
    out = []
    for d in docs:
        o = d.to_dict(); o["id"] = d.id
        out.append(o)
    return jsonify(out), 200


@app.post("/agendamentos")
@auth_required
def criar_agendamento():
    from flask import g
    data = request.get_json() or {}
    ok, msg, ag = validar_agendamento_v1(g.user.uid, data)
    if not ok:
        return jsonify({"erro": msg}), 400
    ag = salvar_agendamento(g.user.uid, ag)
    return jsonify(ag), 201


@app.patch("/agendamentos/<ag_id>")
@auth_required
def atualizar_agendamento_route(ag_id):
    from flask import g
    body = request.get_json() or {}
    try:
        ag = atualizar_estado_agendamento(g.user.uid, ag_id, body)
    except Exception as e:
        return jsonify({"erro": str(e)}), 400
    return jsonify(ag), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)


############################
# frontend/public/assets/layout.js
############################
// Carrega header e footer canônicos
(async function(){
  const header = document.getElementById('app-header');
  const footer = document.getElementById('app-footer');
  if (header) header.innerHTML = await (await fetch('/public/partials/header.html')).text();
  if (footer) footer.innerHTML = await (await fetch('/public/partials/footer.html')).text();
})();


############################
# frontend/public/partials/header.html
############################
<header class="w-full px-4 py-3 flex items-center gap-3" style="background:#075e54;color:#fff">
  <a href="/pages/dashboard.html" class="flex items-center gap-2" style="text-decoration:none;color:#fff">
    <img src="/public/assets/logo.png" alt="MEI Robô" style="width:30px;height:auto;border-radius:6px" />
    <strong style="font-size:18px">MEI Robô</strong>
  </a>
  <nav style="margin-left:auto;display:flex;gap:16px">
    <a href="/pages/ativar.html" style="color:#fff">Ativar Conta</a>
    <a href="/pages/agenda.html" style="color:#fff">Agenda</a>
    <a href="/pages/admin-cupons.html" style="color:#fff">Admin</a>
  </nav>
</header>


############################
# frontend/public/partials/footer.html
############################
<footer class="w-full px-4 py-6" style="background:#128c7e;color:#fff;margin-top:40px">
  <small>© 2025 MEI Robô — Integração com WhatsApp Business via parceiros (ex.: YCloud). Termos/Privacidade.</small>
</footer>


############################
# frontend/public/assets/styles.css
############################
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif;margin:0;background:#f7f7f7;color:#111}
.container{max-width:960px;margin:0 auto;padding:16px}
.card{background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.06);padding:16px}
.btn{background:#25d366;border:none;color:#111;padding:10px 14px;border-radius:8px;cursor:pointer}
.btn[disabled]{opacity:.6;cursor:not-allowed}
.input{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px}
.table{width:100%;border-collapse:collapse}
.table th,.table td{border-bottom:1px solid #eee;padding:8px;text-align:left}


############################
# frontend/pages/dashboard.html
############################
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Dashboard — MEI Robô</title>
  <link rel="stylesheet" href="/public/assets/styles.css" />
  <script defer src="/public/assets/layout.js"></script>
</head>
<body>
  <div id="app-header"></div>
  <main class="container">
    <div class="card">
      <h2>Dashboard</h2>
      <p>Se sua conta estiver <em>bloqueada</em>, use a página “Ativar Conta”.</p>
      <button class="btn" id="btnStatus">Ver status da licença</button>
      <pre id="out"></pre>
    </div>
  </main>
  <div id="app-footer"></div>
  <script>
    async function status(){
      const token = localStorage.getItem('idToken');
      const r = await fetch('/licencas/status', {headers:{'Authorization':'Bearer '+token}});
      document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
    }
    document.getElementById('btnStatus').onclick = status;
  </script>
</body>
</html>


############################
# frontend/pages/ativar.html
############################
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Ativar Conta — MEI Robô</title>
  <link rel="stylesheet" href="/public/assets/styles.css" />
  <script defer src="/public/assets/layout.js"></script>
</head>
<body>
  <div id="app-header"></div>
  <main class="container">
    <div class="card">
      <h2>Ativar Conta com Cupom</h2>
      <input class="input" id="codigo" placeholder="Código do cupom (ex.: ABCDE-1234)" />
      <button class="btn" id="ativar">Ativar</button>
      <pre id="out"></pre>
    </div>
  </main>
  <div id="app-footer"></div>
  <script>
    document.getElementById('ativar').onclick = async () => {
      const token = localStorage.getItem('idToken');
      const codigo = document.getElementById('codigo').value.trim();
      const r = await fetch('/licencas/ativar-cupom', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+token}, body: JSON.stringify({codigo})});
      const j = await r.json();
      document.getElementById('out').textContent = JSON.stringify(j, null, 2);
    }
  </script>
</body>
</html>


############################
# frontend/pages/admin-cupons.html
############################
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Admin — Cupons</title>
  <link rel="stylesheet" href="/public/assets/styles.css" />
  <script defer src="/public/assets/layout.js"></script>
</head>
<body>
  <div id="app-header"></div>
  <main class="container">
    <div class="card">
      <h2>Gerar Cupom</h2>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <select id="tipo" class="input">
          <option value="trial">trial</option>
          <option value="desconto">desconto</option>
        </select>
        <input id="valor" class="input" placeholder="valor (opcional)" />
        <input id="expiraEm" class="input" placeholder="expiraEm (ISO ex.: 2025-12-31T23:59:00Z)" />
        <input id="usosMax" class="input" placeholder="usosMax (default 1)" />
        <select id="escopo" class="input">
          <option value="global">global</option>
          <option value="uid">uid</option>
        </select>
        <input id="uidDestino" class="input" placeholder="uid destino (se escopo=uid)" />
      </div>
      <button class="btn" id="criar">Criar</button>
      <pre id="out"></pre>
    </div>
  </main>
  <div id="app-footer"></div>
  <script>
    document.getElementById('criar').onclick = async () => {
      const token = localStorage.getItem('idToken');
      const body = {
        tipo: document.getElementById('tipo').value,
        valor: Number(document.getElementById('valor').value || 0) || null,
        expiraEm: document.getElementById('expiraEm').value || null,
        usosMax: Number(document.getElementById('usosMax').value || 1),
        escopo: document.getElementById('escopo').value,
        uidDestino: document.getElementById('uidDestino').value || null
      };
      const r = await fetch('/admin/cupons', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+token}, body: JSON.stringify(body)});
      const j = await r.json();
      document.getElementById('out').textContent = JSON.stringify(j, null, 2);
    }
  </script>
</body>
</html>


############################
# frontend/pages/agenda.html
############################
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Agenda — MEI Robô</title>
  <link rel="stylesheet" href="/public/assets/styles.css" />
  <script defer src="/public/assets/layout.js"></script>
</head>
<body>
  <div id="app-header"></div>
  <main class="container">
    <div class="card">
      <h2>Agenda</h2>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px">
        <input id="clienteId" class="input" placeholder="clienteId" />
        <input id="servicoId" class="input" placeholder="servicoId" />
        <input id="dataHora" class="input" placeholder="data/hora ISO (ex.: 2025-08-25T14:00:00Z)" />
        <input id="duracaoMin" class="input" placeholder="duração (min)" />
      </div>
      <button class="btn" id="criar">Criar</button>
      <pre id="out"></pre>

      <h3>Meus agendamentos</h3>
      <button class="btn" id="listar">Atualizar lista</button>
      <table class="table" id="tbl"><thead><tr><th>id</th><th>dataHora</th><th>dur</th><th>estado</th><th>Ações</th></tr></thead><tbody></tbody></table>
    </div>
  </main>
  <div id="app-footer"></div>
  <script>
    const token = () => localStorage.getItem('idToken');

    async function listar(){
      const r = await fetch('/agendamentos', {headers:{'Authorization':'Bearer '+token()}});
      const arr = await r.json();
      const tb = document.querySelector('#tbl tbody');
      tb.innerHTML = '';
      arr.forEach(x => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${x.id}</td><td>${x.dataHora}</td><td>${x.duracaoMin}</td><td>${x.estado}</td>
          <td>
            <button class='btn' data-id='${x.id}' data-ac='confirmar'>Confirmar</button>
            <button class='btn' data-id='${x.id}' data-ac='cancelar'>Cancelar</button>
          </td>`;
        tb.appendChild(tr);
      });
      tb.querySelectorAll('button').forEach(b => b.onclick = async (ev)=>{
        const id = ev.target.getAttribute('data-id');
        const ac = ev.target.getAttribute('data-ac');
        const r = await fetch(`/agendamentos/${id}`, {method:'PATCH', headers:{'Content-Type':'application/json','Authorization':'Bearer '+token()}, body: JSON.stringify({acao:ac})});
        alert(await r.text());
        listar();
      });
    }

    document.getElementById('listar').onclick = listar;

    document.getElementById('criar').onclick = async () => {
      const body = {
        clienteId: document.getElementById('clienteId').value,
        servicoId: document.getElementById('servicoId').value,
        dataHora: document.getElementById('dataHora').value,
        duracaoMin: Number(document.getElementById('duracaoMin').value || 30)
      };
      const r = await fetch('/agendamentos', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+token()}, body: JSON.stringify(body)});
      const j = await r.json();
      document.getElementById('out').textContent = JSON.stringify(j, null, 2);
      listar();
    }
  </script>
</body>
</html>


############################
# frontend/firebase.json (exemplo simples de hosting)
############################
{
  "hosting": {
    "public": ".",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [
      {"source": "/", "destination": "/pages/dashboard.html"},
      {"source": "/pages/**", "function": null}
    ]
  }
}


############################
# frontend/.firebaserc (exemplo)
############################
{
  "projects": { "default": "seu-projeto-firebase" }
}


############################
# Procfile (se usar no Render via Start Command, opcional)
############################
# web: gunicorn main:app --bind 0.0.0.0:$PORT --workers 2 --threads 8 --timeout 120
