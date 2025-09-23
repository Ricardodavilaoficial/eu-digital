[1mdiff --git a/routes/cupons.py b/routes/cupons.py[m
[1mindex c7453a3..fabe715 100644[m
[1m--- a/routes/cupons.py[m
[1m+++ b/routes/cupons.py[m
[36m@@ -1,6 +1,7 @@[m
[31m-from flask import Blueprint, request, jsonify[m
[32m+[m[32m# routes/cupons.py[m
[32m+[m[32mfrom flask import Blueprint, request, jsonify[m[41m [m
 from google.cloud import firestore[m
[31m-from datetime import datetime[m
[32m+[m[32mfrom datetime import datetime, timedelta  # <-- ADICIONE timedelta[m
 [m
 cupons_bp = Blueprint("cupons_bp", __name__)[m
 [m
